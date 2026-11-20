package fabric.core

import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.Base64
import kotlin.math.acos
import kotlin.math.sqrt

/** ARCore capture — platform-free half (C10 `lens.arcore_session`, C11 `depth.arcore`). SPEC §9 "ARCore + DepthAnything V2".
 *  The ARCore SDK side lives in the app (`ArCoreCapture`, compiled, never run on a phone → `real_unverified_on_device`); it
 *  fills [ArDepthFrame]s. Maths here is bit-for-bit the Python `forge.arcore` (shared vectors `tests/fixtures/arcore_vectors.json`). */

/** One ARCore frame. [depthMm] = DEPTH16 millimetres (0 = no depth, `Frame.acquireDepthImage16Bits`), [confidence] 0..255
 *  (`acquireRawDepthConfidenceImage`, optional), [pose] = camera-to-world [tx,ty,tz,qx,qy,qz,qw], intrinsics of the camera image. */
class ArDepthFrame(val width: Int, val height: Int, val depthMm: IntArray?, val confidence: IntArray?, val pose: DoubleArray,
                   val fx: Double, val fy: Double, val cx: Double, val cy: Double, val imageW: Int, val imageH: Int,
                   val timestampNs: Long, val image: ByteArray? = null, val imageMedia: String = "image/jpeg") {
    init {
        require(pose.size == 7) { "pose must be [tx,ty,tz,qx,qy,qz,qw]" }
        if (depthMm != null) require(depthMm.size == width * height) { "depth size mismatch" }
        if (confidence != null) require(confidence.size == width * height) { "confidence size mismatch" }
    }
}

object ArDepth {
    const val MIN_CONFIDENCE = 128
    const val ANCHORS = 12

    /** Deterministic test frame shared with Python (`forge.arcore.synthetic_frame`). */
    fun synthetic(w: Int, h: Int): Pair<IntArray, IntArray> {
        val d = IntArray(w * h) { i -> val x = i % w; val y = i / w; if ((x + y) % 11 == 0) 0 else 500 + (x * 37 + y * 91) % 4000 }
        val c = IntArray(w * h) { i -> val x = i % w; val y = i / w; (x * 13 + y * 7) % 256 }
        return d to c
    }

    data class Stats(val validFraction: Double, val minM: Double?, val medianM: Double?, val maxM: Double?)

    fun stats(depthMm: IntArray): Stats {
        val v = depthMm.filter { it > 0 }.sorted()
        if (v.isEmpty()) return Stats(0.0, null, null, null)
        return Stats(Math.round(v.size.toDouble() / depthMm.size * 1e6) / 1e6, v.first() / 1000.0, v[(v.size - 1) / 2] / 1000.0, v.last() / 1000.0)
    }

    /** Grid of ceil(sqrt(n))² cell centres; a centre is an anchor if depth > 0 and confidence ≥ [minConf]; mapped to image px. */
    fun anchors(w: Int, h: Int, depthMm: IntArray, confidence: IntArray?, imageW: Int, imageH: Int,
                n: Int = ANCHORS, minConf: Int = MIN_CONFIDENCE): List<DepthAnchor> {
        var g = 1
        while (g * g < n) g++
        val out = ArrayList<DepthAnchor>()
        for (gy in 0 until g) for (gx in 0 until g) {
            val px = (2 * gx + 1) * w / (2 * g); val py = (2 * gy + 1) * h / (2 * g)
            val mm = depthMm[py * w + px]
            if (mm == 0 || (confidence != null && confidence[py * w + px] < minConf)) continue
            out.add(DepthAnchor((2 * px + 1) * imageW / (2 * w), (2 * py + 1) * imageH / (2 * h), mm / 1000.0))
            if (out.size == n) return out
        }
        return out
    }

