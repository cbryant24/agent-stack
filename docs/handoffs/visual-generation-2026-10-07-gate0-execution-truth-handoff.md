---
title: "visual-generation — Execution truth fixes and the first Gate 0 run"
date: 2026-10-07
type: handoff
project: agent-stack
package: visual-generation
status: complete
purpose: session-narrative-for-comprehension-quizzing
tags:
  - handoff
  - visual-generation
  - execution-truth
  - gate0
  - runpod
  - agent-shell
---

# visual-generation — Execution truth fixes and the first Gate 0 run (2026-10-07)

This is a narrative of why the work happened and what it taught, not a changelog. Git has the changelog (`a2395c1`, `b117501`, `2a7b9b4`, `dc30283`, `2eb2ba5`, `8a9fac7`, `f6ecc51`, `efc7415`). The next phase is **Phase 5, Session 2**: the generation and pod tools inside `visual_generation/chat/`. It was waiting on this work, and it is now unblocked.

## 1. Why this session happened: the agent could not vouch for its own records

The `agent-shell` chat layer (Phases 0 to 4) lets you talk to `visual-generation` and write structured evaluations and lessons into memory. Phase 5 is where the chat gains the power to spend money: bring a pod up, render, tear it down. Before giving a chat that power, the foundation under it has to be honest.

The audit (`docs/audit/execution-truth-status.md`) found it was not. The post-mortems on the failed Coraline attempt (`coraline-failure-conclusions.md`) had already shown the symptoms: renders that did not match what was asked, and no way to tell why. The root problem was a gap between *what the record said* and *what actually ran*:

- A "random" seed was never written into the graph that went to ComfyUI, so renders ran on the template's own seed while the record claimed another.
- A LoRA baked into a template's loader still applied when a spec asked for no LoRA.
- A spec's identity LoRA could be dropped when the template had too few loader slots, and the render still happened.
- No value was range-checked, so a typo in steps or strength was submitted as is.
- Nothing saved the graph that was actually submitted, so a render could not be replayed or audited.

Every lesson and evaluation you write afterward is built on those records. If the records can lie, the lessons are noise. That is why the phase doc puts a gate (**Gate 0**) in front of the generation tools, and why the evaluation code already marks evaluations of older generations `agent_status=unresolved`.

## 2. What was fixed, and the design choices behind each fix

Each fix followed the phase doc: a failing regression test first, then the code, one commit per fix.

**Baked-in LoRAs.** The new `neutralize_unused_loras` sets the strength of any loader the spec did not use to 0. If a baked loader has no strength slot, it cannot be turned off, so the spec is skipped at plan time with a reason. Silently rendering with an identity nobody asked for was judged worse than refusing. The gate now prints a line such as "switched off template-baked LoRA(s) the spec did not ask for".

**Identity LoRA that cannot load.** If an identity-bearing LoRA lands in `unmapped` (no loader slot), the spec is skipped. Identity is decided by the model registry, the same authority `generate` already used. A non-identity LoRA dropped this way stays an advisory warning. The split matters: a dropped style LoRA degrades a picture, a dropped identity LoRA gives you a different character.

**Range validation: reject, don't clamp.** You chose rejection at plan time. Clamping would silently change what you asked for, which is exactly the class of defect being removed. Bounds live in `constants.py` (`VALUE_BOUNDS`) so they are easy to adjust, and the check runs on the *effective* settings, so a refinement's default denoise is checked too. Validation covers only values a spec states. A size left unset still takes the template default (1152×896), which is still open as audit row 5.

**Provenance files.** Beside each output the code writes `<gen_id>.graph.json` (the exact graph submitted, after sources were applied) and `<gen_id>.provenance.json` (seed, workflow hash, submitted-graph hash, input and output file hashes, endpoint, timings, unmapped and neutralized lists). Identity-bearing outputs stay under the secured root so path guards still pass. The seed regression test uses a real `ComfyUIClient` on an `httpx.MockTransport`, captures the POSTed prompt, and asserts the seed in that body equals the seed on the stored record. That proves the record against the submit, not against itself.

Both render paths were covered. `quick_generate` builds its own graph, so every fix was applied there too.

**Gate 0 tooling.** `visual-generation gate0 verify` is read-only. It reads provenance files and stored records, and it judges five checks: seed matches the saved graph, random seeds differ, the fixed seed is honored, replay inputs are preserved (graph hash matches its file, output hash matches), and an unsupported required slot is refused before submission. Judging from saved evidence means no pod is needed to verify, so the pod can be deleted the moment generation ends.

## 3. Running Gate 0 live, and what went wrong on the way

The run hit five separate problems. Each is worth understanding.

