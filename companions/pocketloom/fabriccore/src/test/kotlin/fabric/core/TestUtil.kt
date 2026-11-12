package fabric.core

import java.io.File
import java.nio.file.Files

fun tmpDir(): File = Files.createTempDirectory("fabriccore-test").toFile().also { it.deleteOnExit() }

fun fixtures(): Map<String, Any?> =
    Json.obj(File(System.getProperty("fabric.fixtures"), "loomlink_vectors.json").readText())
