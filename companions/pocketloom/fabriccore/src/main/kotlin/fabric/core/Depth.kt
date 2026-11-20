package fabric.core

import kotlin.math.PI
import kotlin.math.tan

/** Metric depth (C11) — SPEC §5.2/§9. REAL: pinhole focal/distance maths (identical to Python `forge.depth`, shared vectors).
 *  STUB: [DepthEstimator] (dense DepthAnything V2 / ARCore depth: no model or SDK bundled). */
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

/** STUB: DepthAnything V2 ONNX / ARCore depth — neither is bundled. */
class DepthEstimator : RelativeDepth {
    override fun estimate(image: ByteArray): FloatArray = refuse("depth.dense_estimate", Depth.MILESTONE, "stub.depth.model_missing")
}
