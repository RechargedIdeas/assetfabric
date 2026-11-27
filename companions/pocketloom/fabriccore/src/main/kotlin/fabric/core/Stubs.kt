package fabric.core

/** C9–C12 stubs: an interface that exists for a stable contract but has NO implementation behind it. Calling one throws this —
 *  it never returns made-up output. `reasonKey` is the locale/string key (`stub.recon.splat_submit` ⇄ Android string
 *  `stub_recon_splat_submit`; the Python twin is `forge.stubs.StubError`, register: content/companions/c9_c12.yaml). */
class StubException(val feature: String, val milestone: String, val reasonKey: String) :
    UnsupportedOperationException("[STUB $feature $milestone] $reasonKey") {
    fun toMap(): Map<String, Any?> = mapOf("stub" to true, "feature" to feature, "milestone" to milestone,
        "reason_key" to reasonKey, "message" to message)
}

internal fun refuse(feature: String, milestone: String, reasonKey: String): Nothing = throw StubException(feature, milestone, reasonKey)
