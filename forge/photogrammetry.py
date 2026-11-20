"""CPU photogrammetry (C12 `recon.photogrammetry`) — incremental structure-from-motion on OpenCV (Apache-2.0).

SPEC §7 "Photogrammetry (COLMAP/Meshroom)" + AMD honesty "CPU COLMAP". COLMAP itself is not bundled (its wheels pull
SuiteSparse/CHOLMOD components under LGPL/GPL); this is a compact incremental SfM in the same shape:

1. SIFT features (OpenCV, patent expired) + ratio-test matching between every view pair;
2. initial pair = the pair with the most essential-matrix inliers; relative pose (RANSAC 5-point) + triangulation;
3. each further view: 2D–3D correspondences through feature tracks → PnP-RANSAC → refine (LM) → triangulate new tracks;
4. outputs: camera poses (world→camera R, t), intrinsics, sparse coloured point cloud (`.ply`, ASCII), per-view
   reprojection RMSE. No bundle adjustment (drift grows with the number of views; noted in INFERENCES C-74).

Scale is unknown (monocular): evaluation aligns to ground truth with a similarity transform (Umeyama).
`render_views` makes the acceptance input: a textured box on a textured ground plane, ray-cast from known poses
(NumPy) — real images with exact ground-truth cameras, not real-world photos."""
from __future__ import annotations

import io
import math
from pathlib import Path
from typing import Any

import numpy as np


def _cv2():  # noqa: ANN202
    try:
        import cv2
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("photogrammetry needs opencv-python-headless (install forge with the 'recon' extra)") from e
    return cv2


# --------------------------------------------------------------------------------------------- synthetic scene

def _texture(u: np.ndarray, v: np.ndarray, seed: int) -> np.ndarray:
    """Deterministic high-contrast colour texture on [0,1]²: sharp random-colour cells at two scales over smooth noise
    (corners/blobs for SIFT at several scales)."""
    rng = np.random.default_rng(seed)
    uu, vv = np.clip(u, 0, 1 - 1e-9), np.clip(v, 0, 1 - 1e-9)
    out = np.zeros(u.shape + (3,))
    for n, wgt in ((10, 0.55), (30, 0.30)):
        cells = rng.random((n, n, 3))
        out += wgt * cells[(uu * n).astype(int), (vv * n).astype(int)]
    grid = rng.random((7, 7, 3))
    x, y = uu * 6, vv * 6
    i, j = x.astype(int), y.astype(int)
    fx, fy = (x - i)[..., None], (y - j)[..., None]
    out += 0.15 * (grid[i, j] * (1 - fx) * (1 - fy) + grid[i + 1, j] * fx * (1 - fy) + grid[i, j + 1] * (1 - fx) * fy
                   + grid[i + 1, j + 1] * fx * fy)
    return np.clip(out, 0, 1)


def look_at(eye: np.ndarray, target: np.ndarray, up: np.ndarray = np.array([0.0, 1.0, 0.0])) -> tuple[np.ndarray, np.ndarray]:
    """World→camera (R, t) for an OpenCV camera (x right, y down, z forward)."""
    z = target - eye
    z = z / np.linalg.norm(z)
    x = np.cross(z, up)
    x = x / np.linalg.norm(x)
    y = np.cross(z, x)
    R = np.stack([x, y, z])
    return R, -R @ eye


