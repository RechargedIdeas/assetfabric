package fabric.pocketloom

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaFormat
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import fabric.core.LinkException
import fabric.core.MirrorClient
import fabric.core.ScreenCaptureSource
import fabric.core.Still
import fabric.core.VideoPacket
import fabric.core.VideoStreamSource
import java.io.ByteArrayOutputStream
import java.util.concurrent.Executors

/** MirrorWeave C9: Android screen → paired desktop. MediaProjection (user consent dialog, started by [MainActivity]) feeds a
 *  VirtualDisplay; mode `stills` reads frames through an ImageReader and pushes JPEG stills (FabricCore [ScreenCaptureSource]),
 *  mode `h264` renders into a MediaCodec hardware H.264 encoder and pushes its packets ([VideoStreamSource]).
 *  Status: compiled into the APK, **not yet run on a phone** (register: `real_unverified_on_device`). */
class ScreenMirrorService : Service() {
    companion object {
        const val ACTION_START = "fabric.pocketloom.mirror.START"
        const val ACTION_STOP = "fabric.pocketloom.mirror.STOP"
        const val EXTRA_RESULT_CODE = "result_code"
        const val EXTRA_DATA = "data"
        const val EXTRA_MODE = "mode"        // "stills" | "h264"
        private const val CHANNEL = "mirror"
        private const val NOTIF_ID = 9
        private const val MAX_EDGE = 720
        @Volatile var running = false
            private set
        @Volatile var lastError: String? = null
            private set
        @Volatile var framesSent = 0
            private set
    }

