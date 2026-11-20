package fabric.core

import java.util.Base64

/** MirrorWeave (C9) — SPEC §9: Android screen stream → desktop; desktop ⇄ Android remote control; camera stills/telemetry/video.
 *
 *  This file is the **platform-free half** (pure JVM, JUnit-tested): wire contracts, bitstream checks, the frame/video sources
 *  that the Android services feed, input-event verification + gesture geometry, and Camera2 focus maths. The Android half
 *  (MediaProjection [ScreenCaptureSource] grabber, MediaCodec H.264 encoder, AccessibilityService gestures, Camera2 focus) lives
 *  in the app module (`fabric.pocketloom.*`) — compiled into the APK, **never run on a phone yet** (`real_unverified_on_device`). */
object MirrorWeave {
    const val MILESTONE = "C9"
    const val MAX_FRAME_BYTES = 8 * 1024 * 1024
    val STILL_KINDS = setOf("screen", "camera_still", "telemetry")
    val VIDEO_KINDS = setOf("screen_video", "camera_video")
    val STILL_CODECS = setOf("png", "jpeg", "webp", "json")
    val VIDEO_CODECS = setOf("vp8", "vp9", "h264")
    private val STREAM_RE = Regex("^[a-z0-9][a-z0-9_-]{0,31}$")

    fun validStream(s: String) = STREAM_RE.matches(s)

    fun sniff(codec: String, d: ByteArray): Boolean = when (codec) {
        "png" -> d.size >= 8 && d[0] == 0x89.toByte() && String(d, 1, 3, Charsets.US_ASCII) == "PNG" && d[4] == 0x0D.toByte()
        "jpeg" -> d.size >= 3 && d[0] == 0xFF.toByte() && d[1] == 0xD8.toByte() && d[2] == 0xFF.toByte()
        "webp" -> d.size >= 12 && String(d, 0, 4, Charsets.US_ASCII) == "RIFF" && String(d, 8, 4, Charsets.US_ASCII) == "WEBP"
        "json" -> runCatching { Json.parse(String(d, Charsets.UTF_8)) }.isSuccess
        in VIDEO_CODECS -> Video.sniff(codec, d)
        else -> false
    }
}

/** Bitstream helpers — same rules as `forge.mirrorvideo` (Python). */
object Video {
    fun h264NalTypes(d: ByteArray): List<Int> {
        val out = ArrayList<Int>(); var i = 0; val n = d.size
        while (i + 3 < n) {
            val sc3 = d[i] == 0.toByte() && d[i + 1] == 0.toByte() && d[i + 2] == 1.toByte()
            val sc4 = d[i] == 0.toByte() && d[i + 1] == 0.toByte() && d[i + 2] == 0.toByte() && d[i + 3] == 1.toByte()
            if (sc3 || sc4) { val j = i + if (sc3) 3 else 4; if (j < n) out.add(d[j].toInt() and 0x1F); i = j } else i++
        }
        return out
    }

    fun isKeyframe(codec: String, p: ByteArray): Boolean {
        if (p.isEmpty()) return false
        return when (codec) {
            "vp8" -> (p[0].toInt() and 1) == 0 && p.size >= 10 &&
                p[3] == 0x9d.toByte() && p[4] == 0x01.toByte() && p[5] == 0x2a.toByte()
            "vp9" -> {
                val b = ((p[0].toInt() and 0xFF) shl 8) or (if (p.size > 1) p[1].toInt() and 0xFF else 0)
                val bits = String.format("%16s", Integer.toBinaryString(b)).replace(' ', '0')
                if (!bits.startsWith("10")) false else {
                    val profile = (bits[2] - '0') or ((bits[3] - '0') shl 1)
                    val i = 4 + if (profile == 3) 1 else 0
                    bits[i] == '0' && bits[i + 1] == '0'
                }
            }
            "h264" -> h264NalTypes(p).any { it == 5 || it == 7 }
            else -> throw IllegalArgumentException("unknown video codec $codec")
        }
    }

