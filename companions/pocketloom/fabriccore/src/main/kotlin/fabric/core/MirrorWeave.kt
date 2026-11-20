package fabric.core

import java.util.Base64

/** MirrorWeave (C9) — SPEC §9: Android screen stream → desktop; desktop ⇄ Android remote control; camera stills/telemetry.
 *
 *  REAL: [FrameEnvelope] (same wire contract as `forge.mirrorweave.FrameEnvelope`), [StillsSource], [MirrorClient]
 *  (signed LoomLink `/mirror/frame`, `/mirror/latest`, `/mirror/control` — needs the `mirror` / `drive_studio` capabilities the
 *  desktop user granted at pairing; the desktop only runs allow-listed read-only queries).
 *  STUB (throws [StubException]): [ScreenCaptureSource] (MediaProjection), [VideoStreamSource] (H.264/WebRTC),
 *  [AndroidInputInjector] (desktop → phone input), [FocusController] (camera focus). */
object MirrorWeave {
    const val MILESTONE = "C9"
    const val MAX_FRAME_BYTES = 8 * 1024 * 1024
    val STREAM_KINDS = setOf("screen", "camera_still", "telemetry")
    val STILL_CODECS = setOf("png", "jpeg", "webp", "json")
    val STUB_CODECS = setOf("h264", "vp9", "av1")
    private val STREAM_RE = Regex("^[a-z0-9][a-z0-9_-]{0,31}$")

    fun validStream(s: String) = STREAM_RE.matches(s)

    fun sniff(codec: String, d: ByteArray): Boolean = when (codec) {
        "png" -> d.size >= 8 && d[0] == 0x89.toByte() && String(d, 1, 3, Charsets.US_ASCII) == "PNG" && d[4] == 0x0D.toByte()
        "jpeg" -> d.size >= 3 && d[0] == 0xFF.toByte() && d[1] == 0xD8.toByte() && d[2] == 0xFF.toByte()
        "webp" -> d.size >= 12 && String(d, 0, 4, Charsets.US_ASCII) == "RIFF" && String(d, 8, 4, Charsets.US_ASCII) == "WEBP"
        "json" -> runCatching { Json.parse(String(d, Charsets.UTF_8)) }.isSuccess
        else -> false
    }
}

class FrameEnvelope(val stream: String, val seq: Long, val tsMs: Long, val kind: String, val codec: String,
                    val width: Int, val height: Int, val data: ByteArray) {
    init {
        require(MirrorWeave.validStream(stream)) { "bad stream id" }
        if (kind == "camera_video" || codec in MirrorWeave.STUB_CODECS)
            refuse("mirror.video_stream", MirrorWeave.MILESTONE, "stub.mirror.video_codec")
        require(kind in MirrorWeave.STREAM_KINDS) { "unknown frame kind $kind" }
        require(codec in MirrorWeave.STILL_CODECS) { "unknown codec $codec" }
        require((kind == "telemetry") == (codec == "json")) { "telemetry frames must be json and json frames must be telemetry" }
        require(seq >= 0 && tsMs >= 0 && width >= 0 && height >= 0) { "negative field" }
        require(data.isNotEmpty() && data.size <= MirrorWeave.MAX_FRAME_BYTES) { "frame must be 1..${MirrorWeave.MAX_FRAME_BYTES} bytes" }
        require(MirrorWeave.sniff(codec, data)) { "payload is not valid $codec" }
    }

    fun toWire(): Map<String, Any?> = mapOf("stream" to stream, "seq" to seq, "ts_ms" to tsMs, "kind" to kind, "codec" to codec,
        "width" to width, "height" to height, "data_b64" to Base64.getEncoder().encodeToString(data))

    companion object {
        fun fromWire(w: Map<String, Any?>) = FrameEnvelope(w["stream"] as String, w["seq"].asLong(), w["ts_ms"].asLong(),
            w["kind"] as String, w["codec"] as String, (w["width"] ?: 0).asLong().toInt(), (w["height"] ?: 0).asLong().toInt(),
            Base64.getDecoder().decode(w["data_b64"] as String))
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

/** STUB: live screen capture needs MediaProjection (foreground service + user consent) — not built. */
class ScreenCaptureSource : MirrorSource {
    override fun frames(): Sequence<FrameEnvelope> = refuse("mirror.screen_capture", MirrorWeave.MILESTONE, "stub.mirror.screen_capture")
}

/** STUB: H.264/WebRTC video — not built. */
class VideoStreamSource : MirrorSource {
    override fun frames(): Sequence<FrameEnvelope> = refuse("mirror.video_stream", MirrorWeave.MILESTONE, "stub.mirror.video_codec")
}

/** STUB: desktop → phone remote input needs an AccessibilityService / adb bridge on the phone — not built. */
class AndroidInputInjector {
    fun send(action: String, args: Map<String, Any?> = emptyMap()): Nothing =
        refuse("mirror.android_input", MirrorWeave.MILESTONE, "stub.mirror.android_input")
}

/** STUB: camera focus control (CameraX/Camera2) — not built. */
class FocusController {
    fun setFocus(distanceM: Double): Nothing = refuse("mirror.camera_focus", MirrorWeave.MILESTONE, "stub.mirror.camera_focus")
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
}