    private var projection: MediaProjection? = null
    private var display: VirtualDisplay? = null
    private var reader: ImageReader? = null
    private var encoder: MediaCodec? = null
    private val worker = Executors.newSingleThreadExecutor()

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP || intent == null) { stopSelf(); return START_NOT_STICKY }
        startInForeground()
        val data: Intent? = if (Build.VERSION.SDK_INT >= 33) intent.getParcelableExtra(EXTRA_DATA, Intent::class.java)
            else @Suppress("DEPRECATION") intent.getParcelableExtra(EXTRA_DATA)
        val mpm = getSystemService(MediaProjectionManager::class.java)
        val mp = data?.let { mpm.getMediaProjection(intent.getIntExtra(EXTRA_RESULT_CODE, 0), it) }
        if (mp == null) { lastError = getString(R.string.mirror_no_consent); stopSelf(); return START_NOT_STICKY }
        mp.registerCallback(object : MediaProjection.Callback() { override fun onStop() { stopSelf() } }, Handler(Looper.getMainLooper()))
        projection = mp
        val dm = resources.displayMetrics
        val scale = minOf(1.0, MAX_EDGE.toDouble() / maxOf(dm.widthPixels, dm.heightPixels))
        val w = ((dm.widthPixels * scale).toInt() / 2) * 2
        val h = ((dm.heightPixels * scale).toInt() / 2) * 2
        running = true; framesSent = 0; lastError = null
        if (intent.getStringExtra(EXTRA_MODE) == "h264") startH264(mp, w, h, dm.densityDpi) else startStills(mp, w, h, dm.densityDpi)
        return START_NOT_STICKY
    }

    private fun startInForeground() {
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CHANNEL, getString(R.string.mirror_channel), NotificationManager.IMPORTANCE_LOW))
        val n = Notification.Builder(this, CHANNEL).setSmallIcon(R.drawable.ic_launcher)
            .setContentTitle(getString(R.string.mirror_notif_title)).setContentText(getString(R.string.mirror_notif_text)).build()
        if (Build.VERSION.SDK_INT >= 29) startForeground(NOTIF_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION)
        else startForeground(NOTIF_ID, n)
    }

    private fun startStills(mp: MediaProjection, w: Int, h: Int, dpi: Int) {
        val r = ImageReader.newInstance(w, h, PixelFormat.RGBA_8888, 2)
        reader = r
        display = mp.createVirtualDisplay("pocketloom-mirror", w, h, dpi, DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR, r.surface, null, null)
        val client = MirrorClient(CoreHolder.get(this).link)
        worker.execute {
            val src = ScreenCaptureSource("screen", { grab(r, w, h) }, fps = 5, running = { running })
            pushAll { src.frames().forEach { client.pushFrame(it); framesSent++ } }
        }
    }

    private fun grab(r: ImageReader, w: Int, h: Int): Still? {
        val img = r.acquireLatestImage() ?: return null
        try {
            val plane = img.planes[0]
            val rowPx = plane.rowStride / plane.pixelStride
            val bmp = Bitmap.createBitmap(rowPx, h, Bitmap.Config.ARGB_8888)
            bmp.copyPixelsFromBuffer(plane.buffer)
            val crop = if (rowPx != w) Bitmap.createBitmap(bmp, 0, 0, w, h) else bmp
            val out = ByteArrayOutputStream()
            crop.compress(Bitmap.CompressFormat.JPEG, 70, out)
            return Still(out.toByteArray(), "jpeg", w, h)
        } finally { img.close() }
    }

    private fun startH264(mp: MediaProjection, w: Int, h: Int, dpi: Int) {
        val fmt = MediaFormat.createVideoFormat(MediaFormat.MIMETYPE_VIDEO_AVC, w, h).apply {
            setInteger(MediaFormat.KEY_COLOR_FORMAT, MediaCodecInfo.CodecCapabilities.COLOR_FormatSurface)
            setInteger(MediaFormat.KEY_BIT_RATE, 2_000_000)
            setInteger(MediaFormat.KEY_FRAME_RATE, 30)
            setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, 2)
        }
        val enc = MediaCodec.createEncoderByType(MediaFormat.MIMETYPE_VIDEO_AVC)
        enc.configure(fmt, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
        val surface = enc.createInputSurface()
        enc.start()
        encoder = enc
        display = mp.createVirtualDisplay("pocketloom-mirror", w, h, dpi, DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR, surface, null, null)
        val client = MirrorClient(CoreHolder.get(this).link)
        worker.execute {
            val packets = sequence {
                val info = MediaCodec.BufferInfo()
                while (running) {
                    val idx = enc.dequeueOutputBuffer(info, 10_000)
                    if (idx < 0) continue
                    val buf = enc.getOutputBuffer(idx)
                    if (buf != null && info.size > 0) {
                        val b = ByteArray(info.size); buf.position(info.offset); buf.get(b)
                        yield(VideoPacket(b, config = info.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG != 0,
                            key = info.flags and MediaCodec.BUFFER_FLAG_KEY_FRAME != 0, ptsUs = info.presentationTimeUs))
                    }
                    enc.releaseOutputBuffer(idx, false)
                    if (info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0) break
                }
            }
            pushAll { VideoStreamSource("screen-video", packets, "h264", w, h).frames().forEach { client.pushFrame(it); framesSent++ } }
        }
    }

    private fun pushAll(body: () -> Unit) {
        try { body() } catch (e: LinkException) { lastError = e.message } catch (e: RuntimeException) { lastError = e.toString() }
        finally { Handler(Looper.getMainLooper()).post { stopSelf() } }
    }

    override fun onDestroy() {
        running = false
        runCatching { display?.release() }
        runCatching { encoder?.stop(); encoder?.release() }
        runCatching { reader?.close() }
        runCatching { projection?.stop() }
        worker.shutdownNow()
        super.onDestroy()
    }
}

fun mirrorIntent(ctx: Context, resultCode: Int, data: Intent, mode: String) =
    Intent(ctx, ScreenMirrorService::class.java).setAction(ScreenMirrorService.ACTION_START)
        .putExtra(ScreenMirrorService.EXTRA_RESULT_CODE, resultCode).putExtra(ScreenMirrorService.EXTRA_DATA, data)
        .putExtra(ScreenMirrorService.EXTRA_MODE, mode)
