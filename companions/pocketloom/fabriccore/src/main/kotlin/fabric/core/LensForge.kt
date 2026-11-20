package fabric.core

/** LensForge capture intelligence (C10) — SPEC §9 "Capture modes … offload path for reconstruction".
 *
 *  REAL: [CaptureModes] (read from the bundled PatternVault capture profiles = content/patternvault/capture_profiles.json),
 *  [Quality] (integer pixel math, bit-for-bit the Python `forge.lensforge.gray_metrics`; proven by shared vectors),
 *  [CaptureTelemetry] (typed contract). Decoding a JPEG to gray is the Android layer's job (BitmapFactory) — FabricCore stays
 *  Android-free, so [Quality] takes an integer gray array.
 *  STUB: [ArCoreSession] (ARCore is an Android-only SDK, not bundled). View overlap is NOT measured anywhere. */
object CaptureModes {
    const val MILESTONE = "C10"

    data class Mode(val id: String, val status: String, val routeHint: String?, val minViews: Int, val minLongEdgePx: Int,
                    val reasonKey: String?)

    private val profile: Map<String, Any?> by lazy {
        Json.obj(CaptureModes::class.java.getResourceAsStream("/fabric/capture_profiles.json")!!.bufferedReader().readText())
    }
    val all: Map<String, Mode> by lazy {
        profile["modes"].asMap().mapValues { (id, v) ->
            val m = v.asMap()
            Mode(id, m["status"] as String, m["route_hint"] as String?, (m["min_views"] ?: 0).asLong().toInt(),
                (m["min_long_edge_px"] ?: 0).asLong().toInt(), m["reason_key"] as String?)
        }
    }
    val minSharpness: Double get() = profile["thresholds"].asMap()["min_sharpness"].asDouble()
    val meanLuma: Pair<Double, Double> get() = profile["thresholds"].asMap()["mean_luma"].asList().let { it[0].asDouble() to it[1].asDouble() }
    val maxClipFraction: Double get() = profile["thresholds"].asMap()["max_clip_fraction"].asDouble()

    /** Mode lookup; a stub mode (video, ARCore-assisted) refuses. */
    fun require(id: String): Mode {
        val m = all[id] ?: throw IllegalArgumentException("unknown capture mode $id")
        if (m.status == "stub") refuse("lens.mode.$id", MILESTONE, m.reasonKey!!)
        return m
    }
}

object Quality {
    data class Metrics(val meanLuma: Double, val darkClip: Double, val brightClip: Double, val sharpness: Double)

    /** Integer luma exactly like Python: (299R+587G+114B)/1000 (floor). */
    fun luma(r: Int, g: Int, b: Int): Int = (299 * r + 587 * g + 114 * b) / 1000

    fun assessGray(gray: IntArray, w: Int, h: Int): Metrics {
        require(gray.size == w * h && w > 0 && h > 0) { "gray size mismatch" }
        val n = w * h
        var total = 0L; var dark = 0L; var bright = 0L
        for (v in gray) { total += v; if (v <= 5) dark++; if (v >= 250) bright++ }
        var sharp = 0.0
        if (w >= 3 && h >= 3) {
            var s = 0L; var ss = 0L; var m = 0L
            for (y in 1 until h - 1) for (x in 1 until w - 1) {
                val i = y * w + x
                val lap = (4 * gray[i] - gray[i - w] - gray[i + w] - gray[i - 1] - gray[i + 1]).toLong()
                s += lap; ss += lap * lap; m++
            }
            val mean = s.toDouble() / m
            sharp = ss.toDouble() / m - mean * mean
        }
        return Metrics(total.toDouble() / n, dark.toDouble() / n, bright.toDouble() / n, sharp)
    }

    /** Advisory verdict reasons (same labels as Python): blurry, too_dark, too_bright, clipped, low_resolution. */
    fun reasons(m: Metrics, w: Int, h: Int, mode: CaptureModes.Mode): List<String> = buildList {
        if (m.sharpness < CaptureModes.minSharpness) add("blurry")
        val (lo, hi) = CaptureModes.meanLuma
        if (m.meanLuma < lo) add("too_dark") else if (m.meanLuma > hi) add("too_bright")
        if (maxOf(m.darkClip, m.brightClip) > CaptureModes.maxClipFraction) add("clipped")
        if (maxOf(w, h) < mode.minLongEdgePx) add("low_resolution")
    }
}

/** Typed capture telemetry (SPEC §4/§9). Null = unknown — never defaulted. */
data class CaptureTelemetry(val device: String = "", val focalLengthMm: Double? = null, val focalLength35mm: Double? = null,
                            val sensorWidthMm: Double? = null, val exposureS: Double? = null, val iso: Double? = null,
                            val focusDistanceM: Double? = null, val orientation: Int? = null, val capturedAtMs: Long? = null,
                            val source: String = "") {
    init {
        fun chk(name: String, v: Double?, lo: Double, hi: Double) { if (v != null) require(v in lo..hi) { "$name: out of range" } }
        chk("focal_length_mm", focalLengthMm, 0.5, 2000.0); chk("focal_length_35mm", focalLength35mm, 5.0, 2000.0)
        chk("sensor_width_mm", sensorWidthMm, 0.5, 100.0); chk("exposure_s", exposureS, 1e-6, 3600.0)
        chk("iso", iso, 1.0, 10_000_000.0); chk("focus_distance_m", focusDistanceM, 0.0, 1e6)
        if (orientation != null) require(orientation in 1..8) { "orientation: 1..8" }
        if (capturedAtMs != null) require(capturedAtMs >= 0) { "captured_at_ms: out of range" }
    }

    fun toMap(): Map<String, Any?> = linkedMapOf<String, Any?>().also {
        if (device.isNotEmpty()) it["device"] = device
        focalLengthMm?.let { v -> it["focal_length_mm"] = v }; focalLength35mm?.let { v -> it["focal_length_35mm"] = v }
        sensorWidthMm?.let { v -> it["sensor_width_mm"] = v }; exposureS?.let { v -> it["exposure_s"] = v }
        iso?.let { v -> it["iso"] = v }; focusDistanceM?.let { v -> it["focus_distance_m"] = v }
        orientation?.let { v -> it["orientation"] = v.toLong() }; capturedAtMs?.let { v -> it["captured_at_ms"] = v }
        if (source.isNotEmpty()) it["source"] = source
    }
}

/** STUB: ARCore depth/pose-assisted capture (also the on-phone rung of metric depth). */
class ArCoreSession {
    fun start(): Nothing = refuse("lens.arcore_session", CaptureModes.MILESTONE, "stub.lens.arcore_session")
}