    fun sniff(codec: String, p: ByteArray): Boolean = p.isNotEmpty() && when (codec) {
        "vp8" -> (p[0].toInt() and 1) == 1 || (p.size >= 6 && p[3] == 0x9d.toByte() && p[4] == 0x01.toByte() && p[5] == 0x2a.toByte())
        "vp9" -> (p[0].toInt() and 0xC0) == 0x80
        "h264" -> p.size >= 4 && p[0] == 0.toByte() && p[1] == 0.toByte() && (p[2] == 1.toByte() || (p[2] == 0.toByte() && p[3] == 1.toByte()))
        else -> false
    }
}

class FrameEnvelope(val stream: String, val seq: Long, val tsMs: Long, val kind: String, val codec: String,
                    val width: Int, val height: Int, val data: ByteArray, val keyframe: Boolean = false) {
    val isVideo get() = kind in MirrorWeave.VIDEO_KINDS

    init {
        require(MirrorWeave.validStream(stream)) { "bad stream id" }
        require(kind in MirrorWeave.STILL_KINDS || kind in MirrorWeave.VIDEO_KINDS) { "unknown frame kind $kind" }
        require(codec in MirrorWeave.STILL_CODECS || codec in MirrorWeave.VIDEO_CODECS) { "unknown codec $codec" }
        require((kind in MirrorWeave.VIDEO_KINDS) == (codec in MirrorWeave.VIDEO_CODECS)) { "video kinds need a video codec" }
        require((kind == "telemetry") == (codec == "json")) { "telemetry frames must be json and json frames must be telemetry" }
        require(seq >= 0 && tsMs >= 0 && width >= 0 && height >= 0) { "negative field" }
        require(data.isNotEmpty() && data.size <= MirrorWeave.MAX_FRAME_BYTES) { "frame must be 1..${MirrorWeave.MAX_FRAME_BYTES} bytes" }
        require(MirrorWeave.sniff(codec, data)) { "payload is not valid $codec" }
        if (codec in MirrorWeave.VIDEO_CODECS) require(keyframe == Video.isKeyframe(codec, data)) { "keyframe flag does not match the bitstream" }
    }

    fun toWire(): Map<String, Any?> {
        val m = mutableMapOf<String, Any?>("stream" to stream, "seq" to seq, "ts_ms" to tsMs, "kind" to kind, "codec" to codec,
            "width" to width, "height" to height, "data_b64" to Base64.getEncoder().encodeToString(data))
        if (isVideo) m["keyframe"] = keyframe
        return m
    }

    companion object {
        fun fromWire(w: Map<String, Any?>) = FrameEnvelope(w["stream"] as String, w["seq"].asLong(), w["ts_ms"].asLong(),
            w["kind"] as String, w["codec"] as String, (w["width"] ?: 0).asLong().toInt(), (w["height"] ?: 0).asLong().toInt(),
            Base64.getDecoder().decode(w["data_b64"] as String), w["keyframe"] as? Boolean ?: false)
    }
}

interface MirrorSource { fun frames(): Sequence<FrameEnvelope> }

/** REAL: a sequence of still images (screen captures / camera stills) as ordered frames. */
class StillsSource(private val stream: String, private val images: Iterable<ByteArray>, private val kind: String = "screen",
                   private val codec: String = "png", private val startSeq: Long = 0,
                   private val clock: () -> Long = System::currentTimeMillis) : MirrorSource {
    override fun frames(): Sequence<FrameEnvelope> = images.asSequence().mapIndexed { i, d ->
        FrameEnvelope(stream, startSeq + i, clock(), kind, codec, 0, 0, d)
    }
}

/** One captured still from a platform grabber (MediaProjection ImageReader → JPEG on Android). */
class Still(val data: ByteArray, val codec: String, val width: Int, val height: Int)

/** Live screen capture as stills. The platform half supplies [grab] (Android: `fabric.pocketloom.ScreenMirrorService`); this
 *  class owns pacing (fps), sequence numbers, frame skipping when the grabber has nothing new, and an optional frame budget. */
