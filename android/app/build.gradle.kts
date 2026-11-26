plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

android {
    namespace = "com.fmcwradar.app"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.fmcwradar.app"
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        versionName = "0.2.35"            // tracks the fmcw_radar version it bundles (tests/test_android.py)
        ndk {
            // arm64 for phones, x86_64 for the emulator; each ABI carries its
            // own CPython + numpy / scipy (tens of MB each)
            abiFilters += listOf("arm64-v8a", "x86_64")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    sourceSets {
        getByName("main") {
            // One page for every host: the desktop window and the browser get
            // it from fmcw_radar.webhost (src/fmcw_radar/webui/www), and this
            // APK takes the very same files as its assets, loaded from
            // file:///android_asset/www/.
            assets.setSrcDirs(listOf("../../src/fmcw_radar/webui"))
        }
    }
}

chaquopy {
    defaultConfig {
        // 3.10: the newest Python for which Chaquopy's repository has a scipy
        // wheel (chaquo/chaquopy#1237); fmcw_radar declares requires-python
        // >= 3.10 and its CI runs 3.10.
        version = "3.10"
        pip {
            // Android binary wheels from Chaquopy's index; pyyaml comes from
            // PyPI in the same resolve.  No matplotlib: the library's plots
            // are an optional extra the page does not use.
            install("numpy")
            install("scipy")
            install("pyyaml")
            // fmcw_radar itself as an sdist (interpreted build).  An sdist,
            // not install("../.."): a directory install makes the whole
            // repository an input of the pip task and this Gradle project
            // lives inside that repository, which Gradle 8's validation
            // rejects.  From the repo root:
            //   python -m build --sdist --outdir android/app/pysrc .
            val pysrc = file("pysrc")
            val sdists = pysrc.listFiles { f -> f.name.matches(Regex("fmcw_radar-.*\\.tar\\.gz")) }?.toList() ?: emptyList()
            require(sdists.size == 1) {
                "expected exactly one fmcw_radar sdist in android/app/pysrc/ (found ${sdists.size}); " +
                    "from the repo root run: python -m build --sdist --outdir android/app/pysrc ."
            }
            install(sdists[0].absolutePath)
        }
    }
}
