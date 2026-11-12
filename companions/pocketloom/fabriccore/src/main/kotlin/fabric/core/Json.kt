package fabric.core

/** Minimal JSON (RFC 8259) reader/writer so FabricCore has no third-party dependencies.
 *  Values map to: Map<String, Any?>, List<Any?>, String, Long, Double, Boolean, null.
 *  `write` emits canonical JSON (sorted keys, no spaces) — the same canonical form the
 *  desktop forge uses for checksums (forge/save.py `canonical`). */
object Json {
    fun parse(text: String): Any? {
        val p = Parser(text)
        p.ws()
        val v = p.value()
        p.ws()
        require(p.i == text.length) { "trailing data at ${p.i}" }
        return v
    }

    @Suppress("UNCHECKED_CAST")
    fun obj(text: String): Map<String, Any?> = parse(text) as Map<String, Any?>

    fun write(v: Any?): String = StringBuilder().also { emit(v, it) }.toString()

    private fun emit(v: Any?, sb: StringBuilder) {
        when (v) {
            null -> sb.append("null")
            is String -> str(v, sb)
            is Boolean -> sb.append(v)
            is Int, is Long, is Short, is Byte -> sb.append(v.toString())
            is Double, is Float -> {
                val d = (v as Number).toDouble()
                require(d.isFinite()) { "non-finite number" }
                if (d == Math.rint(d) && Math.abs(d) < 1e15) sb.append(d.toLong()) else sb.append(d.toString())
            }
            is Map<*, *> -> {
                sb.append('{')
                v.keys.map { it.toString() }.sorted().forEachIndexed { i, k ->
                    if (i > 0) sb.append(',')
                    str(k, sb); sb.append(':'); emit(v[k], sb)
                }
                sb.append('}')
            }
            is Iterable<*> -> {
                sb.append('[')
                v.forEachIndexed { i, x -> if (i > 0) sb.append(','); emit(x, sb) }
                sb.append(']')
            }
            is Array<*> -> emit(v.toList(), sb)
            is IntArray -> emit(v.toList(), sb)
            else -> str(v.toString(), sb)
        }
    }

    private fun str(s: String, sb: StringBuilder) {
        sb.append('"')
        for (c in s) {
            when (c) {
                '"' -> sb.append("\\\"")
                '\\' -> sb.append("\\\\")
                '\n' -> sb.append("\\n")
                '\r' -> sb.append("\\r")
                '\t' -> sb.append("\\t")
                '\b' -> sb.append("\\b")
                '\u000C' -> sb.append("\\f")
                else -> if (c < ' ') sb.append(String.format("\\u%04x", c.code)) else sb.append(c)
            }
        }
        sb.append('"')
    }

    private class Parser(val s: String) {
        var i = 0
        fun ws() { while (i < s.length && s[i] in " \t\r\n") i++ }
        fun value(): Any? {
            ws()
            require(i < s.length) { "unexpected end" }
            return when (s[i]) {
                '{' -> obj()
                '[' -> arr()
                '"' -> string()
                't' -> lit("true", true)
                'f' -> lit("false", false)
                'n' -> lit("null", null)
                else -> num()
            }
        }
        fun lit(w: String, v: Any?): Any? {
            require(s.startsWith(w, i)) { "bad literal at $i" }
            i += w.length; return v
        }
        fun obj(): Map<String, Any?> {
            val m = LinkedHashMap<String, Any?>()
            i++; ws()
            if (s[i] == '}') { i++; return m }
            while (true) {
                ws(); val k = string(); ws()
                require(s[i] == ':') { "expected : at $i" }; i++
                m[k] = value(); ws()
                if (s[i] == ',') { i++; continue }
                require(s[i] == '}') { "expected } at $i" }; i++; return m
            }
        }
        fun arr(): List<Any?> {
            val l = ArrayList<Any?>()
            i++; ws()
            if (s[i] == ']') { i++; return l }
            while (true) {
                l.add(value()); ws()
                if (s[i] == ',') { i++; continue }
                require(s[i] == ']') { "expected ] at $i" }; i++; return l
            }
        }
        fun string(): String {
            require(s[i] == '"') { "expected string at $i" }
            i++
            val sb = StringBuilder()
            while (true) {
                val c = s[i++]
                when (c) {
                    '"' -> return sb.toString()
                    '\\' -> {
                        val e = s[i++]
                        when (e) {
                            'n' -> sb.append('\n'); 't' -> sb.append('\t'); 'r' -> sb.append('\r')
                            'b' -> sb.append('\b'); 'f' -> sb.append('\u000C')
                            'u' -> { sb.append(s.substring(i, i + 4).toInt(16).toChar()); i += 4 }
                            else -> sb.append(e)
                        }
                    }
                    else -> sb.append(c)
                }
            }
        }
        fun num(): Any {
            val st = i
            while (i < s.length && s[i] in "+-0123456789.eE") i++
            val t = s.substring(st, i)
            require(t.isNotEmpty()) { "bad value at $st" }
            return if (t.any { it in ".eE" }) t.toDouble() else t.toLong()
        }
    }
}

fun Any?.asMap(): Map<String, Any?> = @Suppress("UNCHECKED_CAST") (this as Map<String, Any?>)
fun Any?.asList(): List<Any?> = @Suppress("UNCHECKED_CAST") (this as List<Any?>)
fun Any?.asLong(): Long = (this as Number).toLong()
fun Any?.asDouble(): Double = (this as Number).toDouble()