class ScreenCaptureSource(private val stream: String, private val grab: () -> Still?, private val fps: Int = 5,
                          private val maxFrames: Int = Int.MAX_VALUE, private val startSeq: Long = 0,
                          private val clock: () -> Long = System::currentTimeMillis,
                          private val sleep: (Long) -> Unit = { Thread.sleep(it) }, private val running: () -> Boolean = { true }) : MirrorSource {
    init { require(fps in 1..30) { "fps must be 1..30" } }

    override fun frames(): Sequence<FrameEnvelope> = sequence {
        val period = 1000L / fps
        var seq = startSeq; var n = 0
        while (n < maxFrames && running()) {
            val t0 = clock()
            val s = grab()
            if (s != null) { yield(FrameEnvelope(stream, seq++, t0, "screen", s.codec, s.width, s.height, s.data)); n++ }
            val left = period - (clock() - t0)
            if (left > 0) sleep(left)
        }
    }
}

/** One encoder output buffer (Android MediaCodec): `config` = SPS/PPS (BUFFER_FLAG_CODEC_CONFIG). */
class VideoPacket(val data: ByteArray, val config: Boolean = false, val key: Boolean = false, val ptsUs: Long = 0)

/** Encoder packets → video envelopes. Codec-config buffers are held and prepended to the next keyframe so every keyframe the
 *  desktop receives is independently decodable (it may join mid-stream or resync after a gap). */
class VideoStreamSource(private val stream: String, private val packets: Sequence<VideoPacket>, private val codec: String = "h264",
                        private val width: Int = 0, private val height: Int = 0, private val kind: String = "screen_video",
                        private val startSeq: Long = 0, private val clock: () -> Long = System::currentTimeMillis) : MirrorSource {
    init { require(codec in MirrorWeave.VIDEO_CODECS) { "unknown video codec $codec" }; require(kind in MirrorWeave.VIDEO_KINDS) }

    override fun frames(): Sequence<FrameEnvelope> = sequence {
        var config: ByteArray? = null; var seq = startSeq
        for (p in packets) {
            if (p.config) { config = p.data; continue }
            var data = p.data
            val nals = if (codec == "h264") Video.h264NalTypes(data) else emptyList()
            if (codec == "h264" && config != null && (p.key || 5 in nals) && 7 !in nals) data = config + data
            yield(FrameEnvelope(stream, seq++, clock(), kind, codec, width, height, data, Video.isKeyframe(codec, data)))
        }
    }
}

// ------------------------------------------------------------------------------------------- desktop → phone input

/** A desktop-queued event, validated with the same rules as `forge.mirrorweave.validate_android_event`. */
class InputEvent(val type: String, val x: Double = 0.0, val y: Double = 0.0, val x2: Double = 0.0, val y2: Double = 0.0,
                 val durationMs: Long = 0, val key: String = "", val text: String = "", val mode: String = "",
                 val distanceM: Double? = null, val hasPoint: Boolean = false) {
    companion object {
        val TYPES = setOf("tap", "long_press", "swipe", "key", "text", "focus")
        val KEYS = setOf("back", "home", "recents", "notifications", "quick_settings")
        val FOCUS_MODES = setOf("auto", "manual", "lock", "unlock")
        const val MAX_TEXT = 256

        private fun unit(m: Map<String, Any?>, k: String): Double {
            val v = (m[k] ?: throw IllegalArgumentException("missing $k")).asDouble()
            require(v in 0.0..1.0) { "$k must be in [0,1]" }; return v
        }

        fun parse(m: Map<String, Any?>): InputEvent {
            val t = m["type"] as? String ?: throw IllegalArgumentException("missing type")
            require(t in TYPES) { "bad type $t" }
            val ev = when (t) {
                "tap" -> InputEvent(t, unit(m, "x"), unit(m, "y"), hasPoint = true)
                "long_press" -> InputEvent(t, unit(m, "x"), unit(m, "y"), durationMs = (m["duration_ms"] ?: 600L).asLong(), hasPoint = true)
                "swipe" -> InputEvent(t, unit(m, "x"), unit(m, "y"), unit(m, "x2"), unit(m, "y2"), (m["duration_ms"] ?: 300L).asLong(), hasPoint = true)
                "key" -> { val k = m["key"] as? String ?: ""; require(k in KEYS) { "bad key $k" }; InputEvent(t, key = k) }
                "text" -> { val s = m["text"] as? String ?: ""; require(s.isNotEmpty() && s.length <= MAX_TEXT) { "text must be 1..$MAX_TEXT chars" }; InputEvent(t, text = s) }
                else -> {
                    val mode = m["mode"] as? String ?: "auto"
                    require(mode in FOCUS_MODES) { "bad focus mode $mode" }
                    val d = if (mode == "manual") (m["distance_m"] ?: throw IllegalArgumentException("manual focus needs distance_m")).asDouble() else null
                    if (d != null) require(d in 0.05..1000.0) { "distance_m must be in [0.05, 1000]" }
                    val pt = m.containsKey("x") || m.containsKey("y")
                    InputEvent(t, if (pt) unit(m, "x") else 0.0, if (pt) unit(m, "y") else 0.0, mode = mode, distanceM = d, hasPoint = pt)
                }
            }
            if (t == "long_press" || t == "swipe") require(ev.durationMs in 1..5000) { "duration_ms must be in [1, 5000]" }
            return ev
        }

        /** Verify the desktop's per-event MAC (session key) over the exact JSON text received, then parse + validate. */
        fun verified(keyHex: String, client: String, row: Map<String, Any?>): Pair<Long, InputEvent> {
            val seq = row["seq"].asLong(); val ej = row["event_json"] as String
            val want = LoomCrypto.mac(LoomCrypto.unhex(keyHex), "input", client, seq.toString(), ej)
            if (!LoomCrypto.same(want, row["sig"] as? String ?: "")) throw SecurityException("input event $seq: bad signature")
            return seq to parse(Json.obj(ej))
        }
    }
}

