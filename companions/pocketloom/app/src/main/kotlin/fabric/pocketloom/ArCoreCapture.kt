package fabric.pocketloom

import android.app.Activity
import android.graphics.ImageFormat
import android.graphics.Rect
import android.graphics.YuvImage
import android.media.Image
import android.opengl.EGL14
import android.opengl.EGLConfig
import android.opengl.EGLContext
import android.opengl.EGLDisplay
import android.opengl.EGLSurface
import android.opengl.GLES11Ext
import android.opengl.GLES20
import android.os.Handler
import android.os.HandlerThread
import com.google.ar.core.ArCoreApk
import com.google.ar.core.Config
import com.google.ar.core.Frame
import com.google.ar.core.Session
import com.google.ar.core.TrackingState
import com.google.ar.core.exceptions.NotYetAvailableException
import fabric.core.ArDepthFrame
import java.io.ByteArrayOutputStream
import java.nio.ByteOrder

/** ARCore capture (C10 `lens.arcore_session`, C11 `depth.arcore`) on the ARCore SDK. Runs a headless session — an
 *  offscreen EGL pbuffer context owns the camera texture ARCore needs — and samples one [ArDepthFrame] every
 *  [intervalMs] while tracking: camera pose, image intrinsics, DEPTH16 (+ raw-depth confidence) when the device supports
 *  the Depth API, and the camera image as JPEG. ARCore is optional: on devices without Google Play Services for AR this
 *  reports `unsupported` and the app keeps working. Status: compiled, **never run on a phone** (`real_unverified_on_device`).
 *  The caller must hold CAMERA. Use of ARCore is subject to the Google APIs ToS + ARCore Additional Terms (in-app notice). */
class ArCoreCapture(private val activity: Activity) {
    sealed class Result {
        data class Frames(val frames: List<ArDepthFrame>, val depthSupported: Boolean) : Result()
        data class Unavailable(val reason: String) : Result()
    }

    private val thread = HandlerThread("arcore").apply { start() }
    private val handler = Handler(thread.looper)

    /** Availability check; may ask the user to install/update Google Play Services for AR (user-initiated). */
    fun ensureInstalled(userRequested: Boolean): String = try {
        when (ArCoreApk.getInstance().requestInstall(activity, userRequested)) {
            ArCoreApk.InstallStatus.INSTALLED -> "installed"
            else -> "install_requested"
        }
    } catch (e: Exception) { "unsupported: ${e.javaClass.simpleName}" }

    fun capture(count: Int, intervalMs: Long, onDone: (Result) -> Unit) {
        handler.post { onDone(runCatching { run(count, intervalMs) }.getOrElse { Result.Unavailable("${it.javaClass.simpleName}: ${it.message}") }) }
    }

    fun close() { thread.quitSafely() }

    private fun run(count: Int, intervalMs: Long): Result {
        val avail = ArCoreApk.getInstance().checkAvailability(activity)
        if (!avail.isSupported) return Result.Unavailable("arcore_unsupported:$avail")
        val egl = OffscreenEgl()
        val session = Session(activity)
        try {
            val cfg = Config(session).apply {
                focusMode = Config.FocusMode.AUTO
                updateMode = Config.UpdateMode.BLOCKING
                depthMode = if (session.isDepthModeSupported(Config.DepthMode.AUTOMATIC)) Config.DepthMode.AUTOMATIC else Config.DepthMode.DISABLED
            }
            session.configure(cfg)
            session.setCameraTextureName(egl.texture)
            session.resume()
            val out = ArrayList<ArDepthFrame>()
            var last = 0L
            val deadline = System.currentTimeMillis() + count * intervalMs + 15_000
            while (out.size < count && System.currentTimeMillis() < deadline) {
                val frame = session.update()
                if (frame.camera.trackingState != TrackingState.TRACKING) continue
                val now = System.currentTimeMillis()
                if (now - last < intervalMs) continue
                last = now
                out.add(toFrame(frame, cfg.depthMode == Config.DepthMode.AUTOMATIC))
            }
            return Result.Frames(out, cfg.depthMode == Config.DepthMode.AUTOMATIC)
        } finally {
            session.pause(); session.close(); egl.release()
        }
    }

    private fun toFrame(frame: Frame, depth: Boolean): ArDepthFrame {
        val p = frame.camera.pose
        val intr = frame.camera.imageIntrinsics
        val f = intr.focalLength; val c = intr.principalPoint; val dim = intr.imageDimensions
        var w = 0; var h = 0; var mm: IntArray? = null; var conf: IntArray? = null
        if (depth) {
            try {
                frame.acquireDepthImage16Bits().use { img -> w = img.width; h = img.height; mm = plane16(img) }
                frame.acquireRawDepthConfidenceImage().use { img -> if (img.width == w && img.height == h) conf = plane8(img) }
            } catch (_: NotYetAvailableException) { mm = null; conf = null; w = 0; h = 0 }
        }
        val jpeg = try { frame.acquireCameraImage().use { yuvToJpeg(it) } } catch (_: NotYetAvailableException) { null }
        return ArDepthFrame(if (mm != null) w else 0, if (mm != null) h else 0, mm, if (mm != null) conf else null,
            doubleArrayOf(p.tx().toDouble(), p.ty().toDouble(), p.tz().toDouble(), p.qx().toDouble(), p.qy().toDouble(), p.qz().toDouble(), p.qw().toDouble()),
            f[0].toDouble(), f[1].toDouble(), c[0].toDouble(), c[1].toDouble(), dim[0], dim[1], frame.timestamp, jpeg)
    }

