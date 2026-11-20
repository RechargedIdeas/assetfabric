package fabric.pocketloom

import android.annotation.SuppressLint
import android.content.Context
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CameraMetadata
import android.hardware.camera2.CaptureRequest
import android.media.MediaRecorder
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.util.Size
import java.io.File

/** LensForge video capture (C10) on the platform Camera2 API + MediaRecorder (the phone's hardware H.264 encoder) — no
 *  CameraX. Records [seconds] of back-camera video (≤ 1080p, 30 fps, no audio) into the app cache and hands the file to
 *  [onDone]; MainActivity then stores it via `PocketLoomCore.captureVideo` which queues `lens.video` for the desktop.
 *  Status: compiled, **not yet run on a phone** (`real_unverified_on_device`). The caller must hold the CAMERA permission. */
class Camera2Video(context: Context) {
    private val ctx: Context = context.applicationContext
    private val thread = HandlerThread("camera2-video").apply { start() }
    private val handler = Handler(thread.looper)
    private var device: CameraDevice? = null
    private var session: CameraCaptureSession? = null
    private var recorder: MediaRecorder? = null

    private fun pickSize(sizes: Array<Size>): Size =
        sizes.filter { it.width <= 1920 && it.height <= 1080 }.maxByOrNull { it.width.toLong() * it.height } ?: sizes.last()

    @SuppressLint("MissingPermission")   // MainActivity requests CAMERA first
    fun record(seconds: Int, onDone: (File?) -> Unit) {
        val cm = ctx.getSystemService(CameraManager::class.java)
        val id = cm.cameraIdList.firstOrNull { cm.getCameraCharacteristics(it).get(CameraCharacteristics.LENS_FACING) == CameraMetadata.LENS_FACING_BACK }
            ?: cm.cameraIdList.firstOrNull() ?: return finish(null, onDone)
        val chars = cm.getCameraCharacteristics(id)
        val map = chars.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP) ?: return finish(null, onDone)
        val size = pickSize(map.getOutputSizes(MediaRecorder::class.java) ?: return finish(null, onDone))
        val out = File(ctx.cacheDir, "clip-${System.currentTimeMillis()}.mp4")
        val rec = (if (Build.VERSION.SDK_INT >= 31) MediaRecorder(ctx) else @Suppress("DEPRECATION") MediaRecorder()).apply {
            setVideoSource(MediaRecorder.VideoSource.SURFACE)
            setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
            setOutputFile(out.absolutePath)
            setVideoEncoder(MediaRecorder.VideoEncoder.H264)
            setVideoEncodingBitRate(12_000_000)
            setVideoFrameRate(30)
            setVideoSize(size.width, size.height)
            setOrientationHint(chars.get(CameraCharacteristics.SENSOR_ORIENTATION) ?: 0)
            prepare()
        }
        recorder = rec
        cm.openCamera(id, object : CameraDevice.StateCallback() {
            override fun onOpened(d: CameraDevice) {
                device = d
                val req = d.createCaptureRequest(CameraDevice.TEMPLATE_RECORD).apply {
                    addTarget(rec.surface); set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_VIDEO)
                }
                @Suppress("DEPRECATION")   // the SessionConfiguration overload needs API 28; minSdk is 26
                d.createCaptureSession(listOf(rec.surface), object : CameraCaptureSession.StateCallback() {
                    override fun onConfigured(s: CameraCaptureSession) {
                        session = s
                        s.setRepeatingRequest(req.build(), null, handler)
                        rec.start()
                        handler.postDelayed({
                            val ok = runCatching { rec.stop() }.isSuccess
                            finish(if (ok && out.length() > 0) out else null, onDone)
                        }, seconds * 1000L)
                    }
                    override fun onConfigureFailed(s: CameraCaptureSession) { finish(null, onDone) }
                }, handler)
            }
            override fun onDisconnected(d: CameraDevice) { finish(null, onDone) }
            override fun onError(d: CameraDevice, error: Int) { finish(null, onDone) }
        }, handler)
    }

    private fun finish(file: File?, onDone: (File?) -> Unit) {
        runCatching { session?.close() }; runCatching { device?.close() }; runCatching { recorder?.release() }
        session = null; device = null; recorder = null
        thread.quitSafely()
        onDone(file)
    }
}