/** A gesture stroke in screen pixels: Android `GestureDescription.StrokeDescription(path, startMs, durationMs)`. */
data class Stroke(val points: List<Pair<Float, Float>>, val startMs: Long, val durationMs: Long)

object GestureMapper {
    const val TAP_MS = 50L

    private fun px(u: Double, size: Int) = (u * (size - 1)).toFloat()

    fun strokes(ev: InputEvent, w: Int, h: Int): List<Stroke> {
        require(w > 0 && h > 0) { "screen size unknown" }
        return when (ev.type) {
            "tap" -> listOf(Stroke(listOf(px(ev.x, w) to px(ev.y, h)), 0, TAP_MS))
            "long_press" -> listOf(Stroke(listOf(px(ev.x, w) to px(ev.y, h)), 0, ev.durationMs))
            "swipe" -> listOf(Stroke(listOf(px(ev.x, w) to px(ev.y, h), px(ev.x2, w) to px(ev.y2, h)), 0, ev.durationMs))
            else -> emptyList()
        }
    }
}

/** What the phone does with a verified event — implemented by `fabric.pocketloom.MirrorAccessibilityService`. */
interface InputSink {
    fun screenSize(): Pair<Int, Int>
    fun gesture(strokes: List<Stroke>): Boolean
    fun globalAction(key: String): Boolean
    fun typeText(text: String): Boolean
    fun focus(req: FocusRequest): Boolean
}

/** Pulls queued events from the paired desktop, verifies every MAC, executes in order, remembers the last seq. */
class AndroidInputInjector(private val link: LoomLinkClient, private val sink: InputSink, var after: Long = -1) {
    fun pollOnce(): List<Map<String, Any?>> {
        if (!link.has("mirror")) throw LinkException(403, "capability 'mirror' not granted")
        val s = link.session ?: throw LinkException(0, "not paired")
        val rows = link.postJson(null, "/mirror/input/poll", mapOf("after" to after))["events"].asList().map { it.asMap() }
        return rows.map { row ->
            val (seq, ev) = InputEvent.verified(s.keyHex, s.clientId, row)
            after = seq
            mapOf("seq" to seq, "type" to ev.type, "ok" to execute(ev))
        }
    }

    fun execute(ev: InputEvent): Boolean = when (ev.type) {
        "tap", "long_press", "swipe" -> sink.screenSize().let { (w, h) -> sink.gesture(GestureMapper.strokes(ev, w, h)) }
        "key" -> sink.globalAction(ev.key)
        "text" -> sink.typeText(ev.text)
        "focus" -> sink.focus(FocusRequest.from(ev))
        else -> false
    }
}

