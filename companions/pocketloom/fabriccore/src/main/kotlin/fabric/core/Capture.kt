package fabric.core

/** Local capture (C4): stills taken on the phone (camera intent) or imported (document picker)
 *  are validated, stored content-addressed with capture telemetry, and a `recon.capture` job is
 *  queued for offload — reconstruction itself (RealityLoom/SplatForge, C10–C12) is NOT done here
 *  and is not implemented yet; the desktop side currently only stores the capture (labelled stub). */
object Captures {
    const val OP = "recon.capture"

    fun mediaOf(b: ByteArray): String? = when {
        b.size >= 3 && b[0] == 0xFF.toByte() && b[1] == 0xD8.toByte() && b[2] == 0xFF.toByte() -> "image/jpeg"
        b.size >= 8 && b[0] == 0x89.toByte() && b[1] == 'P'.code.toByte() && b[2] == 'N'.code.toByte() && b[3] == 'G'.code.toByte() -> "image/png"
        b.size >= 12 && String(b, 0, 4, Charsets.US_ASCII) == "RIFF" && String(b, 8, 4, Charsets.US_ASCII) == "WEBP" -> "image/webp"
        else -> null
    }

    /** Pixel size from the PNG IHDR or the first JPEG SOFn marker; null when unknown. */
    fun dimensions(b: ByteArray): Pair<Int, Int>? {
        fun u16(i: Int) = ((b[i].toInt() and 0xff) shl 8) or (b[i + 1].toInt() and 0xff)
        fun u32(i: Int) = (u16(i) shl 16) or u16(i + 2)
        return when (mediaOf(b)) {
            "image/png" -> if (b.size >= 24) u32(16) to u32(20) else null
            "image/jpeg" -> {
                var i = 2
                while (i + 9 < b.size) {
                    if (b[i] != 0xFF.toByte()) return null
                    val m = b[i + 1].toInt() and 0xff
                    if (m == 0xD8 || m == 0x01 || m in 0xD0..0xD7) { i += 2; continue }
                    val len = u16(i + 2)
                    if (m in 0xC0..0xCF && m != 0xC4 && m != 0xC8 && m != 0xCC) return u16(i + 7) to u16(i + 5)
                    i += 2 + len
                }
                null
            }
            else -> null
        }
    }

    /** Store a capture and queue its reconstruction offload. Returns the store entry + job id.
     *  `meta` carries capture telemetry from the device (source, timestamps, orientation, model…). */
    fun ingest(store: AssetStore, queue: OffloadQueue, data: ByteArray, source: String,
               meta: Map<String, Any?> = emptyMap(), telemetry: Telemetry? = null): Map<String, Any?> {
        val media = mediaOf(data) ?: throw IllegalArgumentException("not an image (jpeg/png/webp expected)")
        require(data.size <= 64 * 1024 * 1024) { "capture larger than 64 MiB" }
        val sha = sha256Hex(data)
        val id = "cap_" + sha.substring(0, 12)
        val dim = dimensions(data)
        val prov = linkedMapOf<String, Any?>("source" to source, "bytes" to data.size.toLong(), "media" to media,
            "reconstruction" to "pending-offload (C10–C12 not implemented)")
        if (dim != null) { prov["width"] = dim.first.toLong(); prov["height"] = dim.second.toLong() }
        prov.putAll(meta)
        val entry = store.put(id, "capture", data, prov, media)
        val job = JobSpec("recon_" + sha.substring(0, 12), OP,
            mapOf("asset_id" to id, "blob_sha" to sha, "media" to media), mapOf("device" to "desktop"))
        queue.enqueue(job)
        telemetry?.record("capture", mapOf("id" to id, "bytes" to data.size, "media" to media, "source" to source))
        return mapOf("entry" to entry, "job" to job.id)
    }
}
