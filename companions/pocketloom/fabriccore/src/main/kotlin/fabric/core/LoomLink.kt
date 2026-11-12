package fabric.core

import java.io.File
import java.net.HttpURLConnection
import java.net.URI
import java.net.URL
import java.net.URLDecoder
import java.security.SecureRandom
import java.util.Base64
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/** LoomLink client (C5 pairing + the signed transport used by C6 offload/sync).
 *  Wire-compatible with `forge/loomlink.py`. The pairing code never crosses the wire: both sides
 *  prove knowledge of it with HMAC-SHA256 over fresh nonces and derive a per-device session key.
 *  Transport is plain HTTP to a LAN or Tailscale address (Tailscale encrypts the path); requests
 *  are integrity-protected by the request MAC, not encrypted — see docs/INFERENCES.md C-7. */
object LoomCrypto {
    const val CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    const val CODE_LEN = 8
    private val rnd = SecureRandom()

    fun mac(key: ByteArray, vararg parts: String): String {
        val m = Mac.getInstance("HmacSHA256"); m.init(SecretKeySpec(key, "HmacSHA256"))
        return m.doFinal(parts.joinToString("|").toByteArray()).joinToString("") { "%02x".format(it) }
    }
    fun hex(b: ByteArray) = b.joinToString("") { "%02x".format(it) }
    fun unhex(s: String) = ByteArray(s.length / 2) { s.substring(2 * it, 2 * it + 2).toInt(16).toByte() }
    fun nonce(): String = ByteArray(16).also(rnd::nextBytes).let(::hex)
    fun normaliseCode(c: String) = c.trim().uppercase().replace("-", "").replace(" ", "")
    fun validCode(c: String) = normaliseCode(c).let { n -> n.length == CODE_LEN && n.all { it in CODE_ALPHABET } }
    /** Constant-time compare. */
    fun same(a: String, b: String): Boolean = java.security.MessageDigest.isEqual(a.toByteArray(), b.toByteArray())
}

/** `loomlink://pair?u=<url>&c=<code>&n=<server id>` — what the desktop prints / shows as a QR. */
data class PairingUri(val url: String, val code: String, val serverId: String?) {
    companion object {
        fun parse(s: String): PairingUri {
            val u = URI(s.trim())
            require(u.scheme == "loomlink" && (u.host == "pair" || u.schemeSpecificPart.startsWith("//pair"))) { "not a loomlink://pair URI" }
            val q = (u.rawQuery ?: "").split("&").filter { it.contains("=") }.associate {
                val (k, v) = it.split("=", limit = 2); k to URLDecoder.decode(v, "UTF-8")
            }
            val url = q["u"] ?: throw IllegalArgumentException("pairing URI has no url")
            val code = q["c"] ?: throw IllegalArgumentException("pairing URI has no code")
            require(url.startsWith("http://") || url.startsWith("https://")) { "pairing url must be http(s)" }
            require(LoomCrypto.validCode(code)) { "malformed pairing code" }
            return PairingUri(url.trimEnd('/'), LoomCrypto.normaliseCode(code), q["n"])
        }
    }
}

class LinkException(val status: Int, message: String) : Exception(message)

/** Minimal HTTP seam so the client is unit-testable without sockets. */
fun interface Http {
    fun request(method: String, url: String, headers: Map<String, String>, body: ByteArray?): Pair<Int, ByteArray>
}

object UrlHttp : Http {
    var timeoutMs = 10_000
    override fun request(method: String, url: String, headers: Map<String, String>, body: ByteArray?): Pair<Int, ByteArray> {
        val c = URL(url).openConnection() as HttpURLConnection
        c.requestMethod = method; c.connectTimeout = timeoutMs; c.readTimeout = timeoutMs * 3
        headers.forEach { (k, v) -> c.setRequestProperty(k, v) }
        if (body != null) { c.doOutput = true; c.outputStream.use { it.write(body) } }
        val code = c.responseCode
        val data = (if (code < 400) c.inputStream else c.errorStream)?.use { it.readBytes() } ?: ByteArray(0)
        c.disconnect()
        return code to data
    }
}

/** A paired desktop (persisted in the app's private storage). */
data class LinkSession(val url: String, val clientId: String, val keyHex: String, val caps: List<String>,
                       val serverId: String, val pairedAt: Long) {
    fun toMap() = mapOf("url" to url, "client_id" to clientId, "key" to keyHex, "caps" to caps,
        "server_id" to serverId, "paired_at" to pairedAt)
    companion object {
        fun from(m: Map<String, Any?>) = LinkSession(m["url"] as String, m["client_id"] as String, m["key"] as String,
            m["caps"].asList().map { it as String }, m["server_id"] as String, m["paired_at"].asLong())
        fun load(f: File): LinkSession? = if (f.exists()) runCatching { from(Json.obj(f.readText())) }.getOrNull() else null
    }
    fun save(f: File) {
        f.parentFile?.mkdirs()
        val tmp = File(f.path + ".tmp"); tmp.writeText(Json.write(toMap()))
        tmp.setReadable(false, false); tmp.setReadable(true, true)
        if (!tmp.renameTo(f)) { f.delete(); tmp.renameTo(f) }
    }
}