def render_views(n: int = 8, w: int = 320, h: int = 240, radius: float = 3.0, height: float = 1.4,
                 arc_deg: float = 120.0) -> dict[str, Any]:
    """Ray-cast a textured unit box (centre (0,0.5,0)) on a textured ground plane y=0 from `n` cameras on an arc."""
    f = 1.1 * w
    K = np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1.0]])
    ss = 2                                                           # 2×2 supersampling (anti-aliasing)
    Ks = np.array([[f * ss, 0, w * ss / 2], [0, f * ss, h * ss / 2], [0, 0, 1.0]])
    planes = [  # (axis, value, normal sign, (u-axis, v-axis), bounds for the box faces) — box [-0.5,0.5]×[0,1]×[-0.5,0.5]
        (0, 0.5, (2, 1)), (0, -0.5, (2, 1)), (2, 0.5, (0, 1)), (2, -0.5, (0, 1)), (1, 1.0, (0, 2))]
    images, poses = [], []
    ys, xs = np.mgrid[0:h * ss, 0:w * ss]
    pix = np.stack([xs + 0.5, ys + 0.5, np.ones_like(xs, dtype=float)], -1).reshape(-1, 3)
    for k in range(n):
        a = math.radians(-arc_deg / 2 + arc_deg * k / max(1, n - 1))
        eye = np.array([radius * math.sin(a), height, radius * math.cos(a)])
        R, t = look_at(eye, np.array([0.0, 0.4, 0.0]))
        d = (R.T @ (np.linalg.inv(Ks) @ pix.T)).T
        best = np.full(len(d), np.inf)
        col = np.zeros((len(d), 3))
        with np.errstate(divide="ignore", invalid="ignore"):
            tg = -eye[1] / d[:, 1]                                       # ground y = 0
            p = eye + tg[:, None] * d
            m = (tg > 0) & (np.abs(p[:, 0]) < 4) & (np.abs(p[:, 2]) < 4)
            best[m] = tg[m]
            col[m] = _texture((p[m, 0] + 4) / 8, (p[m, 2] + 4) / 8, 1) * 0.8
            for fi, (ax, val, (ua, va)) in enumerate(planes):
                tt = (val - eye[ax]) / d[:, ax]
                q = eye + tt[:, None] * d
                inb = (np.abs(q[:, 0]) <= 0.5 + 1e-9) & (q[:, 1] >= -1e-9) & (q[:, 1] <= 1 + 1e-9) & (np.abs(q[:, 2]) <= 0.5 + 1e-9)
                mm = (tt > 0) & inb & (tt < best)
                best[mm] = tt[mm]
                uu = q[mm, ua] + (0.5 if ua != 1 else 0.0)
                vv = q[mm, va] + (0.5 if va != 1 else 0.0)
                col[mm] = _texture(uu, vv, 10 + fi)
        img = (np.clip(col, 0, 1) * 255).reshape(h, ss, w, ss, 3).mean((1, 3)).round().astype(np.uint8)
        images.append(img)
        poses.append({"R": R, "t": t, "center": eye})
    return {"images": images, "poses": poses, "K": K}


def png_bytes(rgb: np.ndarray) -> bytes:
    from PIL import Image
    b = io.BytesIO()
    Image.fromarray(rgb).save(b, "PNG")
    return b.getvalue()


# --------------------------------------------------------------------------------------------- SfM

def _decode(img: bytes | np.ndarray) -> np.ndarray:
    if isinstance(img, np.ndarray):
        return img
    cv2 = _cv2()
    a = cv2.imdecode(np.frombuffer(img, np.uint8), cv2.IMREAD_COLOR)
    if a is None:
        raise ValueError("unreadable image")
    return a[:, :, ::-1]


