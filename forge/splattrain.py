"""SplatForge CPU rung (C12): a small, real 3D Gaussian Splatting trainer in NumPy — no GPU, no new dependency.

What it is (and is not):
* Gaussians are **isotropic** (one world σ each), colour is SH degree 0, rasterisation is **dense** (every Gaussian ×
  every pixel, depth-sorted front-to-back alpha compositing exactly as in 3DGS, α clamped at 0.99). Gradients are analytic
  (the 3DGS backward pass specialised to isotropic splats), the optimiser is Adam, with opacity pruning.
* It trains the same `.ply` the rest of the pipeline reads (`forge.splats.write_ply`), from posed views — ground-truth
  poses or the CPU SfM output (`forge.photogrammetry`) — and an optional sparse point cloud for initialisation.
* Dense rasterisation is O(N·P): it is meant for **tiny scenes** (≤ ~2k splats, ≤ ~100×75 px views) — a working CPU
  fallback and a correctness reference, not a substitute for tile-based GPU training. Anisotropic covariance, higher-order
  SH, adaptive densification and full-resolution training stay the `opensplat-rocm` rung (`planned`). See INFERENCES C-77.
"""
from __future__ import annotations

import math
import time
from typing import Any

import numpy as np

ALPHA_MAX = 0.99
NEAR = 0.05


