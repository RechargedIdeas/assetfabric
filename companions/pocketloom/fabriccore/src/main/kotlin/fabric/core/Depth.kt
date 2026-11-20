package fabric.core

import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.Base64
import kotlin.math.PI
import kotlin.math.tan

/** Metric depth (C11) — SPEC §5.2/§9. REAL: pinhole focal/distance maths (identical to Python `forge.depth`, shared vectors).
 *  REAL (0.7.5): [DepthEstimator] — dense DepthAnything V2 Small runs on the paired desktop (LoomLink offload op
 *  `depth.estimate`); the phone sends the capture (+ optional metric anchors) and gets the relative map back as uint16.
 *  ARCore depth: [ArDepth] (ArCore.kt) packs DEPTH16 frames for the desktop (op `depth.arcore`). */
object Depth {
    const val MILESTONE = "C11"
    const val FULL_FRAME_WIDTH_MM = 36.0

    fun focalPx(imageWidthPx: Int, focalLengthMm: Double? = null, sensorWidthMm: Double? = null,
                focalLength35mm: Double? = null, hfovDeg: Double? = null): Double {
        require(imageWidthPx > 0) { "image width must be positive" }
        if (focalLengthMm != null && focalLengthMm != 0.0 && sensorWidthMm != null && sensorWidthMm != 0.0)
            return focalLengthMm / sensorWidthMm * imageWidthPx
        if (focalLength35mm != null && focalLength35mm != 0.0) return focalLength35mm / FULL_FRAME_WIDTH_MM * imageWidthPx
        if (hfovDeg != null && hfovDeg > 0 && hfovDeg < 180) return (imageWidthPx / 2.0) / tan(hfovDeg * PI / 360.0)
        throw IllegalArgumentException("depth.no_intrinsics")
    }

    /** Pinhole z = f·S/s for an object of known size facing the camera. Returns (distance, lo, hi?) in metres. */
    fun distanceToObject(realSizeM: Double, sizePx: Double, focalLengthPx: Double, sizePxErr: Double = 1.0): Triple<Double, Double, Double?> {
        require(realSizeM > 0 && sizePx > 0 && focalLengthPx > 0) { "size, pixel extent and focal length must be positive" }
        val z = focalLengthPx * realSizeM / sizePx
        val lo = focalLengthPx * realSizeM / (sizePx + sizePxErr)
        val hi = if (sizePx > sizePxErr) focalLengthPx * realSizeM / maxOf(1e-9, sizePx - sizePxErr) else null
        return Triple(z, lo, hi)
    }
}

/** Contract for a dense relative-depth backend (image bytes → relative inverse-depth map, larger = nearer). */
interface RelativeDepth { fun estimate(image: ByteArray): FloatArray }

/** Metric anchor in image pixels (e.g. a LensForge known-size object or a tap with a measured distance). */
data class DepthAnchor(val x: Int, val y: Int, val depthM: Double)

data class DepthMap(val width: Int, val height: Int, val relative: FloatArray, val metric: Map<String, Any?>?) {
    /** Relative value at (x, y), larger = nearer. */
    fun at(x: Int, y: Int): Float = relative[y * width + x]
}

/** Dense relative depth via the paired desktop (DepthAnything V2 Small, onnxruntime CPU there). Needs `offload`. */
class DepthEstimator(private val link: LoomLinkClient, private val maxSide: Int = 512) : RelativeDepth {
    private var n = 0

    fun request(image: ByteArray, anchors: List<DepthAnchor> = emptyList()): DepthMap {
        if (!link.has("offload")) throw LinkException(403, "capability 'offload' not granted")
        val payload = mapOf("data_b64" to Base64.getEncoder().encodeToString(image), "max_side" to maxSide,
            "anchors" to anchors.map { mapOf("x" to it.x, "y" to it.y, "depth_m" to it.depthM) })
        val job = mapOf("id" to "depth-${link.clientId}-${System.currentTimeMillis()}-${n++}", "op" to "depth.estimate",
            "payload" to payload, "origin" to link.clientId)
        val r = link.postJson(null, "/offload", job)
        if (r["ok"] != true) throw IllegalStateException((r["error"] as? String) ?: "depth.estimate failed")
        @Suppress("UNCHECKED_CAST") val v = r["value"] as Map<String, Any?>
        return decode(v)
    }

    override fun estimate(image: ByteArray): FloatArray = request(image).relative

    companion object {
        fun decode(v: Map<String, Any?>): DepthMap {
            val w = (v["width"] as Number).toInt(); val h = (v["height"] as Number).toInt()
            val lo = (v["rel_min"] as Number).toDouble(); val hi = (v["rel_max"] as Number).toDouble()
            val bb = ByteBuffer.wrap(Base64.getDecoder().decode(v["rel_u16_b64"] as String)).order(ByteOrder.LITTLE_ENDIAN)
            require(bb.remaining() == w * h * 2) { "depth map size mismatch" }
            val out = FloatArray(w * h) { (lo + (bb.short.toInt() and 0xFFFF) / 65535.0 * (hi - lo)).toFloat() }
            @Suppress("UNCHECKED_CAST")
            return DepthMap(w, h, out, v["metric"] as Map<String, Any?>?)
        }
    }
}
