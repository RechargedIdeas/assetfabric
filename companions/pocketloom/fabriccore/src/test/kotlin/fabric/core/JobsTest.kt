package fabric.core

import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class JobsTest {
    @Test fun hashchainMatchesPython() {
        for (v in fixtures()["hashchain"].asList().map { it.asMap() })
            assertEquals(v["digest"], hashchain(v["seed"], (v["rounds"] as Number).toInt()))
    }

    @Test fun dispatcherRunsLocallyOrQueues() {
        val d = tmpDir()
        val store = AssetStore(File(d, "s"), "n"); val q = OffloadQueue(File(d, "q.jsonl")); val t = Telemetry(File(d, "t.jsonl"))
        val disp = Dispatcher(LocalExecutor(store) { Palettes.colours(it) }, q, t)
        assertEquals("done", disp.submit(JobSpec("c", "local.cave", mapOf("seed" to 3L)))["status"])
        assertEquals("queued", disp.submit(JobSpec("r", "recon.capture", mapOf("x" to 1L)))["status"])
        assertEquals("queued", disp.submit(JobSpec("h", "hashchain", mapOf("seed" to "1")), preferOffload = true)["status"])
        assertEquals(listOf("r", "h"), q.pending().map { it.id })
        assertEquals("error", disp.submit(JobSpec("bad", "local.cave", mapOf("seed" to 1L, "palette" to "nope")))["status"])
        val sum = t.summary()
        assertEquals(1, sum["errors"])
    }

    @Test fun queueSurvivesRestartTornLineAndOffline() {
        val f = File(tmpDir(), "q.jsonl")
        val q = OffloadQueue(f)
        q.enqueue(JobSpec("a", "hashchain", mapOf("seed" to "1"))); q.enqueue(JobSpec("b", "hashchain", mapOf("seed" to "2")))
        f.appendText("{\"ev\":\"enqueue\",\"id\":\"c\",\"jo")          // torn write (power loss)
        val q2 = OffloadQueue(f)
        assertEquals(listOf("a", "b"), q2.pending().map { it.id })
        assertEquals(0, q2.drain { null })                                 // offline: nothing lost
        assertEquals(2, q2.pending().size)
        var calls = 0
        assertEquals(1, q2.drain { calls++; if (calls == 1) mapOf("ok" to true) else throw RuntimeException("link dropped") })
        val q3 = OffloadQueue(f)
        assertEquals(listOf("b"), q3.pending().map { it.id })
        assertTrue("a" in q3.results())
    }
}
