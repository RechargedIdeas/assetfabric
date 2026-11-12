package fabric.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

class LoomLinkTest {
    @Test fun hmacMatchesPython() {
        for (v in fixtures()["hmac"].asList().map { it.asMap() })
            assertEquals(v["mac"], LoomCrypto.mac(LoomCrypto.unhex(v["key_hex"] as String), *v["parts"].asList().map { it as String }.toTypedArray()))
    }

    @Test fun pairingUri() {
        val u = PairingUri.parse("loomlink://pair?u=http%3A%2F%2F100.64.0.2%3A8765&c=abcd-2345&n=desktop")
        assertEquals(PairingUri("http://100.64.0.2:8765", "ABCD2345", "desktop"), u)
        assertFailsWith<IllegalArgumentException> { PairingUri.parse("loomlink://pair?u=http%3A%2F%2Fx&c=ABC") }
        assertFailsWith<IllegalArgumentException> { PairingUri.parse("https://pair?u=x&c=ABCD2345") }
        assertFailsWith<IllegalArgumentException> { PairingUri.parse("loomlink://pair?u=file%3A%2F%2Fx&c=ABCD2345") }
        assertTrue(LoomCrypto.validCode("abcd 2345")); assertTrue(!LoomCrypto.validCode("ABCD0O11"))
    }

    /** In-memory desktop implementing just the pairing half of the protocol. */
    private class FakeDesktop(val code: String, val cheat: Boolean = false) : Http {
        var ns = ""; var nc = ""; val seen = ArrayList<Map<String, String>>()
        override fun request(method: String, url: String, headers: Map<String, String>, body: ByteArray?): Pair<Int, ByteArray> {
            seen.add(headers)
            val b = Json.obj(String(body ?: ByteArray(0)).ifEmpty { "{}" })
            val c = (if (cheat) "ZZZZZZZZ" else code).toByteArray()
            val out: Map<String, Any?> = when {
                url.endsWith("/pair/hello") -> { nc = b["nc"] as String; ns = LoomCrypto.nonce()
                    mapOf("ns" to ns, "server_id" to "desk", "proof" to LoomCrypto.mac(c, "srv", nc, ns, b["client_id"] as String)) }
                url.endsWith("/pair/confirm") -> {
                    if (b["proof"] != LoomCrypto.mac(c, "cli", nc, ns, b["client_id"] as String)) return 403 to "{\"error\":\"bad proof\"}".toByteArray()
                    mapOf("ok" to true, "granted" to (b["caps"].asList() - "mirror"), "server_id" to "desk")
                }
                else -> mapOf("ok" to true)
            }
            return 200 to Json.write(out).toByteArray()
        }
    }

    @Test fun pairDerivesKeyAndSignsWithMonotonicTs() {
        val fake = FakeDesktop("ABCD2345")
        val cl = LoomLinkClient("pl-1", http = fake, clock = { 1_000L })
        val s = cl.pair("http://h:1/", "abcd2345", listOf("offload", "sync", "mirror"))
        assertEquals(listOf("offload", "sync"), s.caps)
        assertEquals(LoomCrypto.mac("ABCD2345".toByteArray(), "key", fake.nc, fake.ns, "pl-1"), s.keyHex)
        assertTrue(fake.seen.none { "X-Loom-Sig" in it })            // pairing is unsigned, code never sent
        cl.postJson(null, "/offload", mapOf("a" to 1)); cl.postJson(null, "/offload", mapOf("a" to 2))
        val ts = fake.seen.takeLast(2).map { it["X-Loom-Ts"]!!.toLong() }
        assertTrue(ts[1] > ts[0])
        assertEquals(LoomCrypto.mac(LoomCrypto.unhex(s.keyHex), "POST", "/offload", ts[1].toString(), sha256Hex(Json.write(mapOf("a" to 2)).toByteArray())),
            fake.seen.last()["X-Loom-Sig"])
    }

    @Test fun rejectsDesktopThatCannotProveCode() {
        val cl = LoomLinkClient("pl-1", http = FakeDesktop("ABCD2345", cheat = true))
        assertFailsWith<LinkException> { cl.pair("http://h:1", "ABCD2345") }
        assertEquals(null, cl.session)
    }

    @Test fun capabilityGates() {
        val cl = LoomLinkClient("pl-1", LinkSession("http://h", "pl-1", "00", listOf("sync"), "d", 0), FakeDesktop("ABCD2345"))
        assertFailsWith<LinkException> { cl.offload(JobSpec("j", "hashchain", emptyMap()), null) }
    }
}
