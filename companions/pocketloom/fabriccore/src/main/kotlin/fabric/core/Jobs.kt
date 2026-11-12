package fabric.core

import java.io.File
import java.security.MessageDigest

/** JobExecutor contract shared by PocketLoom, desktop forge and LoomCluster (C1/C6/C7).
 *  Job wire format = LoomCluster job JSON: {id, op, payload, requires?, origin?}. */
data class JobSpec(val id: String, val op: String, val payload: Map<String, Any?>,
                   val requires: Map<String, Any?> = emptyMap(), val origin: String? = null) {
    fun toMap(): Map<String, Any?> = buildMap {
        put("id", id); put("op", op); put("payload", payload)
        if (requires.isNotEmpty()) put("requires", requires)
        if (origin != null) put("origin", origin)
    }
    companion object {
        fun from(m: Map<String, Any?>) = JobSpec(m["id"] as String, m["op"] as String,
            (m["payload"] as? Map<*, *>)?.mapKeys { it.key.toString() } ?: emptyMap(),
            (m["requires"] as? Map<*, *>)?.mapKeys { it.key.toString() } ?: emptyMap(), m["origin"] as String?)
    }
}

interface JobExecutor {
    val ops: Set<String>
    val devices: List<String>
    fun canRun(job: JobSpec): Boolean =
        job.op in ops && ((job.requires["device"] as String?)?.let { it in devices } ?: true)
    fun execute(job: JobSpec): Map<String, Any?>
}

/** sha256 chain — identical to forge.loomcluster.op_hashchain (seed rendered with str()). */
fun hashchain(seed: Any?, rounds: Int): String {
    val md = MessageDigest.getInstance("SHA-256")
    var h = (seed?.toString() ?: "").toByteArray()
    repeat(rounds) { h = md.digest(h) }
    return h.joinToString("") { "%02x".format(it) }
}

/** CPU executor for everything PocketLoom can do offline. */
class LocalExecutor(private val store: AssetStore?, private val palettes: (String) -> List<String>) : JobExecutor {
    override val ops = setOf("hashchain", "local.cave", "local.sprite")
    override val devices = listOf("cpu")

    override fun execute(job: JobSpec): Map<String, Any?> {
        val p = job.payload
        return when (job.op) {
            "hashchain" -> mapOf("digest" to hashchain(p["seed"], (p["rounds"] as Number? ?: 20000L).toInt()))
            "local.cave", "local.sprite" -> {
                val seed = (p["seed"] as Number? ?: 1L).toLong()
                val pal = palettes(p["palette"] as String? ?: if (job.op == "local.cave") "cave_stone" else "hero_teal")
                val a = if (job.op == "local.cave") LocalForge.cave(seed, palette = pal) else LocalForge.sprite(seed, palette = pal)
                if (store != null && a.ok) {
                    store.put(p["id"] as String? ?: "${a.kind}_$seed", a.kind, a.png,
                        mapOf("seed" to seed, "backend" to a.meta["backend"], "gates" to a.gates.map { it.gate }))
                }
                mapOf("ok" to a.ok, "sha256" to a.sha256, "gates" to a.gates.associate { it.gate to it.ok }, "meta" to a.meta)
            }
            else -> throw IllegalArgumentException("unsupported op ${job.op}")
        }
    }
}

/** OffloadQueue (C6): durable FIFO of jobs waiting for a paired desktop/cluster
 *  (jobs whose op/device this phone cannot run, or that the user chose to offload).
 *  Journal = JSON lines; a torn last line is ignored on load. */
class OffloadQueue(private val file: File) {
    private val pending = LinkedHashMap<String, JobSpec>()
    private val done = LinkedHashMap<String, Map<String, Any?>>()

    init {
        if (file.exists()) file.readLines().forEach { line ->
            val rec = try { Json.obj(line) } catch (e: Exception) { return@forEach }
            val id = rec["id"] as String
            when (rec["ev"]) {
                "enqueue" -> pending[id] = JobSpec.from(rec["job"].asMap())
                "done" -> { pending.remove(id); done[id] = rec["result"].asMap() }
            }
        }
    }

    @Synchronized fun enqueue(job: JobSpec) { pending[job.id] = job; append(mapOf("ev" to "enqueue", "id" to job.id, "job" to job.toMap())) }
    @Synchronized fun complete(id: String, result: Map<String, Any?>) { pending.remove(id); done[id] = result; append(mapOf("ev" to "done", "id" to id, "result" to result)) }
    @Synchronized fun pending(): List<JobSpec> = pending.values.toList()
    @Synchronized fun results(): Map<String, Map<String, Any?>> = done.toMap()

    /** Push pending jobs through `submit` (e.g. LoomLink); returns how many were accepted. */
    fun drain(submit: (JobSpec) -> Map<String, Any?>?): Int {
        var n = 0
        for (job in pending()) {
            val r = try { submit(job) } catch (e: Exception) { null } ?: break   // offline: keep for later
            complete(job.id, r); n++
        }
        return n
    }

    private fun append(rec: Map<String, Any?>) { file.parentFile?.mkdirs(); file.appendText(Json.write(rec) + "\n") }
}
