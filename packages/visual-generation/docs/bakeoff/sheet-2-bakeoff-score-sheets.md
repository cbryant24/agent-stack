# Sheet 2 — Phase 3A Editor Bake-Off Score Sheets (Tests A / B1 / B2 / reduced D)

**Session question (fixed before pod start, per audit §16):** *Which editor stack preserves an
approved hero identity through multi-view derivation and successive edits, and preserves plate
geometry under edit — Qwen-Image-Edit 2511 or FLUX Kontext (with one plate-depth/edge-controlled
arm in Test D)?*

**Protocol constants (record once):** pod/volume IDs; model files + versions; fixed seeds per
test; every image saved with lineage label (input/output + parent). One variable changes at a
time. Same instructions given to both editors wherever the phrasing pattern allows; where a
model needs its native phrasing (image-addressed vs direct), record both phrasings.

**Scoring scale (all tests):** 0 = fail, 1 = marginal (visible defect a director would flag),
2 = pass (would ship). Score each cell independently before totaling.

---

## Test A — identity preservation through multi-view derivation

From the approved hero, derive per editor: front full-body, 3/4 view, profile, back view,
seated pose. (These become the reference pack if the editor wins.)

Score each derived view on: face structure · button eyes · hair topology · proportions ·
wardrobe fidelity · material continuity (skin stays clay, fabric stays fabric).

| View | Face | Eyes | Hair | Prop. | Wardrobe | Material | /12 |
|---|---|---|---|---|---|---|---|
| Front | | | | | | | |
| 3/4 | | | | | | | |
| Profile | | | | | | | |
| Back | | | | | | | |
| Seated | | | | | | | |

One table per editor. **Pass: total ≥ 48/60 with no single view < 8 and no criterion scoring 0
anywhere.** Back view scores hair/wardrobe/material only (face/eyes marked N/A, denominator
adjusted to /54).

## Test B1 — successive character-edit drift

Three sequential edits to the hero (each edit takes the previous output as input):
1. change expression (smile → surprised); 2. move one arm (hand on hip → pointing); 3. lighting
shift (neutral → warm amber key).

After each step score stability of: identity (face+eyes) · hair · wardrobe · background ·
camera/framing.

| After step | Identity | Hair | Wardrobe | Background | Camera | /10 |
|---|---|---|---|---|---|---|
| 1 | | | | | | |
| 2 | | | | | | |
| 3 (cumulative drift vs hero) | | | | | | |

**Pass: ≥ 24/30, step-3 row ≥ 8, no 0s.** The step-3 row is scored against the *original hero*,
not the previous step — cumulative drift is the point.

## Test B2 — derived set-framing coherence (reduced)

Prep: fix one bar master-plate candidate (empty, no characters) at the film's main framing;
both editors derive from the same plate. Derive: one small viewpoint shift + one close framing
(the two classes the film may actually need; large-alternate and reverse angles are deferred —
classification per audit Phase 2).

Score each derivation on: room topology · wall/counter relationships · door/window placement ·
material palette · shared landmarks recognizable.

| Framing | Topology | Walls/counter | Doors/windows | Palette | Landmarks | /10 |
|---|---|---|---|---|---|---|
| Small shift | | | | | | |
| Close | | | | | | |

**Pass: ≥ 16/20, no 0s.**

## Test D (reduced) — plate geometry preservation under edit

Insert one character (hero, standing, specified floor position) into the master-plate candidate
with: Qwen · Kontext · the plate-depth/edge-controlled arm. Score: counter position · furniture
coordinates · TV positions · wall geometry · camera perspective · insertion quality (contact
shadow + occlusion, Gate 2A zones judged visually this session; mechanical calibration comes at
the three-frame proof).

| Arm | Counter | Furniture | TVs | Walls | Camera | Insertion | /12 |
|---|---|---|---|---|---|---|---|
| Qwen 2511 | | | | | | | |
| Kontext | | | | | | | |
| Depth/edge-controlled | | | | | | | |

**Pass: ≥ 10/12 with insertion ≥ 1.**

---

## Decision rule

Winner = editor passing the most tests; ties broken by (1) Test A total (identity is the
scarcest resource), (2) Test D insertion score, (3) iteration cost (wall-clock per accepted
image, from the session log). If **both** editors fail Test A, stop the session — the fallback
architecture (solo-generate + conventional matte composite, audit §6 fallback) gets the next
session, not more attempts. If both pass everything, Qwen wins by default (multi-reference
native; Kontext is single-image and non-commercial-licensed).

Budget: pre-agreed cap $______ (est. 2–4 pod-hours ≈ $4–8). Stop rules: guardrail 3 applies per
test (3 failed attempts at one defect = stop scoring attempts, record fail); pod down during any
review longer than 15 min.

Outputs of a passing session: winning editor named; scored sheets committed; the winning Test A
set becomes the draft reference pack; the plate candidate goes to the hero-style approval queue.
