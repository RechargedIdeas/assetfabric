// FabricCore: pure-Kotlin shared module (JVM target). Used by the Android app and runnable on
// desktop JVMs (LoomCluster peer). Kotlin Multiplatform targets are a later step — see
// docs/INFERENCES.md (C-1).
plugins {
    id("org.jetbrains.kotlin.jvm")
    application
}

kotlin { jvmToolchain(17) }

dependencies {
    testImplementation(kotlin("test"))
}

application {
    mainClass.set("fabric.core.CliKt")
}

tasks.test { useJUnitPlatform() }

tasks.register<Jar>("fatJar") {
    archiveBaseName.set("fabriccore-all")
    manifest { attributes["Main-Class"] = "fabric.core.CliKt" }
    duplicatesStrategy = DuplicatesStrategy.EXCLUDE
    from(sourceSets.main.get().output)
    dependsOn(configurations.runtimeClasspath)
    from({ configurations.runtimeClasspath.get().filter { it.name.endsWith("jar") }.map { zipTree(it) } })
}
