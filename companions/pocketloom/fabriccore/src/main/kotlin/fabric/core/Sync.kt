package fabric.core

import java.util.Base64

/** Version vectors + the deterministic merge plan (C6). Kotlin twin of `forge.loomlink.plan_sync`;
 *  both are checked against the shared fixture `tests/fixtures/sync_plan_cases.json`. */
object VersionVector {
    fun of(e: Map<String, Any?>?): Map<String, Long> =
        (e?.get("vv") as? Map<*, *>)?.entries?.associate { it.key.toString() to (it.value as Number).toLong() } ?: emptyMap()

    /** "equal" | "a" (a dominates) | "b" | "concurrent". */
    fun compare(a: Map<String, Long>, b: Map<String, Long>): String {
        val keys = a.keys + b.keys
        val ge = keys.all { (a[it] ?: 0) >= (b[it] ?: 0) }
        val le = keys.all { (a[it] ?: 0) <= (b[it] ?: 0) }
        return when { ge && le -> "equal"; ge -> "a"; le -> "b"; else -> "concurrent" }
    }
}

object SyncPlan {
    /** server = desktop index, phone = this device's index. Same output as the Python planner. */
    fun plan(server: Map<String, Map<String, Any?>>, phone: Map<String, Map<String, Any?>>, phoneId: String): Map<String, Any?> {
        val pull = ArrayList<Map<String, Any?>>(); val push = ArrayList<String>(); val conflicts = ArrayList<Map<String, Any?>>()
        for (id in (server.keys + phone.keys).sorted()) {
            val s = server[id]; val p = phone[id]
            if (p == null) { pull.add(s!!); continue }
            if (s == null) { push.add(id); continue }
            when (VersionVector.compare(VersionVector.of(s), VersionVector.of(p))) {
                "a" -> pull.add(s)
                "b" -> push.add(id)
                "concurrent" -> if (s["sha256"] == p["sha256"]) {
                    val sv = VersionVector.of(s); val pv = VersionVector.of(p)
                    pull.add(s + ("vv" to (sv.keys + pv.keys).associateWith { maxOf(sv[it] ?: 0, pv[it] ?: 0) }))
                    conflicts.add(mapOf("id" to id, "resolution" to "merged_identical"))
                } else {
                    conflicts.add(mapOf("id" to id, "resolution" to "keep_both", "phone_copy" to "$id~$phoneId"))
                    push.add(id); pull.add(s)
                }
            }
        }
        return mapOf("pull" to pull, "push" to push, "conflicts" to conflicts)
    }
}

/** Runs one sync round against a paired desktop. Conflicts keep both copies: the desktop copy keeps
 *  the id, this device's copy becomes `<id>~<client id>` on both sides. A second round is a no-op. */
class SyncClient(private val link: LoomLinkClient, private val store: AssetStore, private val telemetry: Telemetry? = null) {
    fun sync(): Map<String, Any?> {
        if (!link.has("sync")) throw LinkException(403, "capability 'sync' not granted")
        val plan = link.postJson(null, "/sync/manifest", mapOf("index" to store.index()))
        val keepBoth = plan["conflicts"].asList().map { it.asMap() }.filter { it["resolution"] == "keep_both" }
            .associate { it["id"] as String to it["phone_copy"] as String }
        var pushed = 0; var pulled = 0
        for (id in plan["push"].asList().map { it as String }) {
            val e = store.get(id) ?: continue
            val data = store.read(e["sha256"] as String) ?: continue
            val body = linkedMapOf<String, Any?>("entry" to e, "data_b64" to Base64.getEncoder().encodeToString(data))
            val rid = keepBoth[id]
            if (rid != null) {
                body["conflict_of"] = id
                store.install(e + mapOf("id" to rid, "conflict_of" to id), null)
            }
            link.postJson(null, "/sync/push", body); pushed++
        }
        for (s in plan["pull"].asList().map { it.asMap() }) {
            val sha = s["sha256"] as String
            store.install(s, if (store.read(sha) != null) null else link.getBlob(sha)); pulled++
        }
        val r = mapOf("pushed" to pushed, "pulled" to pulled, "conflicts" to plan["conflicts"])
        telemetry?.record("sync", mapOf("pushed" to pushed, "pulled" to pulled, "conflicts" to keepBoth.size))
        return r
    }
}
