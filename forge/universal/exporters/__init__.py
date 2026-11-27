# AssetFabric — Copyright © 2026 Recharged Ideas. All Rights Reserved. Proprietary; see LICENSE.
"""Built-in adapter registry (id → Adapter). Plugins add to it at runtime through `forge.universal.plugins`."""

from __future__ import annotations

from forge.universal.exporters.base import Adapter, AdapterError, Pack, read_manifest, verify_manifest
from forge.universal.exporters.capture import ColmapAdapter, FuseAdapter, ReconImportAdapter, SplatsAdapter
from forge.universal.exporters.generic import CatalogGenericAdapter
from forge.universal.exporters.three_d import (MESH_PACKS, BlenderAdapter, GltfAdapter, GodotAdapter, OpenScadAdapter,
                                               UnityAdapter, UnrealAdapter)
from forge.universal.exporters.two_d import (AppGameKitAdapter, Atlas2DAdapter, ClickteamAdapter, ConstructAdapter,
                                             EpicCharGenAdapter, RpgMakerAdapter, SpriteLampAdapter)

BUILTINS: list[Adapter] = [GltfAdapter(), GodotAdapter(), UnrealAdapter(), UnityAdapter(), BlenderAdapter(), OpenScadAdapter(),
                           *MESH_PACKS, Atlas2DAdapter(), RpgMakerAdapter(), SpriteLampAdapter(), ConstructAdapter(),
                           ClickteamAdapter(), AppGameKitAdapter(), EpicCharGenAdapter(), ColmapAdapter(), SplatsAdapter(),
                           ReconImportAdapter(), FuseAdapter(), CatalogGenericAdapter()]
REGISTRY: dict[str, Adapter] = {a.id: a for a in BUILTINS}

__all__ = ["Adapter", "AdapterError", "Pack", "REGISTRY", "BUILTINS", "read_manifest", "verify_manifest"]
