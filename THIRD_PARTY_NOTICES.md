# Third-party notices

AssetFabric is proprietary (see [LICENSE](LICENSE)). It depends on third-party software that keeps its own license. This list covers direct dependencies as of F0; a generated SBOM + license audit is required in CI before any BoltPack publish (F7, see SECURITY.md).

| Component | Use | License |
|---|---|---|
| Godot Engine 4.3 | Game Zero runtime (not vendored; `godot-bin/` is gitignored) | MIT |
| PyYAML | `forge.yaml` parsing | MIT |
| pydantic | data models | MIT |
| jsonschema | manifest / telemetry validation | MIT |
| click | `forge` CLI | BSD-3-Clause |
| rich | CLI output | MIT |
| pytest (dev) | tests | MIT |
| PySide6 (optional, Studio) | desktop Studio GUI | LGPL-3.0 (dynamic linking only) |
