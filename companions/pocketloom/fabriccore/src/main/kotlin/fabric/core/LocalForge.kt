package fabric.core

import java.io.ByteArrayOutputStream
import java.security.MessageDigest
import java.util.zip.CRC32
import java.util.zip.Deflater

/** Deterministic 31-bit LCG (same constants as the desktop persona sampler "lcg-1103515245"). */
class Lcg(seed: Long) {
    private var state: Long = seed and 0x7fffffffL
    fun next(): Long { state = (state * 1103515245L + 12345L) and 0x7fffffffL; return state }
    fun next01(): Double = next().toDouble() / 2147483648.0
    fun below(n: Int): Int = (next01() * n).toInt().coerceIn(0, n - 1)
}

data class Gate(val gate: String, val ok: Boolean, val value: Double? = null, val detail: String = "")

/** One generated artifact: palette-indexed pixels + PNG bytes + gates (the forge gate contract). */
class LocalAsset(
    val kind: String, val seed: Long, val width: Int, val height: Int,
    val argb: IntArray, val gates: List<Gate>, val meta: Map<String, Any?>,
) {
    val ok: Boolean get() = gates.all { it.ok }
    val png: ByteArray by lazy { Png.encode(width, height, argb) }
    val sha256: String by lazy { sha256Hex(png) }
}

fun sha256Hex(b: ByteArray): String = MessageDigest.getInstance("SHA-256").digest(b).joinToString("") { "%02x".format(it) }

fun parseHex(c: String): Int {
    val h = c.removePrefix("#")
    return (0xff shl 24) or h.toInt(16)
}

/** LocalForge (C2) — on-device procedural generation. CPU only, so it runs on any phone
 *  (GroundWeave: the CPU rung is the only rung on device). Same gate vocabulary as desktop. */
object LocalForge {
    /** Cellular-automata cave (G1-Tile CPU rung). Gates: solvability (one connected floor
     *  region), floor ratio inside [minFloor, maxFloor]. Largest region is kept; others filled. */
    fun cave(seed: Long, w: Int = 48, h: Int = 32, density: Double = 0.45, steps: Int = 4,
             palette: List<String>, minFloor: Double = 0.30, maxFloor: Double = 0.70): LocalAsset {
        val rng = Lcg(seed)
        var wall = BooleanArray(w * h) { i ->
            val x = i % w; val y = i / w
            x == 0 || y == 0 || x == w - 1 || y == h - 1 || rng.next01() < density
        }
        repeat(steps) {
            val n = BooleanArray(w * h)
            for (y in 0 until h) for (x in 0 until w) {
                if (x == 0 || y == 0 || x == w - 1 || y == h - 1) { n[y * w + x] = true; continue }
                var c = 0
                for (dy in -1..1) for (dx in -1..1) if ((dx != 0 || dy != 0) && wall[(y + dy) * w + x + dx]) c++
                n[y * w + x] = c >= 5 || (c >= 4 && wall[y * w + x])
            }
            wall = n
        }
        // keep the largest connected floor region (4-neighbour flood fill)
        val label = IntArray(w * h) { -1 }
        var best = -1; var bestSize = 0; var lab = 0
        for (start in 0 until w * h) {
            if (wall[start] || label[start] >= 0) continue
            val stack = ArrayDeque<Int>(); stack.add(start); label[start] = lab; var size = 0
            while (stack.isNotEmpty()) {
                val p = stack.removeLast(); size++
                val x = p % w; val y = p / w
                for ((nx, ny) in listOf(x + 1 to y, x - 1 to y, x to y + 1, x to y - 1)) {
                    if (nx < 0 || ny < 0 || nx >= w || ny >= h) continue
                    val q = ny * w + nx
                    if (!wall[q] && label[q] < 0) { label[q] = lab; stack.add(q) }
                }
            }
            if (size > bestSize) { bestSize = size; best = lab }
            lab++
        }
        for (i in 0 until w * h) if (!wall[i] && label[i] != best) wall[i] = true
        val floorRatio = bestSize.toDouble() / (w * h)
        val cols = palette.map(::parseHex)
        val argb = IntArray(w * h) { i -> if (wall[i]) cols[0] else cols[minOf(2, cols.size - 1)] }
        val gates = listOf(
            Gate("solvable", lab > 0 && bestSize > 0, bestSize.toDouble(), "single connected floor region"),
            Gate("floor_ratio", floorRatio in minFloor..maxFloor, floorRatio),
        )
        return LocalAsset("cave", seed, w, h, argb, gates,
            mapOf("floor_ratio" to Math.round(floorRatio * 1e4) / 1e4, "regions_merged" to lab, "backend" to "localforge-ca-cpu"))
    }

