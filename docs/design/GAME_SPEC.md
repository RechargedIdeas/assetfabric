# GAME_SPEC.md — Game Zero (MVP / First Product)

> **Source:** DeepSeek share https://chat.deepseek.com/share/g90tn4mss3265u0xm3 (56 msgs, ChatGrabber high fidelity).  
> **Product name in docs:** **Game Zero** (chat final documentation). Working description: 8-bit fighter/farming hybrid.  
> Built **with AssetFabric**; Game Zero is AssetFabric’s first real product and final MVP test.  
> Prefer chat; mark `[INFERENCE]` where extrapolated.

---

## 1. Pitch

An offline-first **8-bit fighter + farming** game set in **caves, tunnels, and open-world** exploration, with a **futuristic-retro** hybrid look (2D / 2.5D / 3D layers). The player picks one of **four base fighters**; the other three start as **followers**. The roster grows; temporary **time-freeze swaps** let the player take control of followers with a tactical overlay. **Pets**, synergies, tactics, bosses with tiers, and per-entity AI (policies + micro LMs) are core. Platforms: **Android Kotlin** (services + companion surfaces), **Web GUI (PWA)**, **Python desktop Studio/GUI**, game runtime on **Godot 4**.

---

## 2. Design Pillars (from chat)

1. **Offline-first:** every shipped mode runs with zero network.
2. **AI-native but fallback-safe:** BT + neural policy + tiny LM; **no LLM on combat tick path**.
3. **Party as system:** followers, pets, tactics, synergies — not a lone hero.
4. **Tactical clarity:** time-freeze swap exposes optimal choices, status, threats.
5. **Fabric-proven content:** sprites, caves, abilities, dialogue generated/validated through AssetFabric.
6. **Equal balance intent:** automated Monte Carlo balancing; pet stacking with diminishing returns + hard caps.
7. **Cross-input:** controller, touch, keyboard/mouse; full remapping; a11y palettes.

---

## 3. Platforms & Clients

| Client | Role |
|---|---|
| **Godot 4 game** | Authoritative gameplay runtime (Compatibility renderer) |
| **Android Kotlin** | Platform services plugin (STT, sensors, FS, haptics) + PocketLoom companion edition |
| **Web PWA** | Offline-capable HTML5 export; COOP/COEP; size budget |
| **Python desktop GUI** | Studio (training, telemetry, asset gen, character creator, sandbox) — not embedded inside Godot |

Controller support via Godot Input Map with one abstract schema (`attack`, `swap`, `interact`, `tactic_menu`, …).

---

## 4. Core Gameplay Systems (MVP)

### 4.1 Combat / Fighters

- **4 base fighters** at start; player chooses main; other 3 are followers.
- Gain additional characters over progression; can **swap into** them temporarily.
- **Time-freeze swap:** pause (or ~1% speed); overlay shows:
  - each character’s target, HP, cooldowns, position
  - **ranked optimal swap** recommendations
  - nearby enemies / threat scores
  - pet status / synergies
- Recommendation via **lightweight forward simulation** (~2s simulated combat per candidate), target **<50 ms** wall time (precompute/cache during freeze).
- Level 1 start; distinct base stats; growth; skills/abilities/moves; **specializations**.
- Shared items vs character-unique items.
- Character synergies / party **tactics** (player-authored coordination policies).

### 4.2 Pets

- Start: choose **1 of 3** starter pets (distinct fighting styles).
- Many more pets unlockable; fight alongside.
- Pet↔character bonuses; small bonuses to allies of that character; multiple pets per character up to a cap; **diminishing-returns stacking** + hard cap (balance first-class).

### 4.3 AI (characters, pets, enemies, bosses)

| Entity | Decision | Language |
|---|---|---|
| Character | BT + ONNX RL policy | Shared backbone + LoRA |
| Pet | BT + ONNX policy | Smaller/shared + pet LoRA |
| Enemy | BT + ONNX; tier-scaled | Optional generic callout adapter |
| Boss | Hierarchical RL (manager phase + worker) | Dedicated boss adapter |

- Agents learn/adapt (online fine-tune / replay where budget allows).
- **CascadeHub** message bus for realtime agent↔agent↔player chat.
- Player talks via **typing + voice**; shared offline **Vosk** STT (game-vocab fine-tune).
- Combat callouts from **pre-generated cache** (zero LM in combat loop); live LM for non-critical dialogue under latency budget (<2s E2E on mobile-mid).

### 4.4 World

- Biomes: **caves, tunnels, open world** exploration.
- Farming loop (F6): crops/resources that feed combat progression `[INFERENCE: exact crops/economy not specified — implement minimal gather/grow/craft loop that feeds loot/economy schema]`.
- Bosses + trash mobs with **tier system** (skills, weaknesses, weapons, accessories scaled by tier).

### 4.5 Progression & Creator

- Character creator in Studio: stats, skills, personality, accessories, fighting style → emits Godot resources + LoRA job + policy warm-start.
- Player State: Profile / Roster / World layers; versioned; migratable; cross-platform local save (cloud saves deferred).

### 4.6 Look & feel — futuristic retro hybrid

Three composited layers + global pixelation/quantization post-process:

1. **2D** characters/UI (nearest-neighbor; billboards in 3D scenes)
2. **2.5D** world stage (flat plane, fixed-angle camera, Y-sort)
3. **3D** set pieces / effects under same retro post-process

