package fabric.pocketloom

import android.annotation.SuppressLint
import android.content.Context
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CameraMetadata
import android.hardware.camera2.CaptureRequest
import android.hardware.camera2.params.MeteringRectangle
import android.os.Handler
import android.os.HandlerThread
import android.view.Surface
import fabric.core.FocusRequest
import fabric.core.FocusSink

/** Camera focus control on the platform Camera2 API (no CameraX dependency — keeps the APK small and dependency-free).
 *  auto = continuous AF (+ optional metering point, AF trigger); manual = AF off + LENS_FOCUS_DISTANCE in diopters (needs the
 *  MANUAL_SENSOR capability, refused otherwise); lock / unlock = AF trigger start / cancel.
 *  Status: compiled, **not yet run on a phone** (`real_unverified_on_device`). The caller must hold the CAMERA permission. */
class Camera2Focus(context: Context, private val preview: Surface) : FocusSink {
    private val ctx: Context = context.applicationContext
    companion object { @SuppressLint("StaticFieldLeak") @Volatile var active: Camera2Focus? = null; private set }   // holds only the application context

    private val thread = HandlerThread("camera2-focus").apply { start() }
    private val handler = Handler(thread.looper)
    private var device: CameraDevice? = null
    private var session: CameraCaptureSession? = null
    private var builder: CaptureRequest.Builder? = null
    private lateinit var chars: CameraCharacteristics

    @SuppressLint("MissingPermission")   // MainActivity requests CAMERA before constructing this
    fun open(onReady: (Boolean) -> Unit) {
        val cm = ctx.getSystemService(CameraManager::class.java)
        val id = cm.cameraIdList.firstOrNull { cm.getCameraCharacteristics(it).get(CameraCharacteristics.LENS_FACING) == CameraMetadata.LENS_FACING_BACK }
            ?: cm.cameraIdList.firstOrNull() ?: return onReady(false)
        chars = cm.getCameraCharacteristics(id)
        cm.openCamera(id, object : CameraDevice.StateCallback() {
            override fun onOpened(d: CameraDevice) {
                device = d
                val b = d.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW).apply {
                    addTarget(preview); set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_PICTURE)
                }
                builder = b
                @Suppress("DEPRECATION")   // the SessionConfiguration overload needs API 28; minSdk is 26
                d.createCaptureSession(listOf(preview), object : CameraCaptureSession.StateCallback() {
                    override fun onConfigured(s: CameraCaptureSession) { session = s; s.setRepeatingRequest(b.build(), null, handler); active = this@Camera2Focus; onReady(true) }
                    override fun onConfigureFailed(s: CameraCaptureSession) { onReady(false) }
                }, handler)
            }
            override fun onDisconnected(d: CameraDevice) { close() }
            override fun onError(d: CameraDevice, error: Int) { close(); onReady(false) }
        }, handler)
    }

    private fun manualSupported(): Boolean =
        chars.get(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES)?.contains(CameraMetadata.REQUEST_AVAILABLE_CAPABILITIES_MANUAL_SENSOR) == true

    override fun apply(req: FocusRequest): Boolean {
        val b = builder ?: return false; val s = session ?: return false
        val area = chars.get(CameraCharacteristics.SENSOR_INFO_ACTIVE_ARRAY_SIZE)
        val region = area?.let { req.meteringRect(it.width(), it.height()) }
            ?.let { arrayOf(MeteringRectangle(it[0], it[1], it[2] - it[0], it[3] - it[1], MeteringRectangle.METERING_WEIGHT_MAX - 1)) }
        when (req.mode) {
            "manual" -> {
                if (!manualSupported()) return false
                val minD = chars.get(CameraCharacteristics.LENS_INFO_MINIMUM_FOCUS_DISTANCE) ?: return false
                b.set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_OFF)
                b.set(CaptureRequest.LENS_FOCUS_DISTANCE, req.diopters(minD))
            }
            "auto" -> {
                b.set(CaptureRequest.CONTROL_AF_MODE, if (region != null) CaptureRequest.CONTROL_AF_MODE_AUTO else CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_PICTURE)
                if (region != null) b.set(CaptureRequest.CONTROL_AF_REGIONS, region)
            }
            "lock", "unlock" -> {}
            else -> return false
        }
        s.setRepeatingRequest(b.build(), null, handler)
        val trigger = when { req.mode == "unlock" -> CaptureRequest.CONTROL_AF_TRIGGER_CANCEL; req.mode == "lock" || region != null -> CaptureRequest.CONTROL_AF_TRIGGER_START; else -> null }
        if (trigger != null) {
            val once = device!!.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW).apply {
                addTarget(preview); set(CaptureRequest.CONTROL_AF_MODE, b.get(CaptureRequest.CONTROL_AF_MODE)); set(CaptureRequest.CONTROL_AF_TRIGGER, trigger)
                region?.let { set(CaptureRequest.CONTROL_AF_REGIONS, it) }
            }
            s.capture(once.build(), null, handler)
        }
        return true
    }

    fun close() {
        if (active === this) active = null
        runCatching { session?.close() }; runCatching { device?.close() }
        session = null; device = null
        thread.quitSafely()
    }
}
