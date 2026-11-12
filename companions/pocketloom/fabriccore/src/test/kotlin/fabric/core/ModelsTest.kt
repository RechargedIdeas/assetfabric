package fabric.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull

class ModelsTest {
    @Test fun lruEvictionRespectsPins() {
        val d = tmpDir()
        val c = ModelCache(d, 100)
        c.put("pin", ByteArray(40), pinned = true)
        c.put("a", ByteArray(30)); c.put("b", ByteArray(30))
        c.get("a")                                             // a is now more recent than b
        assertEquals(listOf("b"), c.put("c", ByteArray(30)))
        assertEquals(listOf("a", "c", "pin"), c.names())
        assertNull(c.get("b"))
        val again = ModelCache(d, 100)                         // persisted
        assertEquals(listOf("a", "c", "pin"), again.names())
        again.budgetBytes = 40; again.evict()
        assertEquals(listOf("pin"), again.names())
    }

    @Test fun ladderFallsBackToCpu() {
        val sel = GenBackends.select("cave", ModelCache(tmpDir(), 10))
        assertEquals("localforge-ca-cpu", sel["backend"])
        assertEquals("cpu", sel["device"])
        assertFalse(GenBackends.ladder("sprite", null).first().available)
        assertEquals("onnx-small", (sel["skipped"].asList().single().asMap())["rung"])
    }
}