def reconstruct(images: list[bytes | np.ndarray], focal_px: float | None = None, ratio: float = 0.75,
                min_matches: int = 25, seed: int = 0, refine_iters: int = 3) -> dict[str, Any]:
    """Incremental SfM. Returns poses for registered views (None for unregistered), intrinsics K, points (N×3), colours."""
    cv2 = _cv2()
    cv2.setRNGSeed(seed)
    cv2.setNumThreads(1)                                             # deterministic bytes on any core count
    rgb = [_decode(im) for im in images]
    if len(rgb) < 2:
        raise ValueError("photogrammetry needs at least 2 views")
    h, w = rgb[0].shape[:2]
    f = focal_px or 1.2 * max(w, h)
    K = np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1.0]])
    sift = cv2.SIFT_create(nfeatures=4000)
    kps, des = [], []
    for im in rgb:
        k, d = sift.detectAndCompute(cv2.cvtColor(im, cv2.COLOR_RGB2GRAY), None)
        kps.append(np.array([p.pt for p in k], dtype=np.float64))
        des.append(d)
    bf = cv2.BFMatcher(cv2.NORM_L2)
    n = len(rgb)
    matches: dict[tuple[int, int], np.ndarray] = {}
    for i in range(n):
        for j in range(i + 1, n):
            if des[i] is None or des[j] is None:
                continue
            good = [(m.queryIdx, m.trainIdx) for m, nn in bf.knnMatch(des[i], des[j], k=2) if m.distance < ratio * nn.distance]
            if len(good) >= min_matches:
                g = np.array(good)
                _, mask = cv2.findFundamentalMat(kps[i][g[:, 0]], kps[j][g[:, 1]], cv2.FM_RANSAC, 1.0, 0.999)
                if mask is not None and mask.sum() >= min_matches:
                    matches[(i, j)] = g[mask.ravel() > 0]
    if not matches:
        raise ValueError("no view pair has enough matches")
    # tracks: union-find over (view, keypoint)
    parent: dict[tuple[int, int], tuple[int, int]] = {}

    def find(a: tuple[int, int]) -> tuple[int, int]:
        while parent.setdefault(a, a) != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for (i, j), g in matches.items():
        for a, b in g:
            ra, rb = find((i, int(a))), find((j, int(b)))
            if ra != rb:
                parent[rb] = ra
    track_of: dict[tuple[int, int], tuple[int, int]] = {k: find(k) for k in list(parent)}
    views_in: dict[tuple[int, int], list[int]] = {}
    for (v, _), tk in track_of.items():
        views_in.setdefault(tk, []).append(v)
    bad = {tk for tk, vs in views_in.items() if len(vs) != len(set(vs))}    # inconsistent: two keypoints of one view
    track_of = {k: tk for k, tk in track_of.items() if tk not in bad}
    # initial pair: most essential inliers with enough baseline
    best = None
    for (i, j), g in sorted(matches.items(), key=lambda kv: -len(kv[1])):
        cv2.setRNGSeed(seed)
        E, mask = cv2.findEssentialMat(kps[i][g[:, 0]], kps[j][g[:, 1]], K, cv2.USAC_ACCURATE, 0.9999, 0.5)
        if E is None:
            continue
        _, R, t, mp = cv2.recoverPose(E[:3], kps[i][g[:, 0]], kps[j][g[:, 1]], K, mask=mask)
        inl = int((mp.ravel() > 0).sum())
        ang = math.degrees(math.acos(max(-1.0, min(1.0, (np.trace(R) - 1) / 2))))
        score = inl * min(1.0, ang / 15.0)               # prefer a wide baseline: tiny-angle pairs triangulate badly
        if best is None or score > best[0]:
            best = (score, i, j, R, t.ravel(), g[mp.ravel() > 0])
    if best is None:
        raise ValueError("no initial pair")
    _, i0, j0, R1, t1, g0 = best
    poses: dict[int, tuple[np.ndarray, np.ndarray]] = {i0: (np.eye(3), np.zeros(3)), j0: (R1, t1)}
    points: dict[tuple[int, int], np.ndarray] = {}

    def P(v: int) -> np.ndarray:
        R, t = poses[v]
        return K @ np.hstack([R, t[:, None]])

    def triangulate(a: int, b: int, g: np.ndarray) -> None:
        todo = [(x, y) for x, y in g if (a, int(x)) in track_of and track_of[(a, int(x))] not in points]
        if not todo:
            return
        arr = np.array(todo)
        X = cv2.triangulatePoints(P(a), P(b), kps[a][arr[:, 0]].T, kps[b][arr[:, 1]].T)
        X = (X[:3] / X[3]).T
        for (x, _), p in zip(todo, X):
            ok = True
            for v in (a, b):
                R, t = poses[v]
                c = R @ p + t
                if c[2] <= 0:
                    ok = False
            if ok and np.all(np.isfinite(p)):
                points[track_of[(a, int(x))]] = p
    triangulate(i0, j0, g0)
    while True:
        cand = []
        for v in range(n):
            if v in poses:
                continue
            obs = [(track_of[(v, k)], k) for k in range(len(kps[v])) if (v, k) in track_of and track_of[(v, k)] in points]
            cand.append((len(obs), v, obs))
        cand = [c for c in cand if c[0] >= 12]
        if not cand:
            break
        _, v, obs = max(cand)
        obj = np.array([points[tk] for tk, _ in obs])
        img = np.array([kps[v][k] for _, k in obs])
        ok, rvec, tvec, inl = cv2.solvePnPRansac(obj, img, K, None, iterationsCount=2000, reprojectionError=1.5,
                                                 confidence=0.999, flags=cv2.SOLVEPNP_SQPNP)
        if not ok or inl is None or len(inl) < 12:
            break
        rvec, tvec = cv2.solvePnPRefineLM(obj[inl.ravel()], img[inl.ravel()], K, None, rvec, tvec)
        poses[v] = (cv2.Rodrigues(rvec)[0], tvec.ravel())
        for (a, b), g in matches.items():
            if v in (a, b) and a in poses and b in poses:
                triangulate(a, b, g)
    # refinement by alternating resection (PnP-LM per view) and multi-view DLT intersection (a light-weight stand-in for
    # bundle adjustment; robust: observations with > 4 px error are dropped)
    obs_by_track: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for (v, k), tk in track_of.items():
        obs_by_track.setdefault(tk, []).append((v, k))
    for _ in range(refine_iters):
        for v in sorted(poses):
            ob = [(points[track_of[(v, k)]], kps[v][k]) for k in range(len(kps[v])) if (v, k) in track_of and track_of[(v, k)] in points]
            if len(ob) < 12 or v == i0:
                continue
            obj = np.array([o[0] for o in ob])
            img = np.array([o[1] for o in ob])
            R, t = poses[v]
            c = (K @ (R @ obj.T + t[:, None])).T
            e = np.linalg.norm(c[:, :2] / c[:, 2:3] - img, axis=1)
            keep = (c[:, 2] > 0) & (e < 4.0)
            if keep.sum() < 12:
                continue
            rvec, tvec = cv2.solvePnPRefineLM(obj[keep], img[keep], K, None, cv2.Rodrigues(R)[0], t.reshape(3, 1).copy())
            poses[v] = (cv2.Rodrigues(rvec)[0], tvec.ravel())
        for tk in list(points):
            views = [(v, k) for v, k in obs_by_track.get(tk, []) if v in poses]
            if len(views) < 2:
                continue
            A = []
            for v, k in views:
                Pv = P(v)
                x, y = kps[v][k]
                A += [x * Pv[2] - Pv[0], y * Pv[2] - Pv[1]]
            X = np.linalg.svd(np.array(A))[2][-1]
            if abs(X[3]) < 1e-12:
                continue
            X = X[:3] / X[3]
            errs = []
            for v, k in views:
                R, t = poses[v]
                c = K @ (R @ X + t)
                errs.append(np.inf if c[2] <= 0 else float(np.linalg.norm(c[:2] / c[2] - kps[v][k])))
            if max(errs) < 4.0:
                points[tk] = X
            elif np.median(errs) > 4.0:
                del points[tk]
    # colours + reprojection error
    pts_ids = list(points)
    X = np.array([points[k] for k in pts_ids]) if pts_ids else np.zeros((0, 3))
    colors = np.zeros((len(X), 3))
    err: dict[int, list[float]] = {v: [] for v in poses}
    first_obs: dict[tuple[int, int], tuple[int, int]] = {}
    for (v, k), tk in track_of.items():
        if tk in points and v in poses:
            first_obs.setdefault(tk, (v, k))
            R, t = poses[v]
            c = K @ (R @ points[tk] + t)
            err[v].append(float(np.linalg.norm(c[:2] / c[2] - kps[v][k])))
    for idx, tk in enumerate(pts_ids):
        v, k = first_obs[tk]
        x, y = np.clip(kps[v][k].round().astype(int), 0, [w - 1, h - 1])
        colors[idx] = rgb[v][y, x] / 255.0
    return {"K": K, "poses": [poses.get(v) for v in range(n)], "points": X, "colors": colors,
            "registered": sorted(poses), "pairs": len(matches),
            "reproj_rmse_px": {v: float(np.sqrt(np.mean(np.square(e)))) if e else None for v, e in err.items()}}