    /** Mirrored 8-bit creature sprite (G1-Sprite CPU rung). Gates: palette-locked, symmetric,
     *  fill ratio in [0.25, 0.75] of the bounding box, outlined. */
    fun sprite(seed: Long, size: Int = 16, palette: List<String>): LocalAsset {
        val rng = Lcg(seed)
        val half = (size + 1) / 2
        val body = Array(size) { BooleanArray(size) }
        val cx = size / 2.0; val cy = size / 2.0
        for (y in 1 until size - 1) for (x in 1 until half) {
            val dx = (x + 0.5 - cx) / cx; val dy = (y + 0.5 - cy) / cy
            val p = 0.85 - (dx * dx + dy * dy) * 0.9
            if (rng.next01() < p) { body[y][x] = true; body[y][size - 1 - x] = true }
        }
        val cols = palette.map(::parseHex)
        val shade = IntArray(size * size)  // 0 transparent, 1 outline, 2.. body tones
        for (y in 0 until size) for (x in 0 until size) {
            if (body[y][x]) {
                val tone = if (y < size / 3) 3 else if (y > 2 * size / 3) 1 else 2
                shade[y * size + x] = 1 + tone
            }
        }
        for (y in 0 until size) for (x in 0 until size) {
            if (body[y][x]) continue
            var adj = false
            for ((nx, ny) in listOf(x + 1 to y, x - 1 to y, x to y + 1, x to y - 1))
                if (nx in 0 until size && ny in 0 until size && body[ny][nx]) adj = true
            if (adj) shade[y * size + x] = 1
        }
        // eyes (accent) on the upper third, mirrored
        val ey = size / 3 + rng.below(maxOf(1, size / 6)); val ex = half - 2 - rng.below(maxOf(1, half / 3))
        for (x in listOf(ex, size - 1 - ex)) if (ex >= 1 && body[ey][x]) shade[ey * size + x] = 6
        val argb = IntArray(size * size) { i ->
            when (val s = shade[i]) { 0 -> 0; else -> cols[minOf(s - 1, cols.size - 1)] }
        }
        val filled = shade.count { it >= 2 }
        val symmetric = (0 until size).all { y -> (0 until size).all { x -> shade[y * size + x] == shade[y * size + size - 1 - x] } }
        val paletteLocked = argb.all { it == 0 || it in cols }
        val fill = filled.toDouble() / (size * size)
        val gates = listOf(
            Gate("palette_locked", paletteLocked),
            Gate("symmetric", symmetric),
            Gate("fill_ratio", fill in 0.2..0.75, fill),
        )
        return LocalAsset("sprite", seed, size, size, argb, gates, mapOf("fill" to Math.round(fill * 1e4) / 1e4, "backend" to "localforge-sprite-cpu"))
    }
}

/** Dependency-free RGBA PNG encoder (works on JVM and Android; no Bitmap needed). */
object Png {
    fun encode(w: Int, h: Int, argb: IntArray): ByteArray {
        val raw = ByteArray(h * (1 + w * 4))
        var o = 0
        for (y in 0 until h) {
            raw[o++] = 0
            for (x in 0 until w) {
                val p = argb[y * w + x]
                raw[o++] = (p shr 16).toByte(); raw[o++] = (p shr 8).toByte(); raw[o++] = p.toByte(); raw[o++] = (p ushr 24).toByte()
            }
        }
        val def = Deflater(9); def.setInput(raw); def.finish()
        val z = ByteArrayOutputStream(); val buf = ByteArray(8192)
        while (!def.finished()) { val n = def.deflate(buf); z.write(buf, 0, n) }
        def.end()
        val out = ByteArrayOutputStream()
        out.write(byteArrayOf(0x89.toByte(), 'P'.code.toByte(), 'N'.code.toByte(), 'G'.code.toByte(), 13, 10, 26, 10))
        val ihdr = ByteArrayOutputStream().apply { int(w); int(h); write(8); write(6); write(0); write(0); write(0) }.toByteArray()
        chunk(out, "IHDR", ihdr); chunk(out, "IDAT", z.toByteArray()); chunk(out, "IEND", ByteArray(0))
        return out.toByteArray()
    }
    private fun ByteArrayOutputStream.int(v: Int) { write(v ushr 24); write(v ushr 16); write(v ushr 8); write(v) }
    private fun chunk(out: ByteArrayOutputStream, type: String, data: ByteArray) {
        out.int(data.size)
        val t = type.toByteArray(Charsets.US_ASCII)
        out.write(t); out.write(data)
        val crc = CRC32(); crc.update(t); crc.update(data)
        out.int(crc.value.toInt())
    }
}

/** PatternVault palettes bundled from content/patternvault/palettes.json at build time. */
object Palettes {
    private val vault: Map<String, Any?> by lazy {
        val text = Palettes::class.java.getResourceAsStream("/fabric/palettes.json")!!.bufferedReader().readText()
        Json.obj(text)
    }
    fun names(): List<String> = vault["palettes"].asMap().keys.sorted()
    fun colours(name: String): List<String> = vault["palettes"].asMap()[name].asMap()["colours"].asList().map { it as String }
    fun loadFrom(text: String): Map<String, List<String>> =
        Json.obj(text)["palettes"].asMap().mapValues { (_, v) -> v.asMap()["colours"].asList().map { it as String } }
}
