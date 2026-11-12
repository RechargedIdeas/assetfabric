package fabric.pocketloom

import android.content.ContentProvider
import android.content.ContentValues
import android.database.Cursor
import android.net.Uri
import android.os.ParcelFileDescriptor
import java.io.File

/** Minimal write-only target for ACTION_IMAGE_CAPTURE (no AndroidX FileProvider dependency).
 *  The camera app writes one JPEG into the app's cache; MainActivity ingests and deletes it. */
class CaptureProvider : ContentProvider() {
    companion object {
        const val AUTHORITY = "com.rechargedideas.pocketloom.capture"
        val URI: Uri = Uri.parse("content://$AUTHORITY/pending.jpg")
        fun pendingFile(ctx: android.content.Context) = File(ctx.cacheDir, "capture/pending.jpg")
    }

    override fun onCreate() = true

    override fun openFile(uri: Uri, mode: String): ParcelFileDescriptor {
        require(uri.lastPathSegment == "pending.jpg") { "unknown capture uri" }
        val f = pendingFile(context!!); f.parentFile?.mkdirs()
        return ParcelFileDescriptor.open(f, ParcelFileDescriptor.parseMode(mode))
    }

    override fun getType(uri: Uri) = "image/jpeg"
    override fun query(uri: Uri, p: Array<out String>?, s: String?, a: Array<out String>?, o: String?): Cursor? = null
    override fun insert(uri: Uri, values: ContentValues?): Uri? = null
    override fun delete(uri: Uri, s: String?, a: Array<out String>?) = 0
    override fun update(uri: Uri, v: ContentValues?, s: String?, a: Array<out String>?) = 0
}
