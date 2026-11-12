package fabric.core

import kotlin.test.Test
import kotlin.test.assertEquals

class SyncPlanTest {
    @Test fun planMatchesPythonForEveryFixture() {
        for (c in fixtures()["sync_plan"].asList().map { it.asMap() }) {
            @Suppress("UNCHECKED_CAST")
            val p = SyncPlan.plan(c["server"] as Map<String, Map<String, Any?>>, c["phone"] as Map<String, Map<String, Any?>>, c["phone_id"] as String)
            assertEquals(Json.write(c["expected"]), Json.write(p), "case ${c["name"]}")
        }
    }

    @Test fun vectorCompare() {
        assertEquals("equal", VersionVector.compare(mapOf("a" to 1), mapOf("a" to 1, "b" to 0)))
        assertEquals("a", VersionVector.compare(mapOf("a" to 2), mapOf("a" to 1)))
        assertEquals("b", VersionVector.compare(emptyMap(), mapOf("a" to 1)))
        assertEquals("concurrent", VersionVector.compare(mapOf("a" to 1), mapOf("b" to 1)))
    }
}
