package fabric.core

import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class TelemetryTest {
    @Test fun summaryAndRotation() {
        val f = File(tmpDir(), "t.jsonl")
        val t = Telemetry(f, maxBytes = 400)
        repeat(3) { t.record("job.local", mapOf("op" to "local.cave", "ms" to 2.0 * (it + 1))) }
        val s = t.summary()
        assertEquals(mapOf("n" to 3, "mean_ms" to 4.0, "max_ms" to 6.0), s["local_jobs"].asMap()["local.cave"])
        repeat(20) { t.record("x", mapOf("pad" to "0123456789")) }
        assertTrue(File(f.path + ".1").exists())
        assertTrue(f.length() <= 400 + 200)
    }
}
