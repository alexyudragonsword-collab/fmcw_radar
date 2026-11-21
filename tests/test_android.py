"""The Android shell, checked from text (no SDK, no emulator): no
permissions; the activity calls the module that exists and speaks the
bridge the page speaks; the Gradle assets path is the page; the versions
that have to move together are together."""

import re

from conftest import REPO

import fmcw_radar
from fmcw_radar.webhost import WWW

ANDROID = REPO / "android"
KT = ANDROID / "app/src/main/java/com/fmcwradar/app/MainActivity.kt"


def _read(p):
    return p.read_text(encoding="utf-8")


def test_the_manifest_asks_for_no_permission():
    m = _read(ANDROID / "app/src/main/AndroidManifest.xml")
    assert "<uses-permission" not in m and 'android:name=".MainActivity"' in m
    assert 'android:icon="@drawable/ic_launcher"' in m and (ANDROID / "app/src/main/res/drawable/ic_launcher.xml").is_file()


def test_the_activity_calls_the_bridge_that_exists_and_gradle_bundles_the_page():
    kt, gradle = _read(KT), _read(ANDROID / "app/build.gradle.kts")
    assert 'getModule("fmcw_radar.appbridge")' in kt and 'callAttr("call"' in kt
    assert "window.onHostReply" in kt and 'addJavascriptInterface(HostBridge(), "host")' in kt
    assert 'loadUrl("file:///android_asset/www/index.html")' in kt
    import fmcw_radar.appbridge as ab

    assert callable(ab.call)
    assets = re.search(r'assets\.setSrcDirs\(listOf\("([^"]+)"\)\)', gradle).group(1)
    assert (ANDROID / "app" / assets).resolve() == WWW.parent.resolve()
    # one package name in three places: the Kotlin file, its directory, the Gradle namespace and application id
    pkg = re.search(r"^package (\S+)", kt, flags=re.M).group(1)
    assert pkg == "com.fmcwradar.app" and KT.parent == ANDROID / "app/src/main/java" / pkg.replace(".", "/")
    assert f'namespace = "{pkg}"' in gradle and f'applicationId = "{pkg}"' in gradle


def test_the_versions_that_move_together_are_together():
    gradle, top = _read(ANDROID / "app/build.gradle.kts"), _read(ANDROID / "build.gradle.kts")
    wf = _read(REPO / ".github/workflows/android.yml")
    meta = _read(REPO / "pyproject.toml")
    # the Python Chaquopy embeds, the one CI builds the sdist with, and what the library declares it runs on
    assert 'version = "3.10"' in gradle and 'python-version: "3.10"' in wf and 'requires-python = ">=3.10"' in meta
    assert 'id("com.chaquo.python") version "15.0.1"' in top and 'id("com.android.application") version "8.1.4"' in top
    assert 'java-version: "17"' in wf and "JavaVersion.VERSION_17" in gradle
    # the app's version is the library's
    assert f'versionName = "{fmcw_radar.__version__}"' in gradle
    # every binary dependency the library declares is asked of Chaquopy's index by name; the library itself as an sdist
    deps = re.findall(r'^\s+"([a-z]+)[><=]', meta.split("dependencies = [")[1].split("]")[0], flags=re.M)
    assert sorted(deps) == ["numpy", "pyyaml", "scipy"] and all(f'install("{d}")' in gradle for d in deps)
    assert r'Regex("fmcw_radar-.*\\.tar\\.gz")' in gradle and "python -m build --sdist --outdir android/app/pysrc ." in wf
    assert "android/app/pysrc" in gradle or "pysrc" in gradle
    assert "app/pysrc/" in _read(ANDROID / ".gitignore")


def test_the_page_speaks_the_bridge_and_is_ready_for_a_phone():
    js, html, css = _read(WWW / "app.js"), _read(WWW / "index.html"), _read(WWW / "style.css")
    assert "window.onHostReply" in js and "window.host.call(id, route" in js and "const ON_DEVICE" in js
    assert "viewport-fit=cover" in html and "env(safe-area-inset-top)" in css and "env(safe-area-inset-bottom)" in css
    # an element hidden with the attribute but styled with a display stays on screen and eats every tap: each such class says so
    assert ".busy[hidden]{display:none}" in css
    # the workflow checks the page went into the APK, every file of it
    wf = _read(REPO / ".github/workflows/android.yml")
    for f in sorted(p.name for p in WWW.iterdir()):
        assert f in wf, f
