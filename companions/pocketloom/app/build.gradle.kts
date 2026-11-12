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
        versionCode = 1
        versionName = "0.1.0-c6"
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
}
