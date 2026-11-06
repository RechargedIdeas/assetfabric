# F0 `[INFERENCE]` register

Extrapolations made while implementing F0 (chat did not freeze these verbatim):

1. **`forge.yaml` JSON Schema field layout** — synthesized from chat requirements (targets, profiles, dependencies, briefs, cluster, models); no frozen schema in transcript.
2. **PEP 440 package version `0.0.0+f0.0`** — chat used milestone label `0.F0.x`; pip requires compliant versions.
3. **Telemetry transport in F0 = JSONL append** under `.fabric/telemetry/` — chat specifies SQLite/DuckDB + WS; schema is real, SQLite/DuckDB dashboards deferred.
4. **Minimal GitHub Actions workflow** (`.github/workflows/f0-ci.yml`) — chat required CI acceptance harness; exact Actions shape not specified.
5. **Game Zero boot scene** (`scenes/boot.tscn` + `boot.gd`) — empty project implied; scene graph not specified.
6. **`locales/en.json` seed keys** — demonstrates no-hard-coded-strings policy; key set not from chat.
7. **Studio package layout** (`studio/assetfabric_studio`) — PySide6 direction is chat; F0 module paths are scaffolding choice.
8. **Contributor role name placeholders** — staffing names TBD.
9. **ADR file bodies** — decisions accepted from chat; ADR prose is condensed by implementer.
10. **`forge build --target godot-desktop`** — listed in chat F0.5; F0 ships status/store/job instead of a full build pipeline (noted in TODO).

Non-inferences (verbatim from specs): engine Compatibility, AMD fleet inventory, one-milestone offset, telemetry *field names* (SPEC §5.4), hard deferrals, F0/F1 gate pairing, tool catalog names.

## Repository setup (2026-11-05)

11. **License = proprietary, All Rights Reserved** (ADR-0001) — chosen by the Producer when requesting a private repo; not decided in chat.
12. **THIRD_PARTY_NOTICES.md** list — derived from `pyproject.toml` dependencies; full SBOM is an F7 requirement.
13. **Vulnerability-reporting SLA** in SECURITY.md (2/5 business days) — placeholder targets.
14. **Branch naming, code style rules, issue/PR templates, CODEOWNERS** — conventional GitHub hygiene, not specified in chat.
15. **RC family name** for reality-capture models (ADR-0010) — chat called it R1, clashing with the R1 Retro Render Compiler.
16. **Process-sandbox fallback** when KVM/Firecracker is unavailable (ADR-0007 consequences).
