# Phase 5 — `visual-generation chat`: generation and pod lifecycle

**Goal:** from the REPL, bring a pod up, generate, export artifacts, and tear the pod down, with every spend confirmed and every execution record trustworthy.

**Depends on:** Phase 4 and **Gate 0 passing**. **Spends GPU:** yes.

## Entry gate: execution truth

Do not start the generation tools until these are fixed in `visual-generation`, each with a regression test. Items 1-5 come from `coraline-failure-conclusions.md` §9 and item 6 from the experiment rules in `project-instructions.md`; Phase 0 reports current status:

1. Random seed resolved and written into the submitted graph (`generate.py`, `graph_build.py`).
2. `unmapped` slot values shown to the user.
3. Baked-in template LoRAs applying on empty stacks.
4. Canon pin silently dropped beyond the loader count.
5. No validation or clamping of steps, cfg, denoise, strength, size.
6. The final submitted API graph and source hashes saved with every output.

Then run **Gate 0** from `evaluation-charter.md` on a neutral fixture: two random-seed images and one fixed-seed image. It passes when each saved seed equals the submitted graph's sampler seed, the random seeds differ, the fixed seed is honored, replay inputs are preserved, and an unsupported required slot fails before submission.

These fixes are their own Claude Code sessions, separate from the REPL work. They can run in parallel with Phases 1-4.

**Status (2026-10-07).** Session 1 is done except for the live run: items 1 to 6 above are fixed and tested
(`a2395c1`, `b117501`, `2a7b9b4`, `dc30283`, `2eb2ba5`). A read-only checker, `visual-generation gate0 verify`,
the neutral fixture batch, the run guide and a record template are in `packages/visual-generation/docs/gate0/`.
**Gate 0 itself still has to be run on a pod by you**, and passed, before Session 2 (the tools) starts.
Two notes on what was built: out-of-range values are rejected at plan time and never clamped; and the
audit's "template default 1152×896" row is not part of this and remains open.

Remaining §9 items (drafter grounding, stale LoRAs offered, alias matching, trigger tokens, image-level verification, ledger coverage) are not blockers for wrapping `generate`, but the REPL surfaces them as warnings where it can.

## Part A — generation tools

`visual-generation` already splits generation into `plan_generation_sync` (free) and `spend_generation_sync` (paid). That split is the gate.

| Tool | Wraps | Effect |
|---|---|---|
| `plan_generation` | `plan_generation_sync` | READ |
| `generate` | `spend_generation_sync` on a plan | GPU_SPEND |
| `quick_generate` | `quick_generate_sync` | GPU_SPEND |
| `gpu_ledger` | `GpuLedger` | READ |

The `generate` confirm panel shows what the CLI gate shows today (spec count, per-run estimate and its source, rate, session estimate, local cumulative, skipped specs, refinement advisories, LoRA strength warnings, ceiling) plus the experiment fields below.

### Experiment discipline (from `project-instructions.md`)

Before any paid run the REPL requires an `AttemptPlan`, stored with the audit log and linked to the resulting evaluations:

```python
class AttemptPlan(BaseModel):
    question: str                 # the single question this run answers
    baseline_attempt: str | None
    hypothesis: str
    changed_variable: str         # one, unless the test studies a bundle
    controlled_variables: list[str]
    acceptance_gate: str
    stop_rule: str
    session_cost_cap_usd: float
```

`generate` refuses without one. `session_cost_cap_usd` is passed as `max_session_cost`.

The approval rule from the video guide also applies here: a spec whose source is a prior generation is skipped unless that generation has a positive reaction, with an explicit override flag.

## Part B — pod lifecycle

The lifecycle already exists as bash: `scripts/pod up|down|status|watch`, `scripts/comfyui-bootstrap` (run on the pod over SSH), `scripts/stage-models`. Facts the tools must respect:

- Pods are created and deleted, never started or stopped.
- `up` creates through RunPod's GraphQL API with `RUNPOD_API_KEY`; the rest uses `runpodctl`.
- Models live on the `stably_diffused` Global Volume. ComfyUI input, output, temp, user and the venv are on ephemeral container disk, so artifacts must be exported before deletion.
- Never use the `cnne9dp3rt` template or the `runpod/comfyui` image.
- ComfyUI listens on `127.0.0.1:8188` on the pod and is reached through an SSH tunnel.
- `watch` uses a macOS dialog and must run on the Mac.

| Tool | Wraps | Effect |
|---|---|---|
| `pod_status` | `scripts/pod status` | EXTERNAL_READ |
| `pod_up` | `scripts/pod up` | GPU_SPEND (billing starts here) |
| `pod_bootstrap` | scp + ssh `comfyui-bootstrap` | EXTERNAL_READ |
| `pod_tunnel` | SSH tunnel to 8188, returns the endpoint | EXTERNAL_READ |
| `model_sync` | `sync_models` against the endpoint | MEMORY_WRITE (registry) |
| `export_artifacts` | pull outputs and submitted graphs to local storage | READ |
| `pod_down` | `scripts/pod down` | DESTRUCTIVE_LOCAL (stops billing) |

These are subprocess calls. That is the one place shelling out is right: the scripts are bash, tested, and encode incident fixes. A Python port can come later behind the same tools.

### Session behavior

