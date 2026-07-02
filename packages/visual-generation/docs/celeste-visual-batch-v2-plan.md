# celeste-you-dangerous — visual-batch v2 plan (8 production shots)

**Status:** ready to execute, not started. **Written:** 2026-07-02 (end of the Celeste-LoRA session).
**Picks up in:** a fresh Claude Code session — read this top to bottom first, then execute.
**Goal:** a **fresh `visual-batch.md`** with **8 production stills** covering all four sections of
`directed.md`, drafted against the now-complete character-LoRA foundation. Script, voiceover, and
music are **done** — images are the only missing asset class before `edit-brief`.

## 1. Why fresh

The existing `~/agent-projects/celeste-you-dangerous/visual-batch.md` is **pre-LoRA era**
(2026-06-14→22): empty `lora_stack`s, fixed seeds as a continuity crutch, and Celeste descriptors
from before her look was locked. Everything it worked around is now solved properly. **Step 1:
archive it** — `mv visual-batch.md visual-batch-v1-pre-lora.md` (keep for reference/lineage; some
specs reference old generations). Then draft the new shots with
`-o ~/agent-projects/celeste-you-dangerous/visual-batch.md` so the director artifact is rebuilt
fresh (type-only filename per `docs/naming-conventions.md`).

## 2. Foundation state (all DONE — do not rebuild)

Full history: [`character-lora-plan.md`](character-lora-plan.md) (read §6 gotchas + Phase 6 notes).

- **Canon** (`canon show celeste-you-dangerous` to verify, 4 subjects):
  - **the narrator** (Chris): pinned `narrator-zimage.safetensors@2.0`, locked text = skin cue only.
  - **Celeste**: pinned `celeste-zimage.safetensors@2.0`, locked text = pale cream felt + **no-blush
    cue** (must stay; blush re-emerges without it). Forbids include braid/pigtail/blush/short-sleeve.
  - **the storefront** + **the bar interior**: rich locked set descriptions (text-only, no LoRA —
    deliberate; see plan §1).
- **Templates registered:** `visual-workflow` (no LoRA), `visual-workflow-lora` (1 slot),
  **`visual-workflow-lora2`** (2 slots, for two-shots), `visual-workflow-img2img`,
  `visual-workflow-inpaint` (the refine templates have **no LoRA slot** — a deferred variant; build
  only if a cast shot needs a refinement pass).
- **Both LoRAs live on the pod volume** (`/workspace/runpod-slim/ComfyUI/models/loras/`) — survive
  pod cycles; registry synced, identity-bearing.
- **VO** takes: `~/agent-data/voiceover/audio/celeste-you-dangerous/`. Music: done. Script:
  `directed.md` (4 sections) is the beat source of truth.

## 3. Proven per-shot recipes (hard-won — follow them)

- **Solo shot:** `draft --template visual-workflow-lora --canon "<subject>" …` — canon injects the
  LoRA at 2.0 + locked text automatically.
