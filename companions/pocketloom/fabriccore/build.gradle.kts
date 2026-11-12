// FabricCore: pure-Kotlin shared module (JVM target, no third-party runtime dependencies).
// Used by the Android app (PocketLoom) and runnable on desktop JVMs as a CLI
// (`java -jar fabriccore-all.jar …`) — that CLI is what `forge accept C1…C6` drives for the
// Python↔Kotlin interop checks. Kotlin Multiplatform targets are a later step: docs/INFERENCES.md C-1.
plugins {
    id("org.jetbrains.kotlin.jvm")
    application
}

kotlin { jvmToolchain(17) }

dependencies {
    testImplementation(kotlin("test"))
}

// PatternVault palettes are bundled from the repo's single source of truth at build time.
val bundlePalettes by tasks.registering(Copy::class) {
    from(rootProject.file("../../content/patternvault/palettes.json"))
    into(layout.buildDirectory.dir("generated/fabricres/fabric"))
}
sourceSets.main { resources.srcDir(layout.buildDirectory.dir("generated/fabricres")) }
tasks.named("processResources") { dependsOn(bundlePalettes) }

application {
    mainClass.set("fabric.core.CliKt")
}

tasks.test {
    useJUnitPlatform()
    testLogging { events("failed"); exceptionFormat = org.gradle.api.tasks.testing.logging.TestExceptionFormat.FULL }
}

tasks.register<Jar>("fatJar") {
    archiveBaseName.set("fabriccore-all")
    manifest { attributes["Main-Class"] = "fabric.core.CliKt" }
    duplicatesStrategy = DuplicatesStrategy.EXCLUDE
    from(sourceSets.main.get().output)
    dependsOn(configurations.runtimeClasspath)
    from({ configurations.runtimeClasspath.get().filter { it.name.endsWith("jar") }.map { zipTree(it) } })
}
