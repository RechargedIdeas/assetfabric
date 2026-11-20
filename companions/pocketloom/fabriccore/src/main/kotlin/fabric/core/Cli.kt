package fabric.core

import java.io.File
import kotlin.system.exitProcess

/** Desktop/JVM entry point for FabricCore — same code the APK runs. Used by `forge accept C1…C6`
 *  (Python↔Kotlin interop) and for headless debugging. Prints one JSON document to stdout.
 *
 *  fabriccore-all.jar <cmd> --home DIR [options]
 *    info | status
 *    gen --kind cave|sprite --seed N [--count K] [--palette P]
 *    capture --file F [--source S]
 *    offload --op hashchain --seed S [--rounds R]           (queue a job for the desktop)
 *    pair (--uri loomlink://… | --url U --code C) [--caps offload,sync]
 *    drain | sync | unpair
 *    put --id ID --file F [--kind K]                          (edit the local store; sync tests)
 *    mirror-push --file F --stream S [--kind screen|camera_still|telemetry] [--codec png|jpeg|webp|json] [--seq N]   (C9)
 *    mirror-latest --stream S | mirror-query --name N [--action query|input|focus] [--target desktop|android]       (C9)
 *    mirror-video-push --file F.ivf|F.h264 --codec vp8|vp9|h264 --stream S       (C9: push a recorded packet stream)
 *    mirror-input-poll [--after N]      (C9: fetch + verify desktop-queued events; executes into a recording sink, prints it)
 *    studio-key --key K [--shift true]  (C9: phone → Studio key event)
 *    stubs                                                     (C9–C12: every Kotlin stub must refuse — prints each refusal)
 */
fun main(args: Array<String>) {
    val cmd = args.firstOrNull() ?: usage()
    val opts = HashMap<String, String>()
    var i = 1
    while (i < args.size) {
        val k = args[i]; require(k.startsWith("--")) { "bad arg $k" }
        opts[k.removePrefix("--")] = args.getOrNull(i + 1) ?: ""; i += 2
    }
    val out: Any? = try {
        if (cmd == "stubs") allStubs()
        else if (cmd == "info") mapOf("version" to PocketLoomCore.VERSION, "ops" to LocalExecutor(null) { emptyList() }.ops.sorted(),
            "palettes" to Palettes.names(), "onnx_runtime_bundled" to GenBackends.ONNX_RUNTIME_BUNDLED)
        else {
            val core = PocketLoomCore(File(opts["home"] ?: usage()), opts["node"])
            when (cmd) {
                "status" -> core.status()
                "gen" -> {
                    val seed = (opts["seed"] ?: "1").toLong(); val n = (opts["count"] ?: "1").toInt()
                    (0 until n).map { core.generate(opts["kind"] ?: "cave", seed + it, opts["palette"]) }
                }
                "capture" -> core.capture(File(opts["file"]!!).readBytes(), opts["source"] ?: "import",
                    mapOf("captured_at" to System.currentTimeMillis(), "device" to "jvm-cli"))
                "offload" -> core.dispatcher.submit(JobSpec("off_" + LoomCrypto.nonce().substring(0, 10), opts["op"] ?: "hashchain",
                    mapOf("seed" to (opts["seed"] ?: "0"), "rounds" to (opts["rounds"] ?: "20000").toLong())), preferOffload = true)
                "pair" -> core.pair(opts["uri"] ?: opts["url"]!!, opts["code"],
                    (opts["caps"] ?: "offload,sync").split(",").filter { it.isNotBlank() }).let { it.toMap() - "key" }
                "drain" -> core.drain() + ("results" to core.queue.results())
                "sync" -> core.sync()
                "unpair" -> { core.unpair(); mapOf("ok" to true) }
                "put" -> core.store.put(opts["id"]!!, opts["kind"] ?: "sprite", File(opts["file"]!!).readBytes(), mapOf("source" to "cli"))
                "index" -> core.store.index()
                "mirror-push" -> MirrorClient(core.link).pushFrame(FrameEnvelope(opts["stream"] ?: "screen", (opts["seq"] ?: "0").toLong(),
                    System.currentTimeMillis(), opts["kind"] ?: "screen", opts["codec"] ?: "png", 0, 0, File(opts["file"]!!).readBytes()))
                "mirror-latest" -> MirrorClient(core.link).latest(opts["stream"] ?: "screen")
                "mirror-query" -> MirrorClient(core.link).control(opts["target"] ?: "desktop", opts["action"] ?: "query", opts["name"] ?: "")
                "mirror-video-push" -> {
                    val codec = opts["codec"] ?: "vp8"; val raw = File(opts["file"]!!).readBytes()
                    val pkts = if (codec == "h264") Ivf.splitH264Aus(raw) else Ivf.parse(raw)
                    val src = VideoStreamSource(opts["stream"] ?: "kvideo", pkts.asSequence().map { VideoPacket(it) }, codec, 32, 32)
                    MirrorClient(core.link).push(src).let { acks -> mapOf("pushed" to acks.size, "last" to acks.lastOrNull()) }
                }
                "mirror-input-poll" -> {
                    val sink = RecordingSink()
                    val r = AndroidInputInjector(core.link, sink, (opts["after"] ?: "-1").toLong()).pollOnce()
                    mapOf("results" to r, "performed" to sink.log)
                }
                "studio-key" -> MirrorClient(core.link).studioKey(opts["key"] ?: "a", opts["shift"] == "true")
                else -> usage()
            }
        }
    } catch (e: StubException) {
        println(Json.write(e.toMap())); exitProcess(4)
    } catch (e: LinkException) {
        println(Json.write(mapOf("error" to e.message, "status" to e.status))); exitProcess(3)
    } catch (e: Exception) {
        println(Json.write(mapOf("error" to e.toString()))); exitProcess(1)
    }
    println(Json.write(out))
}