    /** LoomLink payload for op `depth.arcore` (same layout the desktop decodes). */
    fun payload(f: ArDepthFrame): Map<String, Any?> {
        val m = LinkedHashMap<String, Any?>()
        m["width"] = f.width; m["height"] = f.height
        if (f.depthMm != null) {
            val bb = ByteBuffer.allocate(f.width * f.height * 2).order(ByteOrder.LITTLE_ENDIAN)
            f.depthMm.forEach { bb.putShort(it.coerceIn(0, 65535).toShort()) }
            m["depth_u16_b64"] = Base64.getEncoder().encodeToString(bb.array())
        }
        if (f.confidence != null) m["conf_u8_b64"] = Base64.getEncoder().encodeToString(ByteArray(f.confidence.size) { f.confidence[it].coerceIn(0, 255).toByte() })
        m["pose"] = f.pose.toList()
        m["intrinsics"] = mapOf("fx" to f.fx, "fy" to f.fy, "cx" to f.cx, "cy" to f.cy, "image_w" to f.imageW, "image_h" to f.imageH)
        m["timestamp_ns"] = f.timestampNs
        if (f.image != null) { m["image_b64"] = Base64.getEncoder().encodeToString(f.image); m["media"] = f.imageMedia }
        return m
    }
}

object ArPoses {
    data class Coverage(val views: Int, val pathM: Double, val maxBaselineM: Double, val angularSpreadDeg: Double, val maxStepDeg: Double)

    /** Camera look direction (-Z) rotated by the pose quaternion — same formula as `forge.arcore._forward`. */
    fun forward(p: DoubleArray): DoubleArray {
        var x = p[3]; var y = p[4]; var z = p[5]; var w = p[6]
        val n = sqrt(x * x + y * y + z * z + w * w).let { if (it == 0.0) 1.0 else it }
        x /= n; y /= n; z /= n; w /= n
        return doubleArrayOf(-(2 * (x * z + w * y)), -(2 * (y * z - w * x)), -(1 - 2 * (x * x + y * y)))
    }

    private fun dist(a: DoubleArray, b: DoubleArray) = sqrt((a[0] - b[0]) * (a[0] - b[0]) + (a[1] - b[1]) * (a[1] - b[1]) + (a[2] - b[2]) * (a[2] - b[2]))
    private fun ang(a: DoubleArray, b: DoubleArray) = Math.toDegrees(acos((a[0] * b[0] + a[1] * b[1] + a[2] * b[2]).coerceIn(-1.0, 1.0)))

    fun coverage(poses: List<DoubleArray>): Coverage {
        require(poses.isNotEmpty()) { "no poses" }
        poses.forEach { require(it.size == 7 && it.all(Double::isFinite)) { "pose must be 7 finite numbers" } }
        val c = poses.map { doubleArrayOf(it[0], it[1], it[2]) }
        val f = poses.map(::forward)
        var path = 0.0; for (i in 0 until c.size - 1) path += dist(c[i], c[i + 1])
        var base = 0.0; var spread = 0.0; var step = 0.0
        for (i in c.indices) for (j in i + 1 until c.size) { base = maxOf(base, dist(c[i], c[j])); spread = maxOf(spread, ang(f[i], f[j])) }
        for (i in 0 until f.size - 1) step = maxOf(step, ang(f[i], f[i + 1]))
        return Coverage(poses.size, path, base, spread, step)
    }
}

/** Platform-free ARCore capture session: collects frames from `ArCoreCapture`, reports pose coverage against the
 *  `depth_assist` capture mode, and sends frames to the paired desktop (LoomLink op `depth.arcore`, needs `offload`). */
class ArCoreSession(private val minSpreadDeg: Double = 30.0, private val minViews: Int = 12) {
    private val frames = ArrayList<ArDepthFrame>()
    val size: Int get() = frames.size

    fun add(f: ArDepthFrame) { frames.add(f) }

    fun coverage(): ArPoses.Coverage = ArPoses.coverage(frames.map { it.pose })

    /** True once the set has enough views and angular spread for the `depth_assist` mode. */
    fun sufficient(): Boolean = frames.size >= minViews && coverage().angularSpreadDeg >= minSpreadDeg

    fun upload(link: LoomLinkClient, f: ArDepthFrame, id: String): Map<String, Any?> {
        if (!link.has("offload")) throw LinkException(403, "capability 'offload' not granted")
        val r = link.postJson(null, "/offload", mapOf("id" to id, "op" to "depth.arcore", "payload" to ArDepth.payload(f), "origin" to link.clientId))
        if (r["ok"] != true) throw IllegalStateException((r["error"] as? String) ?: "depth.arcore failed")
        @Suppress("UNCHECKED_CAST") return r["value"] as Map<String, Any?>
    }
}