def umeyama(src: np.ndarray, dst: np.ndarray) -> tuple[float, np.ndarray, np.ndarray]:  # noqa: D103 — kept for point clouds
    """Similarity (s, R, t) minimising |s·R·src + t − dst|²."""
    mu_s, mu_d = src.mean(0), dst.mean(0)
    a, b = src - mu_s, dst - mu_d
    U, S, Vt = np.linalg.svd(b.T @ a / len(src))
    D = np.eye(3)
    if np.linalg.det(U) * np.linalg.det(Vt) < 0:
        D[2, 2] = -1
    R = U @ D @ Vt
    s = float(np.trace(np.diag(S) @ D) / (a ** 2).sum(1).mean())
    return s, R, mu_d - s * R @ mu_s


def evaluate(rec: dict[str, Any], gt: list[dict[str, Any]]) -> dict[str, Any]:
    """Gauge-fix the reconstruction to ground truth with a similarity transform — rotation from the camera orientations
    (chordal mean; camera centres on an arc alone leave it ill-conditioned), then scale + translation from the centres —
    and report the worst camera-centre error (relative to the rig radius) and rotation error."""
    reg = list(rec["registered"])
    est_c = np.array([-rec["poses"][v][0].T @ rec["poses"][v][1] for v in reg])
    gt_c = np.array([gt[v]["center"] for v in reg])
    M = sum(gt[v]["R"].T @ rec["poses"][v][0] for v in reg)          # est world → gt world rotation: R_gt^T R_est
    U, _, Vt = np.linalg.svd(M)
    Ra = U @ np.diag([1, 1, np.sign(np.linalg.det(U @ Vt))]) @ Vt
    rc = (Ra @ est_c.T).T
    a, b = rc - rc.mean(0), gt_c - gt_c.mean(0)
    s = float((a * b).sum() / (a * a).sum())
    aligned = s * a + gt_c.mean(0)
    scale = float(np.linalg.norm(b, axis=1).mean()) or 1.0
    rot_err = []
    for v in reg:
        dR = (rec["poses"][v][0] @ Ra.T) @ gt[v]["R"].T
        rot_err.append(math.degrees(math.acos(max(-1.0, min(1.0, (np.trace(dR) - 1) / 2)))))
    return {"registered": len(reg), "views": len(gt), "center_err_rel_max": float(np.linalg.norm(aligned - gt_c, axis=1).max() / scale),
            "rot_err_deg_max": max(rot_err), "points": int(len(rec["points"]))}


