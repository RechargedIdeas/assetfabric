package fabric.pocketloom

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.graphics.Path
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.WindowManager
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import fabric.core.AndroidInputInjector
import fabric.core.FocusRequest
import fabric.core.InputSink
import fabric.core.Stroke
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledExecutorService
import java.util.concurrent.TimeUnit

/** MirrorWeave C9: desktop → phone remote control. Enabled by the user in system Accessibility settings (never silently).
 *  While enabled and paired with the `mirror` capability it polls the desktop for queued events; FabricCore verifies each
 *  event's HMAC (session key) before anything is performed. Gestures go through `dispatchGesture`, keys through global
 *  actions, text into the focused editable field. Status: compiled, **not yet run on a phone** (`real_unverified_on_device`). */
class MirrorAccessibilityService : AccessibilityService(), InputSink {
    private var poller: ScheduledExecutorService? = null
    private val main = Handler(Looper.getMainLooper())

    override fun onServiceConnected() {
        super.onServiceConnected()
        val core = CoreHolder.get(this)
        val inj = AndroidInputInjector(core.link, this)
        poller = Executors.newSingleThreadScheduledExecutor().also {
            it.scheduleWithFixedDelay({
                if (core.link.has("mirror")) runCatching { inj.pollOnce() }.onFailure { e -> core.telemetry.record("mirror_input_error", mapOf("error" to e.toString())) }
            }, 500, 250, TimeUnit.MILLISECONDS)
        }
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {}
    override fun onInterrupt() {}

    override fun onDestroy() { poller?.shutdownNow(); super.onDestroy() }

    override fun screenSize(): Pair<Int, Int> {
        val wm = getSystemService(WindowManager::class.java)
        return if (Build.VERSION.SDK_INT >= 30) wm.currentWindowMetrics.bounds.let { it.width() to it.height() }
        else resources.displayMetrics.let { it.widthPixels to it.heightPixels }
    }

    override fun gesture(strokes: List<Stroke>): Boolean {
        if (strokes.isEmpty()) return false
        val b = GestureDescription.Builder()
        for (s in strokes) {
            val p = Path(); p.moveTo(s.points[0].first, s.points[0].second)
            s.points.drop(1).forEach { p.lineTo(it.first, it.second) }
            b.addStroke(GestureDescription.StrokeDescription(p, s.startMs, s.durationMs))
        }
        val done = CountDownLatch(1); var ok = false
        main.post { ok = dispatchGesture(b.build(), null, null); done.countDown() }
        done.await(2, TimeUnit.SECONDS)
        return ok
    }

    override fun globalAction(key: String): Boolean {
        val action = when (key) {
            "back" -> GLOBAL_ACTION_BACK; "home" -> GLOBAL_ACTION_HOME; "recents" -> GLOBAL_ACTION_RECENTS
            "notifications" -> GLOBAL_ACTION_NOTIFICATIONS; "quick_settings" -> GLOBAL_ACTION_QUICK_SETTINGS
            else -> return false
        }
        return performGlobalAction(action)
    }

    override fun typeText(text: String): Boolean {
        val node = rootInActiveWindow?.findFocus(AccessibilityNodeInfo.FOCUS_INPUT) ?: return false
        val args = Bundle().apply { putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text) }
        return node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)
    }

    /** Focus applies to the live camera when PocketLoom's camera screen has it open; otherwise there is nothing to focus. */
    override fun focus(req: FocusRequest): Boolean = Camera2Focus.active?.apply(req) ?: false
}
