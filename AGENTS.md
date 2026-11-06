# AGENTS.md — Rules of Engagement

Authoritative instruction set for any AI agent (or human) working on **AssetFabric**.
Grounded in the DeepSeek design chat + `ASSETFABRIC_SPEC.md`.

**If you are an agent, read this file in full before taking any action.**

---

## 1. Project context

AssetFabric is the content fabric + execution substrate. **Game Zero** is its first product.
They are built in parallel with a **one-milestone offset** (see §3.2 and `BUILD_ORDER.md`).

**Single most important rule:**

> A Fabric milestone is not complete until a Game increment that depends on it ships, is playable, and passes its acceptance test.

If you are about to build a Fabric feature that no Game increment depends on, stop. Check `PLAN.md` §Out-of-Scope.

---

## 2. Read order (first session)

1. `AGENTS.md` (this file)
2. `HANDOVER.md`
3. `TODO.md`
4. `PLAN.md`
5. `BUILD_ORDER.md`
6. `ARCHITECTURE.md` (subsystem you touch)
7. `DECISIONS.md` (relevant ADRs)
8. `TESTING.md`

Then run:

```bash
source .venv/bin/activate
forge doctor
forge status
```

Prefer chatgrab specs over invention. Mark extrapolations **`[INFERENCE]`**.

---

## 3. Scope discipline

### 3.1 Hard contract

`PLAN.md` Definition of Done and Out-of-Scope are **hard contracts**. You may not:

- Add a capability not on the DoD without a formal scope change (§3.3).
- Build an Out-of-Scope capability “while we’re here.”
- Refactor for elegance alone — only to unblock a failing acceptance test.

### 3.2 One-milestone offset (enforced)

The Fabric may be **at most one milestone ahead** of the Game.

```
Fabric:  F0 → F1 → F2 → …
Game:         G0 → G1 → …
```

- If Game is at the F0 env-boots gate, Fabric may finish F0 and prepare F1 design — **but must not implement F1 generators** until F0’s game/env gate is green.
- **F1 is blocked** until F0 acceptance: empty Godot boots + `forge status` healthy + tests green.
- CI / agents: refuse to merge F1 generator code while `forge.yaml` `fabric.milestone` is `F0` and `game.increment` is still `env-boots` without an explicit milestone bump PR.

### 3.3 Scope change protocol

1. Write `docs/scope-changes/YYYY-MM-DD-<title>.md` (add + equal remove + timeline).
2. Producer + Factory Lead approval.
3. Update `PLAN.md` DoD / Out-of-Scope on `main`.

---

## 4. Hard runtime constraints (always)

1. **No LLM in the combat tick loop.**
2. **No untrusted code without sandbox during authoring.**
3. **No client-authoritative multiplayer state.**
4. **No hard-coded strings or paths** (locale keys + manifests).
5. **Every GPU capability has a CPU software path** (GroundWeave) — or declare GPU-required and route via LoomCluster.
6. **Weakest acceptance node: 2 cores, no GPU.**

---

## 5. Testing discipline

- Every change needs an acceptance test that fails before and passes after.
- F0 bar: `pytest` + `forge status` exit 0 + Godot structure smoke (`scripts/smoke_godot.sh`).
- Do not merge a change that only passes on one machine.

---

## 6. Documentation discipline

- Update docs in the **same commit** as the code.
- Schema changes → update `docs/schemas/` same commit.
- Non-trivial decisions → ADR under `docs/adr/` + `DECISIONS.md` index.
- Keep `HANDOVER.md` and `TODO.md` current every session.

---

## 7. Commit conventions

```
<type>(<scope>): <short summary>

<body: what and why>

Acceptance: <test that proves it>
Refs: <ADR, milestone>
```

Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `perf`.  
Scopes: `fabric`, `forge`, `game`, `studio`, `substrate`, `docs`, `cluster`, `pocketloom`.

---

## 8. Blocker escalation

1. File in `TODO.md` §Blockers with reproduction + proposed workaround.
2. Producer has **one workday** to assign a fix or approve temporary workaround.
3. No silent workarounds.

---

## 9. What not to do (v1)

Do not build: quantum hardware backends, fantasy-console targets, modern CertPacks, mod marketplace, P2P >2, dedicated servers, M1-Architect as ship gate, LiveOps content (hooks OK later).

Do not deeply implement PocketLoom / LoomCluster in an F0 Fabric session beyond placeholders.

Do not edit Sophonts or unrelated repos under this handoff.

Do not invent product requirements when the chatgrab specs already decide — mark `[INFERENCE]` if you must fill a gap.

---

## 10. Authority order

1. `PLAN.md` Out-of-Scope + DoD  
2. `DECISIONS.md` ADRs  
3. `BUILD_ORDER.md` / `HANDOVER.md`  
4. Latest Producer direction  

Conflict → escalate; do not resolve silently.
