package com.cglbuddy.app

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.ComponentActivity
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.io.File
import java.io.FileOutputStream

class MainActivity : ComponentActivity() {
    private lateinit var webView: WebView
    private var pendingCallbackId: String? = null
    private var pendingKind: String = "file"

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        copyAssetTree("data", File(filesDir, "bundle/data"))
        startPythonBackend()

        webView = WebView(this)
        setContentView(webView)

        webView.settings.javaScriptEnabled = true
        webView.settings.domStorageEnabled = true
        webView.settings.cacheMode = WebSettings.LOAD_DEFAULT
        webView.settings.allowFileAccess = true
        webView.settings.allowContentAccess = true
        webView.webViewClient = WebViewClient()
        webView.webChromeClient = WebChromeClient()
        webView.addJavascriptInterface(AndroidBridge(), "CglBuddyAndroid")

        Handler(Looper.getMainLooper()).postDelayed({
            webView.loadUrl("file:///android_asset/frontend/index.html")
        }, 900)
    }

    private fun startPythonBackend() {
        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(this))
        }
        Python.getInstance()
            .getModule("android_entry")
            .callAttr("start_server", filesDir.absolutePath)
    }

    private fun copyAssetTree(assetPath: String, targetDir: File) {
        val children = assets.list(assetPath) ?: return
        if (children.isEmpty()) {
            targetDir.parentFile?.mkdirs()
            assets.open(assetPath).use { input ->
                FileOutputStream(targetDir).use { output -> input.copyTo(output) }
            }
            return
        }
        targetDir.mkdirs()
        children.forEach { child -> copyAssetTree("$assetPath/$child", File(targetDir, child)) }
    }

    inner class AndroidBridge {
        @JavascriptInterface
        fun pickFile(kind: String, callbackId: String) {
            pendingKind = kind
            pendingCallbackId = callbackId
            val mimeTypes = when (kind) {
                "pdf" -> arrayOf("application/pdf")
                "image" -> arrayOf("image/*", "application/pdf")
                "database" -> arrayOf("application/json", "text/json", "text/plain")
                else -> arrayOf("*/*")
            }
            val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                addCategory(Intent.CATEGORY_OPENABLE)
                type = if (mimeTypes.size == 1) mimeTypes[0] else "*/*"
                putExtra(Intent.EXTRA_MIME_TYPES, mimeTypes)
            }
            startActivityForResult(intent, FILE_PICK_REQUEST)
        }
    }

    @Deprecated("Needed for broad API 28+ compatibility without extra dependencies.")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != FILE_PICK_REQUEST) return
        val callbackId = pendingCallbackId ?: return
        val path = if (resultCode == Activity.RESULT_OK && data?.data != null) {
            copySelectedUri(data.data!!, pendingKind)?.absolutePath
        } else {
            null
        }
        val jsPath = path?.replace("\\", "\\\\")?.replace("'", "\\'") ?: ""
        webView.post {
            webView.evaluateJavascript("window.__androidFileResult && window.__androidFileResult('$callbackId', '$jsPath')", null)
        }
        pendingCallbackId = null
    }

    private fun copySelectedUri(uri: Uri, kind: String): File? {
        val extension = when (kind) {
            "pdf" -> ".pdf"
            "database" -> ".json"
            else -> guessExtension(uri)
        }
        val dir = File(filesDir, "imports").apply { mkdirs() }
        val target = File(dir, "import_${System.currentTimeMillis()}$extension")
        return try {
            contentResolver.openInputStream(uri)?.use { input ->
                FileOutputStream(target).use { output -> input.copyTo(output) }
            }
            target
        } catch (_: Exception) {
            null
        }
    }

    private fun guessExtension(uri: Uri): String {
        val last = uri.lastPathSegment ?: return ".bin"
        return when {
            last.endsWith(".png", true) -> ".png"
            last.endsWith(".jpg", true) || last.endsWith(".jpeg", true) -> ".jpg"
            last.endsWith(".webp", true) -> ".webp"
            last.endsWith(".pdf", true) -> ".pdf"
            else -> ".bin"
        }
    }

    companion object {
        private const val FILE_PICK_REQUEST = 2307
    }
}