    private fun plane16(img: Image): IntArray {
        val pl = img.planes[0]; val buf = pl.buffer.order(ByteOrder.LITTLE_ENDIAN)
        return IntArray(img.width * img.height) { i -> val x = i % img.width; val y = i / img.width
            buf.getShort(y * pl.rowStride + x * pl.pixelStride).toInt() and 0xFFFF }
    }

    private fun plane8(img: Image): IntArray {
        val pl = img.planes[0]; val buf = pl.buffer
        return IntArray(img.width * img.height) { i -> val x = i % img.width; val y = i / img.width
            buf.get(y * pl.rowStride + x * pl.pixelStride).toInt() and 0xFF }
    }

    /** YUV_420_888 → NV21 → JPEG (platform YuvImage encoder). */
    private fun yuvToJpeg(img: Image): ByteArray {
        val w = img.width; val h = img.height
        val nv21 = ByteArray(w * h * 3 / 2)
        val y = img.planes[0]; val u = img.planes[1]; val v = img.planes[2]
        var o = 0
        for (r in 0 until h) for (cx in 0 until w) nv21[o++] = y.buffer.get(r * y.rowStride + cx * y.pixelStride)
        for (r in 0 until h / 2) for (cx in 0 until w / 2) {
            nv21[o++] = v.buffer.get(r * v.rowStride + cx * v.pixelStride)
            nv21[o++] = u.buffer.get(r * u.rowStride + cx * u.pixelStride)
        }
        val bos = ByteArrayOutputStream()
        YuvImage(nv21, ImageFormat.NV21, w, h, null).compressToJpeg(Rect(0, 0, w, h), 90, bos)
        return bos.toByteArray()
    }

    /** 1×1 pbuffer GLES2 context + an external-OES texture: ARCore writes the camera image into it; nothing is drawn. */
    private class OffscreenEgl {
        val display: EGLDisplay = EGL14.eglGetDisplay(EGL14.EGL_DEFAULT_DISPLAY)
        val context: EGLContext
        val surface: EGLSurface
        val texture: Int

        init {
            val ver = IntArray(2)
            check(EGL14.eglInitialize(display, ver, 0, ver, 1)) { "eglInitialize failed" }
            val attrs = intArrayOf(EGL14.EGL_RENDERABLE_TYPE, EGL14.EGL_OPENGL_ES2_BIT, EGL14.EGL_SURFACE_TYPE, EGL14.EGL_PBUFFER_BIT,
                EGL14.EGL_RED_SIZE, 8, EGL14.EGL_GREEN_SIZE, 8, EGL14.EGL_BLUE_SIZE, 8, EGL14.EGL_NONE)
            val cfgs = arrayOfNulls<EGLConfig>(1); val n = IntArray(1)
            check(EGL14.eglChooseConfig(display, attrs, 0, cfgs, 0, 1, n, 0) && n[0] > 0) { "no EGL config" }
            context = EGL14.eglCreateContext(display, cfgs[0], EGL14.EGL_NO_CONTEXT, intArrayOf(EGL14.EGL_CONTEXT_CLIENT_VERSION, 2, EGL14.EGL_NONE), 0)
            surface = EGL14.eglCreatePbufferSurface(display, cfgs[0], intArrayOf(EGL14.EGL_WIDTH, 1, EGL14.EGL_HEIGHT, 1, EGL14.EGL_NONE), 0)
            check(EGL14.eglMakeCurrent(display, surface, surface, context)) { "eglMakeCurrent failed" }
            val t = IntArray(1)
            GLES20.glGenTextures(1, t, 0)
            GLES20.glBindTexture(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, t[0])
            GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_MIN_FILTER, GLES20.GL_LINEAR)
            GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_MAG_FILTER, GLES20.GL_LINEAR)
            texture = t[0]
        }

        fun release() {
            GLES20.glDeleteTextures(1, intArrayOf(texture), 0)
            EGL14.eglMakeCurrent(display, EGL14.EGL_NO_SURFACE, EGL14.EGL_NO_SURFACE, EGL14.EGL_NO_CONTEXT)
            EGL14.eglDestroySurface(display, surface); EGL14.eglDestroyContext(display, context); EGL14.eglTerminate(display)
        }
    }
}
