package fabric.core

import java.io.File

/** On-device telemetry (C3 telemetry screen): append-only JSON lines, local only — nothing is
 *  sent anywhere unless the user pairs and syncs. Rotated at [maxBytes] (one `.1` generation). */
class Telemetry(private val file: File, private val maxBytes: Long = 1_000_000, private val clock: () -> Long = System::currentTimeMillis) {
    @Synchronized
    fun record(ev: String, fields: Map<String, Any?> = emptyMap()) {
        file.parentFile?.mkdirs()
        if (file.exists() && file.length() > maxBytes) {
            val old = File(file.path + ".1"); old.delete(); file.renameTo(old)
        }
        file.appendText(Json.write(fields + mapOf("ev" to ev, "ts" to clock())) + "\n")
    }

    @Synchronized
    fun events(): List<Map<String, Any?>> =
        if (!file.exists()) emptyList() else file.readLines().mapNotNull { runCatching { Json.obj(it) }.getOrNull() }

    /** Per-event counts, local job timings per op, error count. */
    fun summary(): Map<String, Any?> {
        val evs = events()
        val counts = evs.groupingBy { it["ev"] as String }.eachCount().toSortedMap()
        val timings = evs.filter { it["ev"] == "job.local" && it["ms"] is Number }.groupBy { it["op"] as String }
            .mapValues { (_, l) ->
                val ms = l.map { (it["ms"] as Number).toDouble() }
                mapOf("n" to ms.size, "mean_ms" to Math.round(ms.average() * 10) / 10.0, "max_ms" to Math.round(ms.max() * 10) / 10.0)
            }.toSortedMap()
        return mapOf("events" to evs.size, "counts" to counts, "local_jobs" to timings, "errors" to (counts["job.error"] ?: 0))
    }
}