AssetFabric **R1 Retro Render / Q1 Pixel Stability / V1 Validation** produce authenticity packs — **no engine fork** required (bake Shadowglass-like features into Fabric).

### 4.7 Multiplayer

- **Single-player** fully featured offline.
- **P2P** via WebRTC + signaling; **self-hosted** signaling locally for LAN/self-host mode.
- Host simulates AI companions; clients send inputs for controlled character during swaps.
- **v1 scope:** co-op / host-client; **mesh beyond 2 players deferred**; dedicated servers deferred.
- Anti-cheat: **server-authoritative** validation (movement/actions); never trust client HP/inventory.

---

## 5. MVP Scope (what ships)

### In scope for Game Zero v1

| Area | MVP bar |
|---|---|
| Fighters | 4 base + unlock path for additional roster entries (at least a small set beyond 4) `[INFERENCE: “wide range” full roster may be post-slice; vertical slice needs 4 + unlocks demonstrated]` |
| Pets | 3 starters + at least several unlockable archetypes |
| World | One cave system + one open-world transition + farming loop stub that completes vertical slice |
| Combat | Abilities, shared/unique items, tactics UI, time-freeze swap overlay |
| AI | Party followers act independently; callouts; basic voice/text commands offline |
| Bosses | ≥1 tier-3 boss proven by balance runner |
| Platforms | Desktop signed builds; mid-range Android; Web/PWA offline |
| Fabric dependency | All content path goes through AssetFabric generators/validators |

### Explicitly out of scope for Game Zero v1 (chat)

- Quantum game mechanics
- Fantasy console carts as ship target
- Modern console SKUs
- Mod marketplace / community asset sharing
- P2P mesh >2 players; dedicated servers
- Live seasonal content (remote config readiness OK)
- Cross-platform cloud saves
- Full Studio “beauty” polish (functional required)

---

## 6. Acceptance Criteria

### 6.1 Vertical slice (must pass by F6 / ~end of Q3 staffing plan)

**15–20 minutes** of continuous playable content including:

1. Character select among 4 bases + starter pet choice  
2. Farming / gather beat that yields usable resources  
3. Cave exploration with solvable layout  
4. Open-world transition  
5. Full party combat with followers + pet  
6. Time-freeze swap with useful overlay  
7. One boss clear  
8. Save / quit / reload with no data loss  

### 6.2 System acceptance (tied to Fabric DoD)

| ID | Criterion |
|---|---|
| G-AI-01 | 10 agents @ 60 Hz policy inference on mobile-mid without frame-time violation |
| G-AI-02 | Voice command → party response <2s E2E offline on mobile-mid |
| G-AI-03 | Combat callouts never invoke LM in tick loop |
| G-NET-01 | Solo offline launch with networking stack dormant |
| G-NET-02 | 2-player P2P session with TURN fallback path verified |
| G-BAL-01 | Monte Carlo 1k encounters: win-rate deviation <5% across matchups |
| G-SAVE-01 | Desktop ↔ Android ↔ Web save round-trip |
| G-WEB-01 | PWA <45 MB compressed; offline SW; COOP/COEP verified |
| G-A11Y-01 | Colorblind palette variants + full input remap |
| G-FAB-01 | New sprite/ability/cave from Fabric briefs import with zero manual wiring |

### 6.3 Milestone ↔ game increments

| Fabric | Game increment |
|---|---|
| F0 | Env boots |
| F1 | Sandbox encounter |
| F2 | First full combat (party 4 + pets + enemies) |
| F3 | Party AI + swap + dialogue/callouts |
| F4 | Live iteration (hot reload/snapshots used by designers) |
| F5 | First boss + balance |
| F6 | Vertical slice complete |
| F7 | Desktop + Android + Web launch candidates |

**Rule:** Game team may not demand Fabric features outside DoD without a scope trade. Blockers escalate per AGENTS protocol (1 workday fix or approved temporary workaround).

---

## 7. Content Pipeline Expectations (via AssetFabric)

- Palette-constrained 8-bit sprites; seamless tiles; walk-cycle alignment  
- Cave gen from narrative constraint vectors (entry/exit/NPC/boss room) + solvability  
- Ability YAML → GDScript Ability + `.tres`  
- Dialogue/callout generation with safety gateway  
- Audio stems remixable by macro state (ambient/tension/combat/boss)  
- Character creator sandbox in Studio  

---

## 8. Telemetry & QA for the Game

- All agent actions + thought streams logged (debug builds expose live ThoughtStreamViewer)  
- Soft-lock detection on scripted playthroughs  
- Hybrid QA: automated agents + human playtesters  
- Remote config hooks for balance knobs (LiveOps content deferred)

---

## 9. Staffing / Timeline Context (chat)

Indicative with **12–15 people:** Q1 sandbox; Q2 combat+AI; Q3 vertical slice; Q4 platform launches. Smaller teams → proportionally longer. **If vertical slice slips, cut DoD scope — do not endlessly extend Fabric.**

---

## 10. Open Design Decisions `[INFERENCE / chat “Decisions Needed”]`

Document answers in DECISIONS.md before locking content:

- Exact names/stats/specializations of the 4 base fighters  
- Exact 3 starter pets  
- Farming loop economy numbers  
- Whether F8 retro ROM authenticity build is in v1  
- Max pets per character and synergy formula coefficients (optimizer will tune; designers lock caps)

---

*End of GAME_SPEC.md*