class LoomLinkClient(val clientId: String, var session: LinkSession? = null, private val http: Http = UrlHttp,
                     private val clock: () -> Long = System::currentTimeMillis) {
    private var lastTs = 0L

    /** Pair with a desktop showing [code]. Throws if the desktop cannot prove the code (wrong
     *  host / MITM) or rejects ours. Granted caps = requested ∩ what the desktop user allows. */
    fun pair(url: String, code: String, caps: List<String> = listOf("offload", "sync")): LinkSession {
        require(LoomCrypto.validCode(code)) { "malformed pairing code" }
        val c = LoomCrypto.normaliseCode(code).toByteArray()
        val base = url.trimEnd('/')
        val nc = LoomCrypto.nonce()
        val h = postJson(base, "/pair/hello", mapOf("client_id" to clientId, "nc" to nc), signed = false)
        val ns = h["ns"] as String
        if (!LoomCrypto.same(h["proof"] as String, LoomCrypto.mac(c, "srv", nc, ns, clientId)))
            throw LinkException(0, "desktop failed to prove the pairing code")
        val r = postJson(base, "/pair/confirm", mapOf("client_id" to clientId, "nc" to nc, "ns" to ns, "caps" to caps,
            "proof" to LoomCrypto.mac(c, "cli", nc, ns, clientId)), signed = false)
        val s = LinkSession(base, clientId, LoomCrypto.mac(c, "key", nc, ns, clientId),
            r["granted"].asList().map { it as String }, r["server_id"] as String, clock())
        session = s
        return s
    }

    fun pair(uri: PairingUri, caps: List<String> = listOf("offload", "sync")) = pair(uri.url, uri.code, caps)

    private fun nextTs(): Long { val t = maxOf(clock(), lastTs + 1); lastTs = t; return t }

    private fun signHeaders(method: String, path: String, raw: ByteArray): Map<String, String> {
        val s = session ?: throw LinkException(0, "not paired")
        val ts = nextTs().toString()
        return mapOf("X-Loom-Client" to s.clientId, "X-Loom-Ts" to ts,
            "X-Loom-Sig" to LoomCrypto.mac(LoomCrypto.unhex(s.keyHex), method, path, ts, sha256Hex(raw)))
    }

    fun postJson(base: String?, path: String, body: Map<String, Any?>, signed: Boolean = true): Map<String, Any?> {
        val url = base ?: session?.url ?: throw LinkException(0, "not paired")
        val raw = Json.write(body).toByteArray()
        val hdr = mutableMapOf("Content-Type" to "application/json")
        if (signed) hdr.putAll(signHeaders("POST", path, raw))
        val (code, data) = http.request("POST", url + path, hdr, raw)
        val text = String(data, Charsets.UTF_8)
        val obj = runCatching { Json.obj(text) }.getOrElse { throw LinkException(code, "bad response ($code)") }
        if (code != 200) throw LinkException(code, obj["error"] as? String ?: "http $code")
        return obj
    }

    fun getBlob(sha: String): ByteArray {
        val s = session ?: throw LinkException(0, "not paired")
        val path = "/sync/blob/$sha"
        val (code, data) = http.request("GET", s.url + path, signHeaders("GET", path, ByteArray(0)), null)
        if (code != 200) throw LinkException(code, "blob $sha: http $code")
        require(sha256Hex(data) == sha) { "blob digest mismatch for $sha" }
        return data
    }

    fun has(cap: String) = session?.caps?.contains(cap) == true

    /** Send one queued job. Captures are expanded from the local store at send time so the
     *  offload journal stays small. */
    fun offload(job: JobSpec, store: AssetStore?): Map<String, Any?> {
        if (!has("offload")) throw LinkException(403, "capability 'offload' not granted")
        var payload = job.payload
        val blob = payload["blob_sha"] as String?
        if (blob != null && store != null) {
            val data = store.read(blob) ?: throw IllegalStateException("capture blob $blob missing locally")
            payload = payload + ("data_b64" to Base64.getEncoder().encodeToString(data)) + ("id" to payload["asset_id"])
        }
        return postJson(null, "/offload", job.copy(payload = payload, origin = clientId).toMap())
    }
}
