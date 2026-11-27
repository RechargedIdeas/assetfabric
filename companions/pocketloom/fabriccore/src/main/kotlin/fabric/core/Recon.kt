package fabric.core

/** Cluster reconstruction path (C12) — SPEC §7. The phone's part is capture + offload (`recon.capture`, C4/C6); RealityLoom
 *  and SplatForge run on the desktop/cluster.
 *  REAL: [ReconRoute] (backdrop → splat, hero_prop → photogrammetry/MeshWeaver; same rule as `forge.realityloom.route`).
 *  STUB: [SplatForgeClient] — asking the cluster for a reconstruction refuses (`recon.splat_submit`); nothing is queued.
 *  Full-scale training itself runs on the desktop ROCm node (`forge recon train --stage splat`, real_unverified_on_gpu). */
object ReconRoute {
    const val MILESTONE = "C12"
    data class Route(val target: String, val route: String, val alternatives: List<String>)

    fun route(target: String): Route = when (target) {
        "backdrop" -> Route(target, "splat", emptyList())
        "hero_prop" -> Route(target, "photogrammetry", listOf("meshweaver"))
        else -> throw IllegalArgumentException("unknown reconstruction target $target")
    }
}

class SplatForgeClient {
    fun request(bundleSha256: String, target: String): Nothing = refuse("recon.splat_submit", ReconRoute.MILESTONE, "stub.recon.splat_submit")
}
