package fabric.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNotNull
import kotlin.test.assertNull

class StoreTest {
    @Test fun putBumpsVersionVectorAndPersists() {
        val d = tmpDir()
        val s = AssetStore(d, "pl-a")
        s.put("x", "sprite", byteArrayOf(1, 2, 3))
        val e = s.put("x", "sprite", byteArrayOf(4, 5))
        assertEquals(mapOf("pl-a" to 2L), e["vv"])
        val again = AssetStore(d, "pl-a")
        assertEquals(e["sha256"], again.get("x")!!["sha256"])
        assertEquals(2L, (again.get("x")!!["vv"] as Map<*, *>)["pl-a"])
        assertNotNull(again.read(e["sha256"] as String))
    }

    @Test fun contentAddressedDedupe() {
        val s = AssetStore(tmpDir(), "n")
        val a = s.put("a", "k", byteArrayOf(9)); val b = s.put("b", "k", byteArrayOf(9))
        assertEquals(a["sha256"], b["sha256"])
        assertEquals(1, s.stats()["assets"].let { (it as Int) - 1 })
    }

    @Test fun installChecksDigest() {
        val s = AssetStore(tmpDir(), "n")
        val e = mapOf("id" to "q", "sha256" to sha256Hex(byteArrayOf(1)), "vv" to mapOf("m" to 1L))
        assertFailsWith<IllegalArgumentException> { s.install(e, byteArrayOf(2)) }
        s.install(e, byteArrayOf(1))
        assertEquals(mapOf("m" to 1L), s.get("q")!!["vv"])
        s.remove("q"); assertNull(s.get("q"))
    }
}
