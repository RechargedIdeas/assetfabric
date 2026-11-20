package fabric.pocketloom

import android.app.Activity
import android.content.ActivityNotFoundException
import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.SurfaceTexture
import android.media.projection.MediaProjectionManager
import android.provider.Settings
import android.view.MotionEvent
import android.view.Surface
import android.view.TextureView
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.os.Build
import android.os.Bundle
import android.provider.MediaStore
import android.text.InputType
import android.view.View
import android.view.ViewGroup
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.EditText
import android.widget.HorizontalScrollView
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.Spinner
import android.widget.TextView
import fabric.core.LoomCrypto
import fabric.core.Palettes
import fabric.core.PairingUri
import fabric.core.PocketLoomCore
import fabric.core.asList
import fabric.core.asMap
import fabric.core.FocusRequest
import java.util.concurrent.Executors
import kotlin.random.Random

/** PocketLoom standalone UI (C3): Generate · Library · Capture · Link · Telemetry.
 *  Plain platform widgets (no AndroidX) to keep the APK small; every string comes from resources.
 *  All FabricCore work runs on one background thread; the UI thread only renders. */
class MainActivity : Activity() {
    private lateinit var core: PocketLoomCore
    private val worker = Executors.newSingleThreadExecutor()
    private lateinit var header: TextView
    private lateinit var content: LinearLayout
    private var tab = 0
    private var pendingUri: PairingUri? = null
    private var selectedId: String? = null

