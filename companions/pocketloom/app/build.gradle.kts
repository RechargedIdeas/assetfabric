plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "fabric.pocketloom"
    compileSdk = 35
    defaultConfig {
        applicationId = "com.rechargedideas.pocketloom"
        minSdk = 26
        targetSdk = 35
        versionCode = 3
        versionName = "0.3.0-c10"
    }
    buildTypes {
        // Debug builds only for now (auto debug keystore). Release signing is a TODO — docs/packaging.md.
        release { isMinifyEnabled = false }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    lint { abortOnError = true; checkReleaseBuilds = false }
}

dependencies {
    implementation(project(":fabriccore"))
    // C10/C11 ARCore (optional at runtime: "AR Optional" app). ARCore SDK — Google APIs ToS + ARCore Additional Terms
    // (commercial use allowed; in-app notice string `arcore_notice` required). THIRD_PARTY_NOTICES.md, INFERENCES C-68.
    implementation("com.google.ar:core:1.47.0")
}
