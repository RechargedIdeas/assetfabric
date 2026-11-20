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
        assertFailsWith<IllegalArgumentException> { FrameEnvelope("s", 0, 0, "camera_video", "h264", 0, 0, png) }  // not h264 bytes
        assertFailsWith<IllegalArgumentException> { FrameEnvelope("s", 0, 0, "screen", "h264", 0, 0, png) }        // still kind + video codec
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
        assertTrue(r.size >= 4)
        for ((id, v) in r) {
            val m = v.asMap()
            assertEquals(true, m["refused"], id)
            assertTrue((m["message"] as String).startsWith("[STUB "), id)
        }
    }

    // ------------------------------------------------------------------ C9 real paths (2026-11-20)
    @Test fun videoKeyframesMatchPython() {
        for ((codec, rows) in vectors()["video"].asMap()) for (v in rows.asList().map { it.asMap() }) {
            val p = Base64.getDecoder().decode(v["data_b64"] as String)
            assertEquals(v["keyframe"], Video.isKeyframe(codec, p), codec)
            assertEquals(v["sniff"], Video.sniff(codec, p), codec)
            val env = FrameEnvelope("v", 0, 0, "screen_video", codec, 32, 32, p, v["keyframe"] as Boolean)
            assertTrue(FrameEnvelope.fromWire(env.toWire()).data.contentEquals(p))
            assertFailsWith<IllegalArgumentException> { FrameEnvelope("v", 0, 0, "screen_video", codec, 32, 32, p, !(v["keyframe"] as Boolean)) }
        }
    }

    @Test fun videoSourcePrependsCodecConfigToKeyframes() {
        val aus = vectors()["video"].asMap()["h264"].asList().map { Base64.getDecoder().decode(it.asMap()["data_b64"] as String) }
        // Split the first AU into SPS/PPS "config" + the IDR remainder, as MediaCodec delivers them.
        val first = aus[0]; val idrAt = (0 until first.size - 3).first { first[it] == 0.toByte() && first[it + 1] == 0.toByte() &&
            first[it + 2] == 1.toByte() && (first[it + 3].toInt() and 0x1F) == 5 }
        val cfg = first.copyOfRange(0, idrAt); val idr = first.copyOfRange(idrAt, first.size)
        val pk = sequenceOf(VideoPacket(cfg, config = true), VideoPacket(idr, key = true)) + aus.drop(1).asSequence().map { VideoPacket(it) }
        val out = VideoStreamSource("cam", pk, "h264", 32, 32, "camera_video", clock = { 7 }).frames().toList()
        assertEquals(aus.size, out.size)
        assertTrue(out[0].keyframe && Video.h264NalTypes(out[0].data).contains(7))
        assertEquals(listOf(0L, 1L, 2L), out.take(3).map { it.seq })
        assertEquals(aus.map { Video.isKeyframe("h264", it) }, out.map { it.keyframe })
    }

    @Test fun inputEventsVerifyAgainstPythonMacs() {
        val inp = vectors()["input"].asMap()
        val evs = inp["events"].asList().map { InputEvent.verified(inp["key_hex"] as String, inp["client"] as String, it.asMap()).second }
        assertEquals(listOf("tap", "swipe", "key", "text", "focus"), evs.map { it.type })
        assertEquals("héllo \"q\"", evs[3].text)
        val tampered = inp["events"].asList()[0].asMap() + ("event_json" to "{\"type\":\"tap\",\"x\":0.9,\"y\":0.25}")
        assertFailsWith<SecurityException> { InputEvent.verified(inp["key_hex"] as String, inp["client"] as String, tampered) }
        assertFailsWith<SecurityException> { InputEvent.verified(inp["key_hex"] as String, "other-phone", inp["events"].asList()[0].asMap()) }
        assertFailsWith<IllegalArgumentException> { InputEvent.parse(mapOf("type" to "tap", "x" to 1.5, "y" to 0.0)) }
        assertFailsWith<IllegalArgumentException> { InputEvent.parse(mapOf("type" to "key", "key" to "power")) }
        assertFailsWith<IllegalArgumentException> { InputEvent.parse(mapOf("type" to "shell", "cmd" to "rm")) }
    }

    @Test fun gesturesAndFocusMaths() {
        val s = GestureMapper.strokes(InputEvent.parse(mapOf("type" to "swipe", "x" to 0.0, "y" to 1.0, "x2" to 1.0, "y2" to 0.0, "duration_ms" to 250)), 1080, 2400)
        assertEquals(listOf(0f to 2399f, 1079f to 0f), s[0].points); assertEquals(250L, s[0].durationMs)
        assertEquals(GestureMapper.TAP_MS, GestureMapper.strokes(InputEvent.parse(mapOf("type" to "tap", "x" to 0.5, "y" to 0.5)), 100, 100)[0].durationMs)
        val f = FocusRequest("manual", 0.25, 0.5, 0.5)
        assertEquals(4f, f.diopters(10f)); assertEquals(2f, FocusRequest("manual", 0.25).diopters(2f))   // clamped to the lens
        assertEquals(0.001f, FocusRequest("manual", 1000.0).diopters(10f)!!, 1e-6f)
        val r = f.meteringRect(4000, 3000)!!
        assertEquals(listOf(1799, 1349, 2199, 1649), r.toList())
        assertNull(FocusRequest("auto").meteringRect(4000, 3000))
        assertEquals(listOf(0, 0), FocusRequest("auto", null, 0.0, 0.0).meteringRect(4000, 3000)!!.take(2))
        assertFailsWith<IllegalArgumentException> { FocusRequest("manual") }
    }

    @Test fun screenCaptureSourcePacesAndSkipsEmptyGrabs() {
        val png = Base64.getDecoder().decode(vectors()["frames"].asList()[0].asMap()["data_b64"] as String)
        var t = 0L; var calls = 0; val slept = ArrayList<Long>()
        val src = ScreenCaptureSource("screen", { calls++; if (calls % 2 == 0) null else Still(png, "png", 16, 12) }, fps = 10, maxFrames = 3,
            clock = { t }, sleep = { slept.add(it); t += it })
        val fr = src.frames().toList()
        assertEquals(listOf(0L, 1L, 2L), fr.map { it.seq }); assertEquals(5, calls)
        assertTrue(slept.all { it == 100L })
        assertFailsWith<IllegalArgumentException> { ScreenCaptureSource("s", { null }, fps = 0) }
    }

    @Test fun injectorRunsVerifiedEventsThroughTheSink() {
        val inp = vectors()["input"].asMap()
        val http = Http { _, _, _, _ -> 200 to Json.write(mapOf("events" to inp["events"])).toByteArray() }
        val link = LoomLinkClient(inp["client"] as String, LinkSession("http://x", inp["client"] as String, inp["key_hex"] as String,
            listOf("mirror"), "desk", 0), http)
        val sink = RecordingSink(1000, 2000)
        val inj = AndroidInputInjector(link, sink)
        val r = inj.pollOnce()
        assertEquals(5, r.size); assertTrue(r.all { it["ok"] == true }); assertEquals(4L, inj.after)
        assertEquals(mapOf("global" to "back"), sink.log[2]); assertEquals("manual", sink.log[4]["focus"])
    }

    @Test fun depthMapDecodesUint16AndRefusesWithoutOffload() {
        // 2x2 map: values 0, 65535, 32768, 1 over [0.5, 2.5]
        val bb = java.nio.ByteBuffer.allocate(8).order(java.nio.ByteOrder.LITTLE_ENDIAN)
        listOf(0, 65535, 32768, 1).forEach { bb.putShort(it.toShort()) }
        val m = DepthEstimator.decode(mapOf("width" to 2L, "height" to 2L, "rel_min" to 0.5, "rel_max" to 2.5,
            "rel_u16_b64" to java.util.Base64.getEncoder().encodeToString(bb.array()), "metric" to mapOf("median_m" to 3.0)))
        assertEquals(0.5f, m.at(0, 0)); assertEquals(2.5f, m.at(1, 0)); assertEquals(1.5f, m.at(0, 1), 1e-4f)
        assertEquals(3.0, m.metric!!["median_m"])
        assertFailsWith<IllegalArgumentException> {
            DepthEstimator.decode(mapOf("width" to 3L, "height" to 2L, "rel_min" to 0.0, "rel_max" to 1.0,
                "rel_u16_b64" to java.util.Base64.getEncoder().encodeToString(bb.array())))
        }
        assertFailsWith<LinkException> { DepthEstimator(LoomLinkClient("unpaired")).request(ByteArray(4)) }
    }
}