def write_points_ply(points: np.ndarray, colors: np.ndarray) -> bytes:
    head = ("ply\nformat ascii 1.0\n" + f"element vertex {len(points)}\n"
            + "property float x\nproperty float y\nproperty float z\nproperty uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n")
    body = "".join(f"{x:.6f} {y:.6f} {z:.6f} {int(r * 255)} {int(g * 255)} {int(b * 255)}\n" for (x, y, z), (r, g, b) in zip(points, colors))
    return (head + body).encode()


def run_bundle(bundle_dir: Path, focal_px: float | None = None) -> dict[str, Any]:
    """Reconstruct a RealityLoom capture bundle (`bundle.json` + `objects/`): writes `sfm/sparse.ply` + `sfm/cameras.json`."""
    import json
    bundle_dir = Path(bundle_dir)
    m = json.loads((bundle_dir / "bundle.json").read_text(encoding="utf-8"))
    imgs = [(bundle_dir / "objects" / v["sha256"][:2] / v["sha256"]).read_bytes() for v in m["views"]]
    rec = reconstruct(imgs, focal_px=focal_px)
    out = bundle_dir / "sfm"
    out.mkdir(exist_ok=True)
    (out / "sparse.ply").write_bytes(write_points_ply(rec["points"], rec["colors"]))
    cams = [{"view": i, "sha256": m["views"][i]["sha256"], "registered": p is not None,
             **({"R": np.round(p[0], 9).tolist(), "t": np.round(p[1], 9).tolist(), "reproj_rmse_px": round(rec["reproj_rmse_px"][i], 4)} if p else {})}
            for i, p in enumerate(rec["poses"])]
    doc = {"K": rec["K"].tolist(), "cameras": cams, "points": int(len(rec["points"])), "registered": len(rec["registered"]),
           "method": "opencv-sift-incremental-sfm-cpu", "scale": "arbitrary (monocular)"}
    (out / "cameras.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return {**doc, "sparse_ply": str(out / "sparse.ply"), "rec": rec}
