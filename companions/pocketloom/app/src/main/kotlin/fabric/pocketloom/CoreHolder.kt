package fabric.pocketloom

import android.content.Context
import fabric.core.PocketLoomCore

/** One FabricCore per process: the activity and the mirror / accessibility services share the same LoomLink client, so
 *  signed-request timestamps stay strictly increasing (the desktop refuses a replayed or stale timestamp). */
object CoreHolder {
    @Volatile private var core: PocketLoomCore? = null

    fun get(ctx: Context): PocketLoomCore = core ?: synchronized(this) {
        core ?: PocketLoomCore(ctx.applicationContext.filesDir.resolve("pocketloom")).also { core = it }
    }
}