1. **The `agent` wrapper pointed at a `.env` that did not exist** (`~/projects/agent-stack/.env` instead of `~/dev/agent-stack/.env`). `op run` needs that file to resolve `op://` references, so every `agent` command failed. Fixed in `~/.zshrc`. The shell function only changes in a new shell or after `source ~/.zshrc`.
2. **`generate` before a pod existed** produced `ComfyUIUnreachable` and a raw traceback. No GPU time was spent because the failure was at the first submit. The traceback is a real, still-open flaw: the CLI should catch that exception and print one line.
3. **`pod up` failed with `RUNPOD_API_KEY is unset`.** The script reads the key from the environment, not from `.env`. The fix is to run it under `op run --env-file=.env --`.
4. **ComfyUI was not running on a fresh pod.** The code survived on the Global Volume, but the Python venv lives on the container disk (`/comfy-data`) and is wiped when a pod is deleted. `comfyui-bootstrap` rebuilds it each time. This is the "pod is disposable, volume is not" rule from the 2026-09-20 handoff showing up in practice.
5. **`model sync` dropped the character LoRAs.** The sync compares the registry against what this pod's volume actually has. The inference pod's `loras/` folder held only four Wan video LoRAs. The `z-image-turbo-lora` template bakes in `narrator-zimage.safetensors`, and ComfyUI validates a loader's filename against the files it sees even when strength is 0, so every submit would have been rejected. The fix was to point the fixture at the plain `visual-workflow` template. The consequence: Gate 0 passed, but the live run did not exercise the baked-LoRA switch-off. Unit tests cover that path, and a live check is still owed. Where the LoRAs should live is undocumented.

One thing looked like a hang and was not: after answering `y`, nothing printed for minutes. The first render on a fresh pod loads the VAE, the 7.6 GB text encoder and the diffusion model from the network volume. The log showed it working. Later renders took about 2 seconds. This matches the cold-versus-warm finding in the 2026-09-20 handoff.

## 4. Result

All five checks passed (`docs/audit/gate0-result.md`). Random seeds 2639021278 and 2815346798 differed, and fixed seed 12345 was honored. Session inference cost was about $0.098. The pod ran roughly 30 minutes, around $0.35 at $0.69/hr, and was deleted. `./scripts/pod status` confirmed none remained.

Gate 0 passing does not set the trust date. `EXECUTION_TRUTH_VERIFIED_SINCE` in `.env` is the director's own sign-off, and it is the line that stops new evaluations being marked `unresolved`.

## 5. What is still open

- Set `EXECUTION_TRUTH_VERIFIED_SINCE=2026-10-07` when you accept the record.
- `git push origin main` (all Phase 5 Session 1 commits are local).
- The default 1152×896 size when a spec leaves size unset (audit row 5).
- A raw traceback on an unreachable endpoint.
- The fifth check's detail line says `visual-workflow` "has no seed slot", though that template honored seeds. It is believed to test a constructed template, not confirmed.
- A live check that a baked LoRA is really switched off, which needs a pod whose volume has the LoRAs.
- Remaining §9 items from the failure analysis (drafter grounding, stale LoRAs offered, alias matching, trigger tokens, image-level verification, ledger coverage, prompt length budget). These are warnings in the REPL, not blockers.

## 6. The next phase: Phase 5, Session 2

Spec: `docs/agent-shell/phase-5-generation-and-pod-lifecycle.md`. Start in plan mode, and show the exact confirm-panel text for `pod_up` and `generate` before any coding.

**Part A, generation tools.** `plan_generation` (READ), `generate` (GPU_SPEND, wrapping `spend_generation_sync` on a plan), `quick_generate` (GPU_SPEND), `gpu_ledger` (READ). `generate` refuses without an `AttemptPlan` (question, baseline, hypothesis, changed variable, controls, acceptance gate, stop rule, cost cap). The cap is passed as `max_session_cost`. A spec sourced from a prior generation is skipped unless that generation has a positive reaction.

**Part B, pod tools.** `pod_status`, `pod_up` (GPU_SPEND, billing starts), `pod_bootstrap`, `pod_tunnel`, `model_sync`, `export_artifacts`, `pod_down` (DESTRUCTIVE_LOCAL, stops billing). These shell out to `scripts/pod` and `scripts/comfyui-bootstrap` with explicit argument lists, no `shell=True`, a timeout, and output captured in the audit log. The scripts are bash, tested, and encode incident fixes, so they are not reimplemented. Never pass `TEMPLATE_ID` or `IMAGE` overrides.

**Session behavior.** The REPL checks for a running pod at startup. It records uptime from `pod_up` to `pod_down` in the GPU ledger as its own entry type. It prompts to export and delete when a batch drains, warns while a pod is up during review, and runs an idle check-in in place of `pod watch`. A `/pod rebuild` command implements the ten-step runbook with a checkpoint per step.

**What this session taught that Session 2 must respect.**
- `pod_up` needs the API key through `op run`, so the tool must run under that environment.
- Bootstrap, tunnel and sync are separate checkpoints, because each failed independently in this run.
- Sync must run per pod, because the registry reflects one pod's volume and a different pod can drop entries.
- A silent first render is normal, so the tool needs to report "loading models", not just wait.
- Tests use a fake scripts directory and the ComfyUI `MockTransport`. No test creates a pod.

## 7. Questions this document should let you answer

- Why does the agent refuse a spec instead of clamping an out-of-range value?
- Why does a missing baked-LoRA strength slot skip the spec, while a dropped non-identity LoRA only warns?
- What does the seed regression test compare against, and why is that stronger than comparing the record to itself?
- Why can `gate0 verify` run after the pod is deleted?
- Why was the venv missing on a fresh pod while the ComfyUI code was present?
- Why would the `z-image-turbo-lora` template have failed even with the LoRA strength at 0?
- What did the run not prove, and what would prove it?
- What is the difference between Gate 0 passing and `EXECUTION_TRUTH_VERIFIED_SINCE` being set?
- Which part of the real pod bill does the agent's "session cost" not include?
