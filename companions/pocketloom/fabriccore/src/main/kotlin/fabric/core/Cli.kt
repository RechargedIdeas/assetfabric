package fabric.core

import java.io.File
import kotlin.system.exitProcess

/** Desktop/JVM entry point for FabricCore — same code the APK runs. Used by `forge accept C1…C6`
 *  (Python↔Kotlin interop) and for headless debugging. Prints one JSON document to stdout.
 *
 *  fabriccore-all.jar <cmd> --home DIR [options]
 *    info | status
 *    gen --kind cave|sprite --seed N [--count K] [--palette P]
 *    capture --file F [--source S]
 *    offload --op hashchain --seed S [--rounds R]           (queue a job for the desktop)
 *    pair (--uri loomlink://… | --url U --code C) [--caps offload,sync]
 *    drain | sync | unpair
 *    put --id ID --file F [--kind K]                          (edit the local store; sync tests)
 */
fun main(args: Array<String>) {
    val cmd = args.firstOrNull() ?: usage()
    val opts = HashMap<String, String>()
    var i = 1
    while (i < args.size) {
        val k = args[i]; require(k.startsWith("--")) { "bad arg $k" }
        opts[k.removePrefix("--")] = args.getOrNull(i + 1) ?: ""; i += 2
    }
    val out: Any? = try {
        if (cmd == "info") mapOf("version" to PocketLoomCore.VERSION, "ops" to LocalExecutor(null) { emptyList() }.ops.sorted(),
            "palettes" to Palettes.names(), "onnx_runtime_bundled" to GenBackends.ONNX_RUNTIME_BUNDLED)
        else {
            val core = PocketLoomCore(File(opts["home"] ?: usage()), opts["node"])
            when (cmd) {
                "status" -> core.status()
                "gen" -> {
                    val seed = (opts["seed"] ?: "1").toLong(); val n = (opts["count"] ?: "1").toInt()
                    (0 until n).map { core.generate(opts["kind"] ?: "cave", seed + it, opts["palette"]) }
                }
                "capture" -> core.capture(File(opts["file"]!!).readBytes(), opts["source"] ?: "import",
                    mapOf("captured_at" to System.currentTimeMillis(), "device" to "jvm-cli"))
                "offload" -> core.dispatcher.submit(JobSpec("off_" + LoomCrypto.nonce().substring(0, 10), opts["op"] ?: "hashchain",
                    mapOf("seed" to (opts["seed"] ?: "0"), "rounds" to (opts["rounds"] ?: "20000").toLong())), preferOffload = true)
                "pair" -> core.pair(opts["uri"] ?: opts["url"]!!, opts["code"],
                    (opts["caps"] ?: "offload,sync").split(",").filter { it.isNotBlank() }).let { it.toMap() - "key" }
                "drain" -> core.drain() + ("results" to core.queue.results())
                "sync" -> core.sync()
                "unpair" -> { core.unpair(); mapOf("ok" to true) }
                "put" -> core.store.put(opts["id"]!!, opts["kind"] ?: "sprite", File(opts["file"]!!).readBytes(), mapOf("source" to "cli"))
                "index" -> core.store.index()
                else -> usage()
            }
        }
    } catch (e: LinkException) {
        println(Json.write(mapOf("error" to e.message, "status" to e.status))); exitProcess(3)
    } catch (e: Exception) {
        println(Json.write(mapOf("error" to e.toString()))); exitProcess(1)
    }
    println(Json.write(out))
}

private fun usage(): Nothing {
    System.err.println("usage: fabriccore <info|status|gen|capture|offload|pair|drain|sync|unpair|put|index> --home DIR …")
    exitProcess(2)
}
