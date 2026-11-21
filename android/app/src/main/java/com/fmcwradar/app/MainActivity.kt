package com.fmcwradar.app

import android.annotation.SuppressLint
import android.app.Activity
import android.os.Bundle
import android.system.Os
import android.webkit.JavascriptInterface
import android.webkit.WebView
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONObject
import java.util.concurrent.Executors

/**
 * A WebView shell around fmcw_radar.appbridge (the pattern of polar_tx's and
 * array_tx's apps).
 *
 * Deliberately inert: every feature is a Python function behind webhost.Api
 * plus a render in the page.  If a change seems to need Kotlin, the logic
 * wanted to be in Python, where the test suite is.
 *
 * All Python runs on ONE background thread: the library is numpy / scipy code
 * with no locking, and the first call pays the import of numpy + scipy
 * (seconds on a phone).  Long work (the time engine's frame, a sweep, the band
 * table) runs on the library's own thread-backend job queue, so a call returns
 * at once and the page polls its jobs as it does on the desktop.
 */
class MainActivity : Activity() {

    private val executor = Executors.newSingleThreadExecutor()
    private lateinit var web: WebView
    private var bridge: PyObject? = null

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (!Python.isStarted()) {
            // a writable cache before Python.start(): a library that writes one on import dies on a read-only directory
            val cache = filesDir.resolve("cache").apply { mkdirs() }
            Os.setenv("XDG_CACHE_HOME", cache.path, true)
            Python.start(AndroidPlatform(this))
        }
        web = WebView(this)
        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = true          // the page remembers language and theme in localStorage
        web.addJavascriptInterface(HostBridge(), "host")
        setContentView(web)
        web.loadUrl("file:///android_asset/www/index.html")
    }

    inner class HostBridge {
        /** Async RPC: returns immediately, the reply lands via window.onHostReply. */
        @JavascriptInterface
        fun call(id: String, route: String, argsJson: String) {
            executor.execute {
                val reply = try {
                    val py = bridge ?: Python.getInstance()
                        .getModule("fmcw_radar.appbridge").also { bridge = it }
                    py.callAttr("call", route, argsJson).toString()
                } catch (e: Exception) {
                    JSONObject().put("ok", false).put("error", e.toString()).toString()
                }
                runOnUiThread {
                    web.evaluateJavascript(
                        "window.onHostReply(${JSONObject.quote(id)},${JSONObject.quote(reply)})", null)
                }
            }
        }
    }
}
