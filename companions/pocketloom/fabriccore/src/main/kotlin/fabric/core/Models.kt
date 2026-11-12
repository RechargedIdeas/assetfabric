package fabric.core

import java.io.File

/** On-device model cache with byte-budget LRU eviction (SPEC §8 "Model cache + eviction on device").
 *  Pinned models are never evicted. Index persisted as canonical JSON next to the blobs. */
class ModelCache(val dir: File, var budgetBytes: Long) {
    private val indexFile = File(dir, "models.json")
    private val entries = LinkedHashMap<String, MutableMap<String, Any?>>()
    private var tick = 0L

    init {
        dir.mkdirs()
        if (indexFile.exists()) Json.obj(indexFile.readText()).forEach { (k, v) ->
            entries[k] = LinkedHashMap(v.asMap()); tick = maxOf(tick, v.asMap()["used"].asLong())
        }
    }

    @Synchronized
    fun put(name: String, data: ByteArray, pinned: Boolean = false): List<String> {
        require(data.size <= budgetBytes || pinned) { "model $name (${data.size} B) exceeds cache budget $budgetBytes B" }
        File(dir, "$name.bin").writeBytes(data)
        entries[name] = linkedMapOf("name" to name, "size" to data.size.toLong(), "sha256" to sha256Hex(data),
            "pinned" to pinned, "used" to ++tick)
        val evicted = evict(); flush(); return evicted
    }

    @Synchronized
    fun get(name: String): ByteArray? {
        val e = entries[name] ?: return null
        val f = File(dir, "$name.bin")
        if (!f.exists()) { entries.remove(name); flush(); return null }
        e["used"] = ++tick; flush()
        return f.readBytes()
    }

    @Synchronized fun contains(name: String) = name in entries
    @Synchronized fun usedBytes(): Long = entries.values.sumOf { it["size"].asLong() }
    @Synchronized fun names(): List<String> = entries.keys.sorted()

    /** Evict least-recently-used unpinned models until the cache fits its budget. */
    @Synchronized
    fun evict(): List<String> {
        val out = ArrayList<String>()
        while (usedBytes() > budgetBytes) {
            val victim = entries.values.filter { it["pinned"] != true }.minByOrNull { it["used"].asLong() } ?: break
            val n = victim["name"] as String
            entries.remove(n); File(dir, "$n.bin").delete(); out.add(n)
        }
        return out
    }

    private fun flush() {
        val tmp = File(dir, "models.json.tmp"); tmp.writeText(Json.write(entries))
        if (!tmp.renameTo(indexFile)) { indexFile.delete(); tmp.renameTo(indexFile) }
    }

    fun stats(): Map<String, Any?> = mapOf("models" to entries.size, "bytes" to usedBytes(), "budget" to budgetBytes)
}

/** GroundWeave-style backend ladder for on-device generation (C2). Every kind ends in a CPU
 *  procedural rung that is always available; the small-ONNX rung is an honest **stub**: no ONNX
 *  runtime is bundled in this build (docs/INFERENCES.md C-4), so it reports unavailable. */
object GenBackends {
    data class Rung(val id: String, val device: String, val available: Boolean, val reason: String)

    const val ONNX_RUNTIME_BUNDLED = false

    fun ladder(kind: String, models: ModelCache?): List<Rung> {
        val model = "${kind}_small.onnx"
        val onnx = when {
            !ONNX_RUNTIME_BUNDLED -> Rung("onnx-small", "nnapi|cpu", false, "stub: onnxruntime not bundled in this build")
            models?.contains(model) != true -> Rung("onnx-small", "nnapi|cpu", false, "model $model not cached")
            else -> Rung("onnx-small", "nnapi|cpu", true, "")
        }
        val cpu = Rung(if (kind == "cave") "localforge-ca-cpu" else "localforge-sprite-cpu", "cpu", true, "")
        return listOf(onnx, cpu)
    }

    fun select(kind: String, models: ModelCache?): Map<String, Any?> {
        val l = ladder(kind, models)
        val pick = l.first { it.available }
        return mapOf("backend" to pick.id, "device" to pick.device,
            "skipped" to l.takeWhile { it !== pick }.map { mapOf("rung" to it.id, "reason" to it.reason) })
    }
}