    companion object { const val REQ_CAMERA = 1; const val REQ_IMPORT = 2; const val REQ_MIRROR = 3; const val REQ_CAMERA_PERM = 4; const val CLIP_SECONDS = 8 }
    private var mirrorMode = "stills"
    private var focus: Camera2Focus? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        core = CoreHolder.get(this)
        val root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dp(12), dp(12), dp(12), dp(12)) }
        header = TextView(this).apply { textSize = 13f }
        root.addView(TextView(this).apply { setText(R.string.app_name); textSize = 22f })
        root.addView(header)
        val tabs = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        listOf(R.string.tab_generate, R.string.tab_library, R.string.tab_capture, R.string.tab_link, R.string.tab_telemetry)
            .forEachIndexed { i, s -> tabs.addView(Button(this).apply { setText(s); setOnClickListener { show(i) } }) }
        root.addView(HorizontalScrollView(this).apply { addView(tabs) })
        content = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        root.addView(ScrollView(this).apply { addView(content) }, LinearLayout.LayoutParams(-1, 0, 1f))
        setContentView(root)
        handleIntent(intent)
        if (pendingUri == null) show(0)
    }

    override fun onNewIntent(intent: Intent) { super.onNewIntent(intent); handleIntent(intent) }

    private fun handleIntent(i: Intent?) {
        val data = i?.data ?: return
        if (data.scheme == "loomlink") {
            pendingUri = runCatching { PairingUri.parse(data.toString()) }.getOrNull()
            show(3)
        }
    }

    override fun onDestroy() { focus?.close(); worker.shutdown(); super.onDestroy() }

    // ------------------------------------------------------------------ helpers
    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()
    private fun text(s: String) = TextView(this).apply { this.text = s; setPadding(0, dp(4), 0, dp(4)) }
    private fun button(res: Int, f: () -> Unit) = Button(this).apply { setText(res); setOnClickListener { f() } }
    private fun bg(work: () -> Unit) = worker.execute { try { work() } catch (e: Exception) { ui { toastLine(getString(R.string.link_failed, e.message ?: e.toString())) } } }
    private fun ui(f: () -> Unit) = runOnUiThread(f)
    private var statusLine: TextView? = null
    private fun toastLine(s: String) { statusLine?.text = s }

    private fun refreshHeader() = bg {
        val st = core.status()
        val paired = st["paired"]?.asMap()
        val mode = if (paired == null) getString(R.string.mode_standalone) else getString(R.string.mode_paired, paired["server"])
        val n = (st["store"].asMap()["assets"] as Number).toInt()
        ui { header.text = getString(R.string.header_status, core.nodeId, n, (st["offload_pending"] as Number).toInt(), mode) }
    }

    private fun show(i: Int) {
        tab = i; content.removeAllViews(); statusLine = null
        when (i) { 0 -> genTab(); 1 -> libTab(); 2 -> capTab(); 3 -> linkTab(); else -> telTab() }
        refreshHeader()
    }

    private fun preview(png: ByteArray, into: ImageView) {
        val b = BitmapFactory.decodeByteArray(png, 0, png.size) ?: return
        val scale = maxOf(1, dp(256) / maxOf(b.width, b.height))
        into.setImageBitmap(Bitmap.createScaledBitmap(b, b.width * scale, b.height * scale, false))  // nearest-neighbour
    }

    // ------------------------------------------------------------------ C2/C3 generate
    private fun genTab() {
        val kinds = listOf("cave", "sprite")
        val kind = Spinner(this).apply { adapter = ArrayAdapter.createFromResource(this@MainActivity, R.array.gen_kinds, android.R.layout.simple_spinner_dropdown_item) }
        val palettes = Palettes.names()
        val pal = Spinner(this).apply { adapter = ArrayAdapter(this@MainActivity, android.R.layout.simple_spinner_dropdown_item, palettes) }
        kind.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(p: AdapterView<*>?, v: View?, pos: Int, id: Long) {
                pal.setSelection(palettes.indexOf(if (pos == 0) "cave_stone" else "hero_teal").coerceAtLeast(0))
            }
            override fun onNothingSelected(p: AdapterView<*>?) {}
        }
        val seed = EditText(this).apply { setHint(R.string.gen_seed_hint); inputType = InputType.TYPE_CLASS_NUMBER; setText("1") }
        val img = ImageView(this).apply { adjustViewBounds = true }
        val out = text("")
        val note = text("")
        val rejected = text("")
        statusLine = out
        content.addView(text(getString(R.string.gen_kind))); content.addView(kind)
        content.addView(text(getString(R.string.gen_palette))); content.addView(pal)
        content.addView(seed)
        content.addView(button(R.string.gen_random) { seed.setText(String.format(java.util.Locale.ROOT, "%d", Random.nextInt(1, 1_000_000))) })
        content.addView(button(R.string.gen_button) {
            val k = kinds[kind.selectedItemPosition]; val s = seed.text.toString().toLongOrNull() ?: 1L
            val p = palettes.getOrNull(pal.selectedItemPosition)
            out.setText(R.string.gen_running)
            bg {
                val r = core.generate(k, s, p)
                val res = r["result"]?.asMap()
                if (res == null) { ui { out.text = getString(R.string.gen_failed, r["error"] ?: r["status"]) }; return@bg }
                val gates = res["gates"].asMap().entries.joinToString(", ") { "${it.key} ${getString(if (it.value == true) R.string.gate_pass else R.string.gate_fail)}" }
                val sel = r["selection"].asMap()
                val ladder = (sel["skipped"].asList().map { it.asMap()["rung"] } + sel["backend"]).joinToString(" → ")
                val png = core.store.get("${k}_$s")?.let { core.store.read(it["sha256"] as String) }
                ui {
                    out.text = getString(R.string.gen_result, k, s, sel["backend"], (r["ms"] as Number).toDouble(), gates, res["sha256"])
                    note.text = getString(R.string.gen_backend_note, ladder)
                    rejected.text = if (res["ok"] != true) getString(R.string.gen_gates_failed) else null
                    if (png != null && res["ok"] == true) preview(png, img)
                    refreshHeader()
                }
            }
        })
        content.addView(out); content.addView(note); content.addView(rejected); content.addView(img)
    }

    // ------------------------------------------------------------------ C3 library
    private fun libTab() {
        val img = ImageView(this).apply { adjustViewBounds = true }
        val sel = text("")
        statusLine = sel
        content.addView(img); content.addView(sel)
        content.addView(button(R.string.lib_delete) { selectedId?.let { id -> bg { core.store.remove(id); ui { selectedId = null; show(1) } } } })
        bg {
            val items = core.store.list().sortedBy { it["id"] as String }
            ui {
                if (items.isEmpty()) content.addView(text(getString(R.string.lib_empty)))
                for (e in items) {
                    val id = e["id"] as String
                    val label = if (e["conflict_of"] != null) getString(R.string.lib_conflict, id) else id
                    content.addView(text(getString(R.string.lib_item, label, e["kind"], (e["size"] as Number).toLong())).apply {
                        setOnClickListener {
                            selectedId = id; sel.text = getString(R.string.lib_selected, id)
                            bg { core.store.read(e["sha256"] as String)?.let { b -> ui { preview(b, img) } } }
                        }
                    })
                }
            }
        }
    }

    // ------------------------------------------------------------------ C4 capture
    private fun capTab() {
        val out = text(""); statusLine = out
        content.addView(text(getString(R.string.cap_intro)))
        content.addView(button(R.string.cap_take) {
            val i = Intent(MediaStore.ACTION_IMAGE_CAPTURE).putExtra(MediaStore.EXTRA_OUTPUT, CaptureProvider.URI)
                .addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION or Intent.FLAG_GRANT_READ_URI_PERMISSION)
            CaptureProvider.pendingFile(this).delete()
            try { startActivityForResult(i, REQ_CAMERA) } catch (e: ActivityNotFoundException) { out.setText(R.string.cap_no_camera) }
        })
        content.addView(button(R.string.cap_import) {
            startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("image/*"), REQ_IMPORT)
        })
        content.addView(button(R.string.cam_live) {
            if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED)
                requestPermissions(arrayOf(Manifest.permission.CAMERA), REQ_CAMERA_PERM)
            else liveCamera(out)
        })
        content.addView(button(R.string.cam_record) {
            if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
                requestPermissions(arrayOf(Manifest.permission.CAMERA), REQ_CAMERA_PERM); return@button
            }
            focus?.close(); focus = null                              // one camera client at a time
            out.setText(R.string.cam_recording)
            Camera2Video(this).record(CLIP_SECONDS) { f ->
                if (f == null) ui { out.setText(R.string.cam_failed) }
                else bg {
                    val r = runCatching { core.captureVideo(f.readBytes(), "camera",
                        mapOf("captured_at" to System.currentTimeMillis(), "device" to Build.MODEL, "seconds" to CLIP_SECONDS)) }
                    f.delete()
                    ui { out.text = if (r.isSuccess) getString(R.string.cam_clip_queued) else getString(R.string.cam_failed) }
                }
            }
        })
        content.addView(out)
        bg {
            val n = core.store.list().count { it["kind"] == "capture" }
            ui { content.addView(text(resources.getQuantityString(R.plurals.cap_count, n, n))) }
        }
    }

    /** C9/C10 live camera with tap-to-focus (Camera2). A desktop can also queue focus events (MirrorAccessibilityService). */
    private fun liveCamera(out: TextView) {
        focus?.close(); focus = null
        val tv = TextureView(this)
        content.addView(tv, LinearLayout.LayoutParams(-1, dp(320)))
        tv.surfaceTextureListener = object : TextureView.SurfaceTextureListener {
            override fun onSurfaceTextureAvailable(st: SurfaceTexture, w: Int, h: Int) {
                st.setDefaultBufferSize(1280, 720)
                focus = Camera2Focus(this@MainActivity, Surface(st)).also { f ->
                    f.open { ok -> ui { out.setText(if (ok) R.string.cam_ready else R.string.cam_failed) } }
                }
            }
            override fun onSurfaceTextureSizeChanged(st: SurfaceTexture, w: Int, h: Int) {}
            override fun onSurfaceTextureDestroyed(st: SurfaceTexture): Boolean { focus?.close(); focus = null; return true }
            override fun onSurfaceTextureUpdated(st: SurfaceTexture) {}
        }
        tv.setOnTouchListener { v, e ->
            if (e.action == MotionEvent.ACTION_UP) {
                val ok = focus?.apply(FocusRequest("auto", null, (e.x / v.width).toDouble().coerceIn(0.0, 1.0), (e.y / v.height).toDouble().coerceIn(0.0, 1.0))) ?: false
                out.setText(if (ok) R.string.cam_focus_ok else R.string.cam_failed)
                v.performClick()
            }
            true
        }
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == REQ_CAMERA_PERM && grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED && tab == 2) statusLine?.let { liveCamera(it) }
    }

    private fun startMirror(mode: String) {
        mirrorMode = mode
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED)
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 0)
        startActivityForResult(getSystemService(MediaProjectionManager::class.java).createScreenCaptureIntent(), REQ_MIRROR)
    }

    @Deprecated("platform API; no AndroidX ActivityResult in this build")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == REQ_MIRROR) {
            if (resultCode == RESULT_OK && data != null) startForegroundService(mirrorIntent(this, resultCode, data, mirrorMode))
            else toastLine(getString(R.string.mirror_no_consent))
            return
        }
        if (resultCode != RESULT_OK) return
        val source = if (requestCode == REQ_CAMERA) "camera" else "import"
        val read: () -> ByteArray? = when (requestCode) {
            REQ_CAMERA -> { { CaptureProvider.pendingFile(this).takeIf { it.exists() }?.readBytes() } }
            REQ_IMPORT -> { { data?.data?.let { u -> contentResolver.openInputStream(u)?.use { it.readBytes() } } } }
            else -> return
        }
        if (tab != 2) show(2)
        worker.execute {
            try {
                val bytes = read() ?: throw IllegalStateException("no image data")
                val r = core.capture(bytes, source, mapOf("captured_at" to System.currentTimeMillis(),
                    "device" to "${Build.MANUFACTURER} ${Build.MODEL}", "sdk" to Build.VERSION.SDK_INT))
                CaptureProvider.pendingFile(this).delete()
                ui { toastLine(getString(R.string.cap_saved, r["entry"].asMap()["id"], bytes.size)); refreshHeader() }
            } catch (e: Exception) {
                ui { toastLine(getString(R.string.cap_failed, e.message ?: e.toString())) }
            }
        }
    }

    // ------------------------------------------------------------------ C5/C6 link
    private fun linkTab() {
        val out = text(""); statusLine = out
        val state = text("")
        val queued = text("")
        val url = EditText(this).apply { setHint(R.string.link_url_hint); inputType = InputType.TYPE_TEXT_VARIATION_URI }
        val code = EditText(this).apply { setHint(R.string.link_code_hint); inputType = InputType.TYPE_TEXT_FLAG_CAP_CHARACTERS }
        pendingUri?.let { url.setText(it.url); code.setText(it.code); out.setText(R.string.link_from_qr); pendingUri = null }
        content.addView(text(getString(R.string.link_intro))); content.addView(state); content.addView(queued)
        content.addView(url); content.addView(code)
        content.addView(button(R.string.link_pair) {
            val c = code.text.toString()
            if (!LoomCrypto.validCode(c)) { out.setText(R.string.link_bad_code); return@button }
            val u = url.text.toString()
            worker.execute {
                try {
                    val s = core.pair(u, c)
                    ui { out.text = getString(R.string.link_pair_ok, s.caps.joinToString(", ")); show(3) }
                } catch (e: Exception) { ui { out.text = getString(R.string.link_pair_failed, e.message ?: e.toString()) } }
            }
        })
        content.addView(button(R.string.link_drain) { bg { val r = core.drain(); ui { out.text = getString(R.string.link_drain_ok, (r["sent"] as Number).toInt(), (r["pending"] as Number).toInt()); refreshHeader() } } })
        content.addView(button(R.string.link_sync) { bg { val r = core.sync(); ui { out.text = getString(R.string.link_sync_ok, r["pushed"] as Int, r["pulled"] as Int, r["conflicts"].asList().size); refreshHeader() } } })
        content.addView(button(R.string.link_unpair) { bg { core.unpair(); ui { show(3) } } })
        // C9 MirrorWeave: screen → desktop (MediaProjection, user consent each time) and desktop → phone control (Accessibility)
        content.addView(text(getString(R.string.mirror_intro)))
        content.addView(button(R.string.mirror_start_stills) { startMirror("stills") })
        content.addView(button(R.string.mirror_start_h264) { startMirror("h264") })
        content.addView(button(R.string.mirror_stop) { startService(Intent(this, ScreenMirrorService::class.java).setAction(ScreenMirrorService.ACTION_STOP)) })
        content.addView(button(R.string.mirror_remote_settings) { startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)) })
        content.addView(text(if (ScreenMirrorService.running) resources.getQuantityString(R.plurals.mirror_running, ScreenMirrorService.framesSent, ScreenMirrorService.framesSent)
            else ScreenMirrorService.lastError?.let { getString(R.string.mirror_error, it) } ?: getString(R.string.mirror_idle)))
        content.addView(out)
        bg {
            val s = core.link.session
            val q = core.queue.pending().size
            ui {
                state.text = if (s == null) getString(R.string.link_not_paired) else getString(R.string.link_paired, s.serverId, s.url, s.caps.joinToString(", "))
                queued.text = resources.getQuantityString(R.plurals.link_queue, q, q)
            }
        }
    }

    // ------------------------------------------------------------------ C3 telemetry
    private fun telTab() {
        content.addView(button(R.string.tel_refresh) { show(4) })
        bg {
            val st = core.status()
            val lines = ArrayList<String>()
            lines += getString(R.string.tel_node, core.nodeId, PocketLoomCore.VERSION)
            lines += getString(R.string.tel_device, "${Build.MANUFACTURER} ${Build.MODEL}", Build.VERSION.SDK_INT, Runtime.getRuntime().availableProcessors())
            val store = st["store"].asMap(); lines += getString(R.string.tel_store, (store["assets"] as Number).toInt(), (store["bytes"] as Number).toLong())
            val m = st["models"].asMap(); lines += getString(R.string.tel_models, (m["models"] as Number).toInt(), (m["bytes"] as Number).toLong(), (m["budget"] as Number).toLong())
            lines += getString(R.string.tel_queue, (st["offload_pending"] as Number).toInt(), (st["offload_done"] as Number).toInt())
            val t = st["telemetry"].asMap(); lines += getString(R.string.tel_events, (t["events"] as Number).toInt(), (t["errors"] as Number).toInt())
            for ((op, v) in t["local_jobs"].asMap()) {
                val j = v.asMap()
                lines += getString(R.string.tel_job, op, (j["n"] as Number).toInt(), (j["mean_ms"] as Number).toDouble(), (j["max_ms"] as Number).toDouble())
            }
            for ((kind, rungs) in st["backends"].asMap()) for (r in rungs.asList().map { it.asMap() }) {
                lines += if (r["available"] == true) getString(R.string.tel_backend, kind, r["rung"]) else getString(R.string.tel_backend_skip, r["rung"], r["reason"])
            }
            ui { lines.forEach { content.addView(text(it)) } }
        }
    }
}