// ------------------------------------------------------------------------------------------- camera focus (C9 / C10)

/** Camera focus request → Camera2 parameters. Camera2 focus distance is in **diopters** (1/m), 0 = infinity, and the lens's
 *  `LENS_INFO_MINIMUM_FOCUS_DISTANCE` is the largest diopter value it can reach. */
class FocusRequest(val mode: String, val distanceM: Double? = null, val x: Double? = null, val y: Double? = null) {
    init {
        require(mode in InputEvent.FOCUS_MODES) { "bad focus mode $mode" }
        if (mode == "manual") require(distanceM != null && distanceM in 0.05..1000.0) { "manual focus needs distance_m in [0.05, 1000]" }
    }

    /** Diopters clamped to the lens range; null when not manual. */
    fun diopters(minFocusDiopters: Float): Float? = distanceM?.let { (1.0 / it).toFloat().coerceIn(0f, minFocusDiopters) }

    /** Metering rectangle (left, top, right, bottom) on the active sensor array, `frac` of its size, clamped inside. */
    fun meteringRect(sensorW: Int, sensorH: Int, frac: Double = 0.1): IntArray? {
        if (x == null || y == null) return null
        val hw = (sensorW * frac / 2).toInt().coerceAtLeast(1); val hh = (sensorH * frac / 2).toInt().coerceAtLeast(1)
        val cx = (x * (sensorW - 1)).toInt(); val cy = (y * (sensorH - 1)).toInt()
        val l = (cx - hw).coerceIn(0, sensorW - 1); val t = (cy - hh).coerceIn(0, sensorH - 1)
        return intArrayOf(l, t, (cx + hw).coerceIn(l + 1, sensorW), (cy + hh).coerceIn(t + 1, sensorH))
    }

    companion object {
        fun from(ev: InputEvent) = FocusRequest(ev.mode, ev.distanceM, if (ev.hasPoint) ev.x else null, if (ev.hasPoint) ev.y else null)
    }
}

/** Camera focus control. The platform half is `fabric.pocketloom.Camera2Focus` (implements [FocusSink]). */
interface FocusSink { fun apply(req: FocusRequest): Boolean }

class FocusController(private val sink: FocusSink) {
    fun setFocus(distanceM: Double) = sink.apply(FocusRequest("manual", distanceM))
    fun auto(x: Double? = null, y: Double? = null) = sink.apply(FocusRequest("auto", null, x, y))
    fun lock() = sink.apply(FocusRequest("lock"))
}

/** REAL client for the desktop's MirrorWeave endpoints (signed by [LoomLinkClient]). */
class MirrorClient(private val link: LoomLinkClient) {
    private fun need(cap: String) { if (!link.has(cap)) throw LinkException(403, "capability '$cap' not granted") }

    fun pushFrame(env: FrameEnvelope): Map<String, Any?> { need("mirror"); return link.postJson(null, "/mirror/frame", env.toWire()) }

    fun push(source: MirrorSource): List<Map<String, Any?>> = source.frames().map { pushFrame(it) }.toList()

    fun latest(stream: String): Map<String, Any?> { need("mirror"); return link.postJson(null, "/mirror/latest", mapOf("stream" to stream)) }

    fun control(target: String, action: String, name: String = "", args: Map<String, Any?> = emptyMap()): Map<String, Any?> {
        need("drive_studio")
        return link.postJson(null, "/mirror/control", mapOf("target" to target, "action" to action, "name" to name, "args" to args))
    }

    /** Allow-listed read-only desktop query (`forge.status`, `groundweave.show`, `mirror.stats`). */
    fun query(name: String) = control("desktop", "query", name)

    /** Phone → Studio input (key / pointer / scroll), validated again on the desktop. */
    fun studioKey(key: String, shift: Boolean = false) = control("desktop", "input", "key", mapOf("key" to key, "shift" to shift))
    fun studioPointer(action: String, x: Double, y: Double, button: String = "left") =
        control("desktop", "input", "pointer", mapOf("action" to action, "x" to x, "y" to y, "button" to button))
    fun studioScroll(dy: Int) = control("desktop", "input", "scroll", mapOf("dy" to dy))
}