- On startup the REPL runs `pod_status` and tells you if a pod is already running.
- Uptime is tracked from `pod_up` to `pod_down` and written to the ledger. This closes the §9 gap that pod uptime never reached the GPU ledger.
- When a batch drains, the REPL prompts to export artifacts and delete the pod. It warns while a pod is up and you are reviewing: the repo rule is not to leave a pod running during human review.
- An idle check-in runs inside the REPL in place of `pod watch`; if the REPL exits with a pod up, it asks first and offers to start `scripts/pod watch`.
- The standard sequence is offered as one confirmed plan: queue everything locally, `pod_up`, bootstrap, tunnel, `model_sync`, `generate`, export, `pod_down`, then review.

### The rebuild runbook

`visual-generation-v2-refinements.md` ("Infra resilience") specifies a ten-step pod and volume rebuild runbook, deferred, with each step checkpointed and independently retryable. The pod tools above are those steps. Implement the sequence as a resumable procedure in the chat (`/pod rebuild`), keeping the runbook's checkpoints:

1. Confirm the Global Volume exists with `models/` populated.
2. Confirm `.env` has a safe `TEMPLATE_ID` and a `RUNPOD_API_KEY`.
3. `pod up`.
4. Check SSH keepalive config (`ServerAliveInterval 30`, `ServerAliveCountMax 3`).
5. Read SSH connection info.
6. `scp` the bootstrap script.
7. Run it.
8. Open the tunnel and confirm `/system_stats` answers from the pod and through the tunnel.
9. One smoke generation per model family needed, expecting the documented cold-load times.
10. `pod down`, or keep working with the idle check-in running.

A failed step reports which checkpoint failed and resumes from there.

## Acceptance

- Gate 0 passes and its record is saved.
- End-to-end on a neutral fixture from the REPL: up, bootstrap, tunnel, sync, generate, export, down. Each GPU step is confirmed.
- `generate` refuses without an `AttemptPlan` and stops at the cost cap.
- The ledger shows pod uptime cost for the session, separate from per-run inference estimates.
- Starting the REPL with a pod already running reports it.
- Dry-run walks the whole sequence without creating a pod.

## Risks

- **Orphaned pods.** Mitigated by the startup check, the exit prompt and the idle check-in.
- **Tunnel drops.** The 2026-09-20 handoff records SSH tunnel drops. `generate` checks endpoint health before submit and reports a dropped tunnel as a platform-layer finding.
- **Undocumented GraphQL create call.** `scripts/pod` notes it is a beta API. Keep the call in the script and wrap it.
- **Video.** Wan T2V/I2V through the agent CLI is not proven end to end. This phase covers stills. Video tools follow the video implementation guide's own phases.
- **Volume loss.** The volume was reclaimed once when the RunPod balance hit zero. Step 1 of the runbook checks for it; a missing volume stops the procedure with a clear message, because rebuilding the models is out of the runbook's scope.

## Claude Code prompts

Two sessions.

**Session 1 — execution truth (can start any time after Phase 0)**

1. **Goal:** fix the six entry-gate items with regression tests, then run Gate 0.
2. **Mode:** plan mode first, then direct.
3. **Files:** `@docs/audit/execution-truth-status.md @packages/visual-generation/docs/coraline-failure-conclusions.md @packages/visual-generation/docs/evaluation-charter.md @packages/visual-generation/src/visual_generation/generate.py @packages/visual-generation/src/visual_generation/graph_build.py`
4. **Prompt:**

```
Fix the execution-truth defects listed under "Entry gate" in
docs/agent-shell/phase-5-generation-and-pod-lifecycle.md, using
docs/audit/execution-truth-status.md for current status and locations.

One defect per commit. For each: write a failing regression test first, then the fix. The
seed test must assert that the seed stored on the generation record equals the seed in the
graph submitted to the ComfyUI client (use the existing httpx MockTransport pattern).
Persist the final submitted API graph and source file hashes next to every output asset.
Do not change prompt drafting, canon or LoRA selection behavior in this session.

When all tests pass, give me the exact commands to run Gate 0 from evaluation-charter.md on a
neutral fixture, and a template for recording its result. Do not start a pod yourself.
```

**Session 2 — tools (after Gate 0 passes)**

1. **Goal:** generation and pod tools in `visual_generation.chat`.
2. **Mode:** plan mode first, then direct.
3. **Files:** `@docs/agent-shell/phase-5-generation-and-pod-lifecycle.md @packages/visual-generation/src/visual_generation/chat/ @docs/v2-refinements/visual-generation-v2-refinements.md @docs/handoffs/visual-generation-2026-09-20-runpod-global-volume-handoff.md @packages/visual-generation/src/visual_generation/generate.py @packages/visual-generation/src/visual_generation/gpu_tracker.py @scripts/pod @scripts/comfyui-bootstrap @scripts/README.md @packages/visual-generation/runpod-setup-context.md`
4. **Prompt:**

```
Add the Part A and Part B tools from docs/agent-shell/phase-5-generation-and-pod-lifecycle.md
to visual_generation/chat/.

- generate wraps plan_generation_sync then spend_generation_sync. It requires an AttemptPlan
  and passes session_cost_cap_usd as max_session_cost.
- Pod tools call scripts/pod and scripts/comfyui-bootstrap as subprocesses with explicit
  argument lists (no shell=True), a timeout, and captured output in the audit log. Do not
  reimplement their logic. Never pass TEMPLATE_ID or IMAGE overrides.
- Record pod uptime from pod_up to pod_down in the GPU ledger as its own entry type.
- Startup pod check, exit prompt, idle check-in and drain prompt as described.
- Implement the ten-step rebuild runbook as a resumable procedure with a checkpoint per step.
- Tests use a fake scripts directory and the ComfyUI MockTransport. No test creates a pod.

Show me the plan and the exact confirm-panel text for pod_up and generate before coding.
```