private fun usage(): Nothing {
    System.err.println("usage: fabriccore <info|status|gen|capture|offload|pair|drain|sync|unpair|put|index> --home DIR …")
    exitProcess(2)
}

/** C9–C12: invoke every Kotlin stub; each must throw [StubException] (reported here), never return. */
fun allStubs(): Map<String, Any?> {
    val probes: Map<String, () -> Unit> = mapOf(
        "lens.arcore_session" to { ArCoreSession().start() },
        "depth.dense_estimate" to { DepthEstimator().estimate(ByteArray(0)) },
        "recon.splatforge" to { SplatForgeClient().request("0".repeat(64), "backdrop") },
        "lens.mode.video" to { CaptureModes.require("video") },
        "lens.mode.depth_assist" to { CaptureModes.require("depth_assist") },
    )
    return probes.mapValues { (id, f) ->
        try { f(); mapOf("refused" to false, "feature" to id) } catch (e: StubException) { e.toMap() + ("refused" to true) }
    }
}

/** JVM stand-in for the phone's AccessibilityService: records what would be performed (used by the interop check). */
class RecordingSink(private val w: Int = 1080, private val h: Int = 2400) : InputSink {
    val log = ArrayList<Map<String, Any?>>()
    override fun screenSize() = w to h
    override fun gesture(strokes: List<Stroke>): Boolean { log.add(mapOf("gesture" to strokes.map { s -> mapOf("points" to s.points.map { listOf(it.first.toDouble(), it.second.toDouble()) }, "duration_ms" to s.durationMs) })); return true }
    override fun globalAction(key: String): Boolean { log.add(mapOf("global" to key)); return true }
    override fun typeText(text: String): Boolean { log.add(mapOf("text" to text)); return true }
    override fun focus(req: FocusRequest): Boolean { log.add(mapOf("focus" to req.mode, "diopters" to req.diopters(10f)?.toDouble())); return true }
}

/** Minimal IVF demuxer + H.264 access-unit splitter (same rules as forge.mirrorvideo). */
object Ivf {
    fun parse(d: ByteArray): List<ByteArray> {
        require(d.size >= 32 && String(d, 0, 4, Charsets.US_ASCII) == "DKIF") { "not an IVF stream" }
        val bb = java.nio.ByteBuffer.wrap(d).order(java.nio.ByteOrder.LITTLE_ENDIAN)
        var i = bb.getShort(6).toInt(); val out = ArrayList<ByteArray>()
        while (i + 12 <= d.size) { val n = bb.getInt(i); out.add(d.copyOfRange(i + 12, minOf(d.size, i + 12 + n))); i += 12 + n }
        return out
    }

    fun splitH264Aus(d: ByteArray): List<ByteArray> {
        val starts = ArrayList<Int>(); var i = 0
        while (i + 4 < d.size) {
            if (d[i] == 0.toByte() && d[i + 1] == 0.toByte() && d[i + 2] == 0.toByte() && d[i + 3] == 1.toByte() && (d[i + 4].toInt() and 0x1F) == 9) { starts.add(i); i += 4 } else i++
        }
        starts.add(d.size)
        return starts.zipWithNext().filter { it.second > it.first }.map { d.copyOfRange(it.first, it.second) }
    }
}
