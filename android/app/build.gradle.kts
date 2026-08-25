plugins {
    id("com.android.application")
    kotlin("android")
}

android {
    namespace = "com.example.lazypc"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.example.lazypc"
        minSdk = 29
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }


    kotlinOptions {
        jvmTarget = "11"
    }

    buildFeatures {
        compose = true
    }

    composeOptions {
        kotlinCompilerExtensionVersion = "1.5.14"
    }
}

dependencies {

    // Compose
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.activity:activity-compose:1.9.0")

    implementation(platform("androidx.compose:compose-bom:2024.06.00"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation(libs.androidx.appcompat)
    debugImplementation("androidx.compose.ui:ui-tooling")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.4")

    // Network
    implementation("com.squareup.okhttp3:okhttp:4.12.0")


    // 🔥 WebRTC
    implementation("io.github.webrtc-sdk:android:125.6422.07")
    implementation("com.google.android.exoplayer:exoplayer:2.19.1")
    implementation("androidx.appcompat:appcompat:1.6.1")
    implementation("com.google.android.material:material:1.11.0")

    // Google ML Kit: system QR scanner (no CAMERA permission required)
    implementation("com.google.android.gms:play-services-code-scanner:16.1.0")
}