package fabric.core

import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull

class CaptureTest {
    /** Smallest structurally valid JPEG prefix: SOI, APP0, SOF0 (h=480, w=640). */
    private val jpeg = byteArrayOf(0xFF.toByte(), 0xD8.toByte(),
        0xFF.toByte(), 0xE0.toByte(), 0, 4, 0, 0,
        0xFF.toByte(), 0xC0.toByte(), 0, 11, 8, 0x01, 0xE0.toByte(), 0x02, 0x80.toByte(), 1, 1, 0x11, 0,
        0xFF.toByte(), 0xD9.toByte())

    @Test fun sniffing() {
        assertEquals("image/jpeg", Captures.mediaOf(jpeg))
        assertEquals(640 to 480, Captures.dimensions(jpeg))
        assertNull(Captures.mediaOf("hello".toByteArray()))
    }

    @Test fun ingestStoresAndQueuesOffload() {
        val d = tmpDir()
        val store = AssetStore(File(d, "s"), "pl-x"); val q = OffloadQueue(File(d, "q.jsonl"))
        val r = Captures.ingest(store, q, jpeg, "camera", mapOf("device" to "test"))
        val e = r["entry"].asMap()
        assertEquals("capture", e["kind"]); assertEquals("image/jpeg", e["media"])
        assertEquals(640L, e["provenance"].asMap()["width"])
        val job = q.pending().single()
        assertEquals(Captures.OP, job.op); assertEquals(e["sha256"], job.payload["blob_sha"])
        assertFailsWith<IllegalArgumentException> { Captures.ingest(store, q, "nope".toByteArray(), "import") }
    }
}
