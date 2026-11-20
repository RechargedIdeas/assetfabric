package fabric.core

import java.util.Base64
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull
import kotlin.test.assertTrue

private fun vectors(): Map<String, Any?> =
    Json.obj(java.io.File(System.getProperty("fabric.fixtures"), "c9_c12_vectors.json").readText())

class C9C12Test {
    private fun gray(w: Int, h: Int, seed: Int) = IntArray(w * h) { i -> val x = i % w; val y = i / w; (x * 7 + y * 13 + (x * y) % 17 + seed * 31) % 256 }

    @Test fun qualityMatchesPythonVectors() {
        for (v in vectors()["lens_gray"].asList().map { it.asMap() }) {
            val w = v["w"].asLong().toInt(); val h = v["h"].asLong().toInt()
            val m = Quality.assessGray(gray(w, h, v["seed"].asLong().toInt()), w, h)
            assertEquals(v["mean_luma"].asDouble(), m.meanLuma, 1e-8)
            assertEquals(v["dark_clip"].asDouble(), m.darkClip, 1e-8)
            assertEquals(v["bright_clip"].asDouble(), m.brightClip, 1e-8)
            assertEquals(v["sharpness"].asDouble(), m.sharpness, 1e-5)
        }
        for (v in vectors()["luma"].asList().map { it.asList() })
            assertEquals(v[3].asLong().toInt(), Quality.luma(v[0].asLong().toInt(), v[1].asLong().toInt(), v[2].asLong().toInt()))
    }

    @Test fun depthMatchesPythonVectors() {
        for (v in vectors()["focal_px"].asList().map { it.asMap() }) {
            val f = Depth.focalPx(v["image_width_px"].asLong().toInt(), v["focal_length_mm"]?.asDouble(), v["sensor_width_mm"]?.asDouble(),
                v["focal_length_35mm"]?.asDouble(), v["hfov_deg"]?.asDouble())
            assertEquals(v["expected"].asDouble(), f, 1e-6)
        }
        for (v in vectors()["distance"].asList().map { it.asMap() }) {
            val (z, lo, hi) = Depth.distanceToObject(v["real_size_m"].asDouble(), v["size_px"].asDouble(), v["focal_px"].asDouble(), v["err_px"].asDouble())
            assertEquals(v["distance_m"].asDouble(), z, 1e-5); assertEquals(v["lo_m"].asDouble(), lo, 1e-5)
            if (v["hi_m"] == null) assertNull(hi) else assertEquals(v["hi_m"].asDouble(), hi!!, 1e-5)
        }
        assertFailsWith<IllegalArgumentException> { Depth.focalPx(1000) }              // no intrinsics → refuse, never default
        assertFailsWith<IllegalArgumentException> { Depth.distanceToObject(-1.0, 10.0, 100.0) }
    }

    @Test fun routeMatchesPython() {
        for (v in vectors()["route"].asList().map { it.asMap() }) {
            val r = ReconRoute.route(v["target"] as String)
            assertEquals(v["route"], r.route); assertEquals(v["alternatives"].asList(), r.alternatives)
        }
        assertFailsWith<IllegalArgumentException> { ReconRoute.route("nope") }
    }

    @Test fun frameValidationMatchesPython() {
        for (v in vectors()["frames"].asList().map { it.asMap() }) {
            val data = Base64.getDecoder().decode(v["data_b64"] as String)
            assertEquals(v["valid"] as Boolean, MirrorWeave.sniff(v["codec"] as String, data), v.toString())
        }
        val png = Base64.getDecoder().decode(vectors()["frames"].asList()[0].asMap()["data_b64"] as String)
        val env = FrameEnvelope("screen", 3, 1000, "screen", "png", 16, 12, png)
        val back = FrameEnvelope.fromWire(env.toWire())
        assertEquals(3L, back.seq); assertTrue(back.data.contentEquals(png))
        assertFailsWith<IllegalArgumentException> { FrameEnvelope("Bad Stream", 0, 0, "screen", "png", 0, 0, png) }
        assertFailsWith<IllegalArgumentException> { FrameEnvelope("s", 0, 0, "screen", "jpeg", 0, 0, png) }       // bytes are not a jpeg
        assertFailsWith<IllegalArgumentException> { FrameEnvelope("s", 0, 0, "telemetry", "png", 0, 0, png) }
        val e = assertFailsWith<StubException> { FrameEnvelope("s", 0, 0, "camera_video", "h264", 0, 0, png) }
        assertEquals("stub.mirror.video_codec", e.reasonKey)
    }

    @Test fun stillsSourceNumbersFramesInOrder() {
        val png = Base64.getDecoder().decode(vectors()["frames"].asList()[0].asMap()["data_b64"] as String)
        val seqs = StillsSource("cam", listOf(png, png, png), "camera_still", "png", 10).frames().map { it.seq }.toList()
        assertEquals(listOf(10L, 11L, 12L), seqs)
    }

    @Test fun mirrorClientNeedsGrantedCapability() {
        val c = MirrorClient(LoomLinkClient("t"))
        assertEquals(403, assertFailsWith<LinkException> { c.latest("screen") }.status)
        assertEquals(403, assertFailsWith<LinkException> { c.query("forge.status") }.status)
    }

    @Test fun captureModesComeFromTheBundledProfile() {
        assertEquals(24, CaptureModes.require("orbit").minViews)
        assertEquals("hero_prop", CaptureModes.require("orbit").routeHint)
        assertEquals("backdrop", CaptureModes.require("sweep").routeHint)
        assertEquals("stub.lens.video_capture", assertFailsWith<StubException> { CaptureModes.require("video") }.reasonKey)
        assertEquals("stub.lens.arcore_session", assertFailsWith<StubException> { CaptureModes.require("depth_assist") }.reasonKey)
        assertFailsWith<IllegalArgumentException> { CaptureModes.require("nope") }
        val m = Quality.assessGray(IntArray(64 * 48) { 128 }, 64, 48)                  // flat grey: blurry, but not clipped / dark
        assertEquals(listOf("blurry", "low_resolution"), Quality.reasons(m, 64, 48, CaptureModes.require("orbit")))
    }

    @Test fun telemetryContractRejectsOutOfRange() {
        assertEquals(6.9, CaptureTelemetry(device = "x", focalLengthMm = 6.9, orientation = 6).toMap()["focal_length_mm"])
        assertFailsWith<IllegalArgumentException> { CaptureTelemetry(iso = 0.0) }
        assertFailsWith<IllegalArgumentException> { CaptureTelemetry(orientation = 9) }
    }

    @Test fun everyStubRefuses() {
        val r = allStubs()
        assertTrue(r.size >= 9)
        for ((id, v) in r) {
            val m = v.asMap()
            assertEquals(true, m["refused"], id)
            assertTrue((m["message"] as String).startsWith("[STUB "), id)
        }
    }
}
