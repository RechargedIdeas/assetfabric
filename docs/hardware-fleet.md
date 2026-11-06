# docs/hardware-fleet.md — Node inventory

Authoritative inventory from design chat / ASSETFABRIC_SPEC §10. Mirrored in `forge.yaml` `cluster.nodes`.

| Node | Specs | Tier / Role |
|---|---|---|
| **main** | Ryzen 9 5900X, RX 7900 XFX 24GB, 64GB RAM (~32GB free typical) | T1 — Studio host, heavy gen/train |
| **secondary** | Ryzen 5 1600, Vega 64 + Vega 56 (8GB each), 32GB RAM | T2 — batch gen, parallel inference; GPUs **do not pool** |
| **redmi** | Redmi Note 12 Pro 5G, Dimensity 1080, Mali-G68, 8GB | T3 — PocketLoom reference |
| **lemur** | System76 Lemur Pro 9 (Clevo L140CU), i7-10510U, UHD 620, **40GB RAM**, Windows (WSL2 optional) | T4 — portable Studio, warm cache, light inference |
| **nokia** | Nokia 7.2 | T5 — QR/client/review |
| **kindle-1/2** | Kindle Fire tablets | T5 — second-screen dashboards |

## AMD-critical (no NVIDIA in fleet)

| Path | Guidance |
|---|---|
| **Windows** | Prefer **DirectML** |
| **Linux 7900** | **ROCm 6.x** when available |
| **Universal** | **Vulkan** (e.g. llama.cpp) |
| **Vega 56/64** | DirectML / Vulkan only — **not** ROCm 6 |
| **UHD 620** | Do **not** use OpenVINO-on-UHD620 as primary (often slower than CPU) |
| **CUDA-only 3DGS trainers** | Need OpenSplat+ROCm / CPU COLMAP / Meshroom honesty — show real ETAs |

## Weakest acceptance contract

**2 CPU cores, no GPU** (chat used Ryzen 5 1600 with GPUs disabled as contract hardware).  
Every GPU capability needs a **GroundWeave** CPU software path, or must declare GPU-required and be routed by LoomCluster.
