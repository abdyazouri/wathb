import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
}

android {
    namespace = "com.yawmiyati.app"
    compileSdk = 36

    // Release signing: android/keystore.properties (gitignored; see docs/TRIAL_DISTRIBUTION.md) holds
    // storeFile, storePassword, keyAlias and keyPassword. Debug builds work without it; a release build
    // stops with a clear message when it is missing, so an unsigned APK is never produced by mistake.
    val keystoreFile = rootProject.file("keystore.properties")
    val keystore = Properties().apply {
        if (keystoreFile.exists()) keystoreFile.inputStream().use { load(it) }
    }
    val signingKeys = listOf("storeFile", "storePassword", "keyAlias", "keyPassword")
    val hasReleaseKey = signingKeys.all { !keystore.getProperty(it).isNullOrBlank() }
    val buildsRelease = gradle.startParameter.taskNames.any { it.contains("Release", ignoreCase = true) }
    if (buildsRelease && !hasReleaseKey) {
        throw GradleException(
            "Release signing is not set up: create android/keystore.properties with " +
                signingKeys.joinToString(", ") + " (see docs/TRIAL_DISTRIBUTION.md)."
        )
    }

    if (hasReleaseKey) {
        signingConfigs {
            create("release") {
                storeFile     = rootProject.file(keystore.getProperty("storeFile"))
                storePassword = keystore.getProperty("storePassword")
                keyAlias      = keystore.getProperty("keyAlias")
                keyPassword   = keystore.getProperty("keyPassword")
            }
        }
    }

    defaultConfig {
        applicationId = "com.wathb.app"
        minSdk = 26
        targetSdk = 36
        // RELEASE RULE: raise versionCode whenever backend accounts/consent.py
        // bumps CONSENT_VERSION — old clients must update before they can register.
        // Every distributed build needs a higher versionCode (testers update over the old one).
        versionCode = 3
        versionName = "0.9.0-trial.1"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    buildTypes {
        debug {
            isDebuggable = true
            // Local override: add wathbApiBaseUrl=http://10.0.2.2:8000/api/v1/ to
            // ~/.gradle/gradle.properties and run `adb reverse tcp:8000 tcp:8000`.
            val debugUrl = providers.gradleProperty("wathbApiBaseUrl")
                .getOrElse("https://wathb-api2.onrender.com/api/v1/")
            buildConfigField("String", "API_BASE_URL", "\"$debugUrl\"")
        }
        release {
            isMinifyEnabled = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
            buildConfigField("String", "API_BASE_URL", "\"https://wathb-api2.onrender.com/api/v1/\"")
            if (hasReleaseKey) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.ui)
    implementation(libs.androidx.ui.graphics)
    implementation(libs.androidx.ui.tooling.preview)
    implementation(libs.androidx.material3)
    implementation(libs.androidx.material.icons.extended)
    implementation(libs.androidx.navigation.compose)
    implementation(libs.androidx.viewmodel.compose)

    // Networking
    implementation(libs.retrofit)
    implementation(libs.retrofit.gson)
    implementation(libs.okhttp)
    implementation(libs.okhttp.logging)
    implementation(libs.gson)
    implementation(libs.play.services.auth.api.phone)

    // Image loading
    implementation(libs.coil.compose)

    // Maps
    implementation("org.osmdroid:osmdroid-android:6.1.18")

    // Biometric
    implementation("androidx.biometric:biometric:1.1.0")

    // Coroutines
    implementation(libs.kotlinx.coroutines.android)

    // Storage
    implementation(libs.androidx.datastore.preferences)
    implementation(libs.androidx.security.crypto)

    testImplementation(libs.junit)
    testImplementation(libs.kotlinx.coroutines.test)
    testImplementation(libs.okhttp.mockwebserver)
    androidTestImplementation(libs.androidx.junit)
    androidTestImplementation(libs.androidx.espresso.core)
    androidTestImplementation(platform(libs.androidx.compose.bom))
    androidTestImplementation(libs.androidx.ui.test.junit4)
    debugImplementation(libs.androidx.ui.tooling)
    debugImplementation(libs.androidx.ui.test.manifest)
}
