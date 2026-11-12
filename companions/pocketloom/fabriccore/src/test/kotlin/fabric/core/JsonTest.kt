package fabric.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

class JsonTest {
    @Test fun canonicalMatchesPython() {
        for (c in fixtures()["canonical"].asList().map { it.asMap() }) {
            assertEquals(c["text"], Json.write(c["value"]))
            assertEquals(c["text"], Json.write(Json.parse(c["text"] as String)))
        }
    }

    @Test fun roundTripTypes() {
        val v = mapOf("i" to 3L, "d" to 0.25, "s" to "a\u0001b", "l" to listOf(null, true, false), "m" to emptyMap<String, Any?>())
        assertEquals(v, Json.parse(Json.write(v)))
        assertEquals("{\"a\":1,\"b\":2}", Json.write(linkedMapOf("b" to 2, "a" to 1)))
        assertEquals("\"\\u0001\"", Json.write("\u0001"))
    }

    @Test fun rejectsGarbage() {
        assertFailsWith<Exception> { Json.parse("{\"a\":1") }
        assertFailsWith<Exception> { Json.parse("[1,2] x") }
        assertFailsWith<Exception> { Json.write(Double.NaN) }
    }
}
