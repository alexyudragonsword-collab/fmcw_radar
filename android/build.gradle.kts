plugins {
    id("com.android.application") version "8.1.4" apply false
    id("org.jetbrains.kotlin.android") version "1.9.24" apply false
    // The version set is polar_tx's and array_tx's (their docs/android.md):
    // Chaquopy 15.x is the newest line whose repository carries scipy for
    // Python 3.10, and 3.10 is the newest Python with an Android scipy wheel.
    // Change one of plugin / Python version / CI setup-python and re-check the
    // others (tests/test_android.py holds the three together).
    id("com.chaquo.python") version "15.0.1" apply false
}