def _mm(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Matrix product without BLAS (einsum C loop): bit-identical whatever the BLAS thread count (GroundWeave digests)."""
    return np.einsum("ij,jk->ik", a, b, optimize=False)


def _sig(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def render(mu: np.ndarray, log_s: np.ndarray, logit_o: np.ndarray, rgb: np.ndarray, R: np.ndarray, t: np.ndarray,
           K: np.ndarray, w: int, h: int, bg: np.ndarray | None = None, need_grad: bool = False) -> dict[str, Any]:
    """Rasterise isotropic Gaussians into a (h, w, 3) image. With `need_grad`, keeps what `backward` needs."""
    bg = np.zeros(3) if bg is None else np.asarray(bg, float)
    pc = _mm(mu, R.T) + t
    z = pc[:, 2]
    vis = np.where(z > NEAR)[0]
    vis = vis[np.argsort(z[vis], kind="stable")]
    fx, fy, cx, cy = K[0, 0], K[1, 1], K[0, 2], K[1, 2]
    zv = z[vis]
    u = fx * pc[vis, 0] / zv + cx
    v = fy * pc[vis, 1] / zv + cy
    s2 = fx * np.exp(log_s[vis]) / zv
    op = _sig(logit_o[vis])
    ys, xs = np.mgrid[0:h, 0:w]
    qx = (xs.ravel() + 0.5)[None, :]
    qy = (ys.ravel() + 0.5)[None, :]
    dx = qx - u[:, None]
    dy = qy - v[:, None]
    d2 = dx * dx + dy * dy
    g = np.exp(-d2 / (2 * s2[:, None] ** 2))
    a_raw = op[:, None] * g
    a = np.minimum(a_raw, ALPHA_MAX)
    one_m = 1.0 - a
    T = np.ones_like(a)
    if len(a) > 1:
        T[1:] = np.cumprod(one_m[:-1], axis=0)
    t_final = T[-1] * one_m[-1] if len(a) else np.ones(h * w)
    wgt = a * T                                                       # (N, P) contribution weights
    col = _mm(wgt.T, rgb[vis]) + t_final[:, None] * bg[None, :]
    out: dict[str, Any] = {"image": col.reshape(h, w, 3), "visible": len(vis)}
    if need_grad:
        out.update(vis=vis, pc=pc[vis], u=u, v=v, s2=s2, op=op, dx=dx, dy=dy, d2=d2, g=g, a=a, clamp=a_raw >= ALPHA_MAX,
                   T=T, wgt=wgt, t_final=t_final, col=col, bg=bg, fx=fx, fy=fy)
    return out


def backward(fw: dict[str, Any], dcol: np.ndarray, rgb: np.ndarray, R: np.ndarray, n: int) -> dict[str, np.ndarray]:
    """dL/d(params) given dL/d(image) `dcol` (P×3). Isotropic specialisation of the 3DGS backward pass."""
    vis = fw["vis"]
    grads = {k: np.zeros(s) for k, s in (("mu", (n, 3)), ("log_s", n), ("logit_o", n), ("rgb", (n, 3)))}
    if not len(vis):
        return grads
    c = rgb[vis]
    a, T, wgt = fw["a"], fw["T"], fw["wgt"]
    grads["rgb"][vis] = _mm(wgt, dcol)
    # S_i = Σ_{k>i} c_k w_k + T_final·bg = C − Σ_{k≤i} c_k w_k  (per channel)
    G_c = _mm(dcol, c.T)                                                  # (P, N): Σ_ch dC·c_i
    contrib = wgt * G_c.T                                              # (N, P): Σ_ch dC·c_i·w_i
    cum = np.cumsum(contrib, axis=0)
    total = (dcol * fw["col"]).sum(1)[None, :]                         # Σ_ch dC·C
    S_dot = total - cum
    d_a = G_c.T * T - S_dot / (1.0 - a)
    d_a[fw["clamp"]] = 0.0
    op, g, s2 = fw["op"], fw["g"], fw["s2"]
    grads["logit_o"][vis] = (d_a * g).sum(1) * op * (1 - op)
    H = d_a * op[:, None] * g                                          # dL/dg · g
    inv = 1.0 / s2 ** 2
    d_u = (H * fw["dx"]).sum(1) * inv
    d_v = (H * fw["dy"]).sum(1) * inv
    d_s2 = (H * fw["d2"]).sum(1) / s2 ** 3
    x, y, z = fw["pc"][:, 0], fw["pc"][:, 1], fw["pc"][:, 2]
    fx, fy = fw["fx"], fw["fy"]
    d_pc = np.stack([d_u * fx / z, d_v * fy / z,
                     -d_u * fx * x / z ** 2 - d_v * fy * y / z ** 2 - d_s2 * s2 / z], 1)
    grads["mu"][vis] = _mm(d_pc, R)
    grads["log_s"][vis] = d_s2 * s2
    return grads


def psnr(a: np.ndarray, b: np.ndarray) -> float:
    mse = float(np.mean((np.asarray(a, float) - np.asarray(b, float)) ** 2))
    return float("inf") if mse <= 0 else 10 * math.log10(1.0 / mse)


def init_gaussians(n: int, lo: np.ndarray, hi: np.ndarray, sigma: float, seed: int = 0,
                   points: np.ndarray | None = None, colors: np.ndarray | None = None) -> dict[str, np.ndarray]:
    """Init from a sparse point cloud (SfM) when given (topped up with uniform samples), else uniform in [lo, hi]."""
    rng = np.random.default_rng(seed)
    if points is not None and len(points):
        k = min(n, len(points))
        idx = rng.choice(len(points), k, replace=False)
        mu = np.asarray(points, float)[idx]
        rgb = np.asarray(colors, float)[idx] if colors is not None else np.full((k, 3), 0.5)
        if k < n:
            mu = np.vstack([mu, rng.uniform(lo, hi, size=(n - k, 3))])
            rgb = np.vstack([rgb, np.full((n - k, 3), 0.5)])
    else:
        mu = rng.uniform(lo, hi, size=(n, 3))
        rgb = np.full((n, 3), 0.5)
    return {"mu": mu, "log_s": np.full(n, math.log(sigma)), "logit_o": np.full(n, -1.0), "rgb": rgb}


def train(views: list[dict[str, Any]], K: np.ndarray, params: dict[str, np.ndarray], iters: int = 300, seed: int = 0,
          lr: dict[str, float] | None = None, prune_every: int = 100, prune_opacity: float = 0.02,
          bg: np.ndarray | None = None, time_budget_s: float | None = None) -> dict[str, Any]:
    """Adam on photometric L2 over posed views [{image (h,w,3) float 0..1, R, t}]. Returns params + loss curve."""
    lr = {"mu": 0.01, "log_s": 0.02, "logit_o": 0.05, "rgb": 0.03, **(lr or {})}
    p = {k: np.array(v, dtype=np.float64) for k, v in params.items()}
    m = {k: np.zeros_like(v) for k, v in p.items()}
    s = {k: np.zeros_like(v) for k, v in p.items()}
    b1, b2, eps = 0.9, 0.999, 1e-8
    rng = np.random.default_rng(seed)
    h, w = views[0]["image"].shape[:2]
    curve: list[float] = []
    t0 = time.perf_counter()
    step = 0
    for step in range(1, iters + 1):
        vw = views[int(rng.integers(len(views)))]
        fw = render(p["mu"], p["log_s"], p["logit_o"], p["rgb"], vw["R"], vw["t"], K, w, h, bg, need_grad=True)
        diff = fw["col"] - vw["image"].reshape(-1, 3)
        curve.append(float(np.mean(diff ** 2)))
        gr = backward(fw, 2 * diff / diff.size, p["rgb"], vw["R"], len(p["mu"]))
        for k in p:
            m[k] = b1 * m[k] + (1 - b1) * gr[k]
            s[k] = b2 * s[k] + (1 - b2) * gr[k] ** 2
            p[k] -= lr[k] * (m[k] / (1 - b1 ** step)) / (np.sqrt(s[k] / (1 - b2 ** step)) + eps)
        p["rgb"] = np.clip(p["rgb"], 0.0, 1.0)
        p["log_s"] = np.clip(p["log_s"], math.log(1e-3), math.log(1.0))
        if prune_every and step % prune_every == 0 and step < iters:
            keep = _sig(p["logit_o"]) > prune_opacity
            if keep.sum() >= 8 and not keep.all():
                p = {k: v[keep] for k, v in p.items()}
                m = {k: v[keep] for k, v in m.items()}
                s = {k: v[keep] for k, v in s.items()}
        if time_budget_s and time.perf_counter() - t0 > time_budget_s:
            break
    return {"params": p, "curve": curve, "iters": step, "seconds": round(time.perf_counter() - t0, 3)}


def render_params(p: dict[str, np.ndarray], R: np.ndarray, t: np.ndarray, K: np.ndarray, w: int, h: int,
                  bg: np.ndarray | None = None) -> np.ndarray:
    return render(p["mu"], p["log_s"], p["logit_o"], p["rgb"], R, t, K, w, h, bg)["image"]


def to_ply(p: dict[str, np.ndarray]) -> bytes:
    from forge.splats import write_ply
    sc = np.exp(p["log_s"])
    return write_ply(p["mu"], np.clip(p["rgb"], 0, 1), _sig(p["logit_o"]), np.stack([sc, sc, sc], 1))


def demo_scene(n_views: int = 9, w: int = 64, h: int = 48, holdout: int | None = None) -> dict[str, Any]:
    """The synthetic textured-box capture (`photogrammetry.render_views`) at training resolution, one view held out."""
    from forge.photogrammetry import render_views
    sc = render_views(n=n_views, w=w, h=h)
    ho = n_views // 2 if holdout is None else holdout
    views = [{"image": im.astype(np.float64) / 255.0, "R": ps["R"], "t": ps["t"]} for im, ps in zip(sc["images"], sc["poses"])]
    return {"train": [v for i, v in enumerate(views) if i != ho], "test": views[ho], "K": sc["K"], "w": w, "h": h}


def proof(n: int = 600, iters: int = 400, w: int = 64, h: int = 48, seed: int = 0) -> dict[str, Any]:
    """Tiny-scene proof: train on 8 posed views of the synthetic box, evaluate PSNR on the held-out middle view."""
    sc = demo_scene(9, w, h)
    p0 = init_gaussians(n, np.array([-2.5, 0.0, -2.5]), np.array([2.5, 1.2, 2.5]), 0.08, seed)
    base = psnr(render_params(p0, sc["test"]["R"], sc["test"]["t"], sc["K"], w, h), sc["test"]["image"])
    flat = psnr(np.broadcast_to(np.mean([v["image"].reshape(-1, 3).mean(0) for v in sc["train"]], 0), sc["test"]["image"].shape),
                sc["test"]["image"])
    r = train(sc["train"], sc["K"], p0, iters=iters, seed=seed)
    img = render_params(r["params"], sc["test"]["R"], sc["test"]["t"], sc["K"], w, h)
    train_psnr = float(np.mean([psnr(render_params(r["params"], v["R"], v["t"], sc["K"], w, h), v["image"]) for v in sc["train"]]))
    return {"splats_init": n, "splats_final": int(len(r["params"]["mu"])), "iters": r["iters"], "seconds": r["seconds"],
            "resolution": [w, h], "views_train": len(sc["train"]), "psnr_test_init": round(base, 3),
            "psnr_test_flat_mean": round(flat, 3), "psnr_test": round(psnr(img, sc["test"]["image"]), 3),
            "psnr_train": round(train_psnr, 3), "loss_first": round(float(np.mean(r["curve"][:10])), 6),
            "loss_last": round(float(np.mean(r["curve"][-10:])), 6), "params": r["params"], "test_render": img,
            "test_gt": sc["test"]["image"]}


def _resize(img: np.ndarray, w: int, h: int) -> np.ndarray:
    from PIL import Image
    return np.asarray(Image.fromarray(np.asarray(img, np.uint8)).resize((w, h), Image.BILINEAR), np.float64) / 255.0


def from_sfm(images: list[np.ndarray], rec: dict[str, Any], w: int = 64, holdout: int | None = None) -> dict[str, Any]:
    """Posed training views from a CPU SfM reconstruction (`photogrammetry.reconstruct`), downscaled to width `w`."""
    H, W = np.asarray(images[0]).shape[:2]
    h = max(8, round(w * H / W))
    sx, sy = w / W, h / H
    K = np.array(rec["K"], float).copy()
    K[0] *= sx
    K[1] *= sy
    views = []
    for i, pose in enumerate(rec["poses"]):
        if pose is not None:
            views.append({"view": i, "image": _resize(images[i], w, h), "R": np.asarray(pose[0], float), "t": np.asarray(pose[1], float)})
    test = next((v for v in views if v["view"] == holdout), None)
    return {"train": [v for v in views if v is not test], "test": test, "K": K, "w": w, "h": h}


def scene_bounds(points: np.ndarray, centers: np.ndarray, q: float = 0.05) -> tuple[np.ndarray, np.ndarray, float]:
    """Robust init box from the sparse cloud (quantiles) + a σ₀ proportional to the scene size."""
    lo = np.quantile(points, q, axis=0)
    hi = np.quantile(points, 1 - q, axis=0)
    size = float(np.linalg.norm(hi - lo))
    return lo, hi, 0.03 * size