- **Two-shot (narrator + Celeste):** `--template visual-workflow-lora2 --canon "Celeste" --canon
  "the narrator"`. Canon pins both at 2.0, but **1.5/1.5 renders cleaner** (less identity bleed):
  after drafting, **hand-edit the spec's `lora_stack` strengths in the batch file to 1.5** (canon
  override happens at draft time only; `generate` reads the file as-is). Always add points
  restating for Celeste: **"long STRAIGHT black yarn hair, not braided/twisted" + "long-sleeved"**
  (forbid strips words, it can't add them). Known residual: her lower hair may still twist
  dread-ward — acceptable, or masked-inpaint the hair on keeper frames.
- **Rear/back views:** camera instructions LOSE to the face-forward prior (0/3). Use
  **scene-motivated staging** ("watching the TV on the far wall from across the room", "standing at
  the window looking out") — 2/2.
- **Profiles:** come out ¾ (fine). Keep them **warm-lit** — cool TV-glow rim light once broke a
  button eye into a cartoon eye.
- **Settings are automatic** (tech lessons in memory): 1024×1024 (1152×896 stalls the model),
  cfg 1.0 / 8 steps / res_multistep / simple, no negative. Don't fight them.
- **Wardrobe is per-shot promptable** (narrator: hoodie/jeans/AJ1s vibes; Celeste: all-black
  long-sleeved waitress fit at work, hoodie+jeans off-shift). Button eyes limit eye-acting —
  play expressions through **eyebrows, mouth, and body pose** (worked for "annoyed hands-on-hips").

## 4. The 8 shots (map to directed.md beats)

| # | Section | Beat | Shot | Template / canon |
|---|---|---|---|---|
| 1 | Arrival | "He spots a bar with American sports on the screen" | Narrator from behind/¾-rear on the grey hex pavement facing the glowing storefront at dusk, TVs in the windows showing the game (scene-motivated rear) | `visual-workflow-lora`, narrator + the storefront |
| 2 | Arrival | "jumps, clicks his heels… sits down" | Interior: narrator mid-heel-click or grinning walking in, wall TVs glowing, warm amber | `visual-workflow-lora`, narrator + the bar interior |
| 3 | Adversity | "I'm a Knicks fan." | Two-shot: narrator seated at high-top (LEFT), Celeste standing over him smug, tray under arm (RIGHT) | `visual-workflow-lora2`, both (→1.5/1.5) |
| 4 | Adversity | "She's doing this on purpose. He smiles." | Close-up Celeste: smug head-tilt, one brow up (solo; her close-ups are proven) | `visual-workflow-lora`, Celeste + the bar interior |
| 5 | Win/Loss | Tequila shots — "Yes. I. Am." | Two-shot at the bar counter: narrator devilish grin raising a shot glass, Celeste mid-laugh/mock-outrage | `visual-workflow-lora2`, both (→1.5/1.5) |
| 6 | Win/Loss | "he turns, thanks her… he'll be back" | Narrator at the glass door threshold turning back over his shoulder, warm interior behind him, night street ahead | `visual-workflow-lora`, narrator + the storefront |
| 7 | Again & Again | Round 2 — "the fear… all over her face" | Close-up Celeste behind the bar, worried slanted brows + small frown, door-light on her | `visual-workflow-lora`, Celeste + the bar interior |
| 8 | Again & Again | Krillin beatdown — "it's amazing how much can happen on a couch" | Two-shot couch: Celeste leaning forward mid-victory with the controller, narrator slumped in disbelief (couch comp is a proven director favorite) | `visual-workflow-lora2`, both (→1.5/1.5) |

Coverage: 3 solo narrator / 2 solo Celeste / 3 two-shots; sets: storefront ×2, bar interior ×4,
living-room couch ×1 (+1 threshold). Adjust framings freely, keep the beat mapping.

Paul (the Knicks fan) is deliberately **not** in any shot — no LoRA, and background patrons render
generically. If the director wants him in #5, stage him as a blurred background figure only.

## 5. Execution flow (next session)

1. **Unlock 1Password once** (raise the app's auto-lock; every `op run` prompt-timeout this session
   traced to it re-locking). `op run --env-file=.env -- <cmd>` wraps every agent call.
2. Archive the old batch (§1), then **draft all 8** (free, ~$0.03/each) with
   `-o ~/agent-projects/celeste-you-dangerous/visual-batch.md`, sequentially (same-file appends).
3. Hand-edit the three two-shot specs' strengths to 1.5/1.5.
4. User spins up the ComfyUI pod (console) and pastes the endpoint (`https://<pod-id>-8188.proxy.runpod.net/`).
   Generate all 8 (`generate <batch> --section <id> --endpoint <url> --gpu-rate 2.09 -y`), ~$0.01–0.05 each.
5. Review as a set (open in Preview) — judge identity, set continuity, beat readability. Redraft /
   re-generate misses (rears and two-shots are the likely offenders). Refine keepers with
   img2img/inpaint only if needed (build the LoRA-refine template first if the change touches a
   character).
6. **Record reactions** (`report <gen-id> --reaction <…> --notes "…"`) for every reviewed frame —
   taste memory is the compounding asset.
7. Remind the user to **kill the pod** when generation is done.
8. Update this doc's status line + commit. Then the pipeline hands to `edit-brief`.
