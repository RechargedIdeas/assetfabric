package fabric.core

import java.io.File

/** Local asset store (C1/C3): content-addressed blobs + an index with provenance and a
 *  per-asset version vector for sync (C6). Atomic index writes (tmp + rename). */
class AssetStore(val dir: File, val nodeId: String) {
    private val objects = File(dir, "objects")
    private val indexFile = File(dir, "index.json")
    private val entries = LinkedHashMap<String, MutableMap<String, Any?>>()

    init {
        objects.mkdirs()
        if (indexFile.exists()) {
            Json.obj(indexFile.readText()).forEach { (k, v) -> entries[k] = LinkedHashMap(v.asMap()) }
        }
    }

    fun blobFile(sha: String) = File(File(objects, sha.substring(0, 2)), sha)

    fun putBlob(data: ByteArray): String {
        val sha = sha256Hex(data)
        val f = blobFile(sha)
        if (!f.exists()) {
            f.parentFile.mkdirs()
            val tmp = File(f.parentFile, "$sha.tmp"); tmp.writeBytes(data); tmp.renameTo(f)
        }
        return sha
    }

    fun read(sha: String): ByteArray? = blobFile(sha).takeIf { it.exists() }?.readBytes()

    /** Insert or update an asset; bumps this node's counter in the version vector. */
    @Synchronized
    fun put(id: String, kind: String, data: ByteArray, provenance: Map<String, Any?> = emptyMap(),
            media: String = "image/png"): Map<String, Any?> {
        val sha = putBlob(data)
        val prev = entries[id]
        val vv = LinkedHashMap<String, Long>()
        (prev?.get("vv") as? Map<*, *>)?.forEach { (k, v) -> vv[k.toString()] = (v as Number).toLong() }
        vv[nodeId] = (vv[nodeId] ?: 0L) + 1
        val e = linkedMapOf<String, Any?>("id" to id, "kind" to kind, "sha256" to sha, "media" to media,
            "size" to data.size.toLong(), "vv" to vv, "provenance" to provenance, "updated_by" to nodeId)
        entries[id] = e
        flush()
        return e
    }

    /** Install an entry received from a peer (sync) without bumping counters. */
    @Synchronized
    fun install(entry: Map<String, Any?>, data: ByteArray?) {
        if (data != null) require(putBlob(data) == entry["sha256"]) { "blob digest mismatch for ${entry["id"]}" }
        entries[entry["id"] as String] = LinkedHashMap(entry)
        flush()
    }

    @Synchronized fun remove(id: String) { entries.remove(id); flush() }
    @Synchronized fun get(id: String): Map<String, Any?>? = entries[id]
    @Synchronized fun list(): List<Map<String, Any?>> = entries.values.map { it.toMap() }
    @Synchronized fun index(): Map<String, Map<String, Any?>> = entries.mapValues { it.value.toMap() }

    private fun flush() {
        dir.mkdirs()
        val tmp = File(dir, "index.json.tmp")
        tmp.writeText(Json.write(entries))
        if (!tmp.renameTo(indexFile)) { indexFile.delete(); tmp.renameTo(indexFile) }
    }

    fun stats(): Map<String, Any?> = mapOf("assets" to entries.size,
        "bytes" to objects.walkTopDown().filter { it.isFile }.sumOf { it.length() })
}
