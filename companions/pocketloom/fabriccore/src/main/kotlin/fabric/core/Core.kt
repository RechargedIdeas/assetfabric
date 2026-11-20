package fabric.core

import java.io.File

/** PocketLoom's whole offline runtime in one place (used by the Android app and the desktop CLI).
 *  Everything works with nothing connected; pairing only adds offload + sync. */
class PocketLoomCore(val home: File, nodeId: String? = null, modelBudgetBytes: Long = 64L * 1024 * 1024) {
    companion object { const val VERSION = "0.3.0-c10" }

    val nodeId: String = nodeId ?: loadOrCreateNodeId()
    val store = AssetStore(File(home, "store"), this.nodeId)
    val queue = OffloadQueue(File(home, "offload.jsonl"))
    val telemetry = Telemetry(File(home, "telemetry.jsonl"))
    val models = ModelCache(File(home, "models"), modelBudgetBytes)
    val executor = LocalExecutor(store) { Palettes.colours(it) }
    val dispatcher = Dispatcher(executor, queue, telemetry)
    private val sessionFile = File(home, "link/session.json")
    val link = LoomLinkClient(this.nodeId, LinkSession.load(sessionFile))

    private fun loadOrCreateNodeId(): String {
        val f = File(home, "node.json")
        if (f.exists()) return Json.obj(f.readText())["node_id"] as String
        val id = "pl-" + LoomCrypto.nonce().substring(0, 8)
        home.mkdirs(); f.writeText(Json.write(mapOf("node_id" to id)))
        return id
    }

    /** C2: on-device generation through the backend ladder (CPU procedural is always available). */
    fun generate(kind: String, seed: Long, palette: String? = null): Map<String, Any?> {
        require(kind == "cave" || kind == "sprite") { "unknown kind $kind" }
        val sel = GenBackends.select(kind, models)
        val payload = buildMap<String, Any?> { put("seed", seed); if (palette != null) put("palette", palette) }
        return dispatcher.submit(JobSpec("${kind}_$seed", "local.$kind", payload)) + ("selection" to sel)
    }

    fun capture(data: ByteArray, source: String, meta: Map<String, Any?> = emptyMap()) =
        Captures.ingest(store, queue, data, source, meta, telemetry)

    fun captureVideo(data: ByteArray, source: String, meta: Map<String, Any?> = emptyMap()) =
        VideoClips.ingest(store, queue, data, source, meta, telemetry)

    fun pair(uriOrUrl: String, code: String? = null, caps: List<String> = listOf("offload", "sync")): LinkSession {
        val s = if (uriOrUrl.startsWith("loomlink:")) link.pair(PairingUri.parse(uriOrUrl), caps)
                else link.pair(uriOrUrl, code ?: throw IllegalArgumentException("pairing code required"), caps)
        s.save(sessionFile)
        telemetry.record("paired", mapOf("server" to s.serverId, "caps" to s.caps))
        return s
    }

    fun unpair() { sessionFile.delete(); link.session = null; telemetry.record("unpaired") }

    /** C6: push queued jobs to the paired desktop; anything not sent stays queued (offline-safe). */
    fun drain(): Map<String, Any?> {
        if (link.session == null) return mapOf("sent" to 0, "pending" to queue.pending().size, "paired" to false)
        val n = queue.drain { job -> link.offload(job, store) }
        telemetry.record("offload.drain", mapOf("sent" to n, "pending" to queue.pending().size))
        return mapOf("sent" to n, "pending" to queue.pending().size, "paired" to true)
    }

    fun sync(): Map<String, Any?> = SyncClient(link, store, telemetry).sync()

    fun status(): Map<String, Any?> = mapOf(
        "version" to VERSION, "node_id" to nodeId, "store" to store.stats(), "models" to models.stats(),
        "offload_pending" to queue.pending().size, "offload_done" to queue.results().size,
        "paired" to (link.session?.let { mapOf("server" to it.serverId, "url" to it.url, "caps" to it.caps) }),
        "telemetry" to telemetry.summary(),
        "backends" to listOf("cave", "sprite").associateWith { k -> GenBackends.ladder(k, models).map { mapOf("rung" to it.id, "available" to it.available, "reason" to it.reason) } },
    )
}
