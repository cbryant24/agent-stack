# Visual Agent — evaluation charter

## Mission

Use the Celeste / Coraline production challenge as a demanding, repeatable evaluation of the visual-generation agent and its RunPod/ComfyUI image-video runtime. The project should reveal whether the system can produce usable media **and** whether it executes, records, reproduces, and prices that work truthfully.

Coraline is the production case. Generic fixtures are the controls that separate platform and agent failures from the difficulty of the art direction.

## Evaluation questions

### 1. Platform / RunPod

- Can a fresh pod be created, health-checked, bootstrapped, and torn down without hidden state?
- Can the pinned models and workflows be loaded from the selected storage configuration?
- Can cold load, warm run, queue, inference, transfer, and total uptime be measured separately?
- Are outputs and execution records durably exported before ephemeral storage disappears?
- Can the same evaluation run on a fresh pod and produce an equivalent technical result?

### 2. Agent correctness

- Does the submitted graph contain the resolved seed and every approved setting?
- Are unsupported slots rejected before paid submission?
- Do model, LoRA, workflow, source, mask, reference, and output records match execution?
- Can image and video artifacts be retrieved from ComfyUI history and tied to the correct prompt ID?
- Are approval gates enforced before a draft becomes a downstream source?
- Are sequence boundaries ordered and shared exactly as specified?

### 3. Production quality

- Do Celeste and the narrator remain the same approved puppets in solo and shared frames?
- Do character traits stay attached to the correct person?
- Does the bar remain the same set, with stable landmarks and camera relationships?
- Does the surface read as the approved painted-resin/fabric construction?
- Do edits and composites avoid seams, geometry damage, and cumulative identity drift?
- In video, do characters, materials, objects, set geometry, color, and camera remain stable throughout motion and between clips?

### 4. Cost and operational value

- What is the full cost per attempt and per accepted image/clip?
- How much time is cold-load overhead, inference, failed work, review idle time, and storage?
- Does the agent reduce accepted-output cost or merely automate more attempts?

## Status vocabulary

| Status | Meaning |
|---|---|
| `draft` | An output exists; no gate has been scored |
| `candidate` | Eligible for a named gate; lineage is complete |
| `approved` | Passed the named rubric with recorded human sign-off |
| `rejected` | Failed the named rubric; reasons recorded |
| `infrastructure-pass` | Pod/workflow/output path worked technically |
| `agent-pass` | Agent submitted and recorded the intended graph correctly |
| `visual-pass` | Output passed the stated visual rubric |
| `production-ready` | All applicable infrastructure, agent, visual, repeatability, and cost gates passed |

One output may be an infrastructure pass and a visual failure. Record each layer independently.

## Standard attempt record

Every evaluated attempt must retain:

```yaml
attempt_id:
project_id:
evaluation_case:
question:
baseline_attempt:
hypothesis:
changed_variable:
controlled_variables: []
acceptance_gate:
stop_rule:
session_cost_cap_usd:

environment:
  git_commit:
  working_tree_status:
  pod_id:
  gpu:
  hourly_rate_usd:
  volume_id:
  container_image:
  comfyui_commit:
  custom_nodes: []

execution:
  prompt_id:
  workflow_name:
  workflow_sha256:
  submitted_graph_path:
  resolved_seed:
  model_files: []
  model_sha256: []
  source_files: []
  source_sha256: []
  output_files: []
  started_at:
  completed_at:
  cold_load_seconds:
  inference_seconds:
  pod_uptime_seconds:

results:
  infrastructure_status:
  agent_status:
  visual_status:
  scores: {}
  observed: []
  inferred: []
  unresolved: []
  director_signoff:

cost:
  compute_usd:
  storage_usd:
  other_usd:
  total_usd:
```

The exact format may become a Pydantic model or JSON schema later. Until then, the fields are the evaluation contract.

## Benchmark ladder

### Gate 0 — execution truth

Run one random-seed image, a second random-seed image, and one explicit fixed-seed image against a neutral fixture.

Pass when:

- each saved record's seed equals the submitted graph's sampler seed;
- random attempts use different seeds;
- the fixed attempt uses the requested seed;
- replay inputs are preserved;
- a deliberately unsupported required slot fails before submission.

### Gate 1 — generic video plumbing

Use nonpersonal, non-Coraline fixtures.

Run:

1. one T2V clip;
2. one I2V clip;
3. one FLF2V clip;
4. replay one on a fresh pod.

Pass when the agent retrieves a playable video, verifies codec/container/dimensions/FPS/frame count/duration, saves execution lineage, preserves all input hashes, and reconciles total pod cost. FLF2V additionally checks decoded first and last frames against the two supplied boundaries.

### Gate 2 — approved still authority

Approve character heroes and set plates with the existing Sheet-1 and editor/set gates. No Coraline video candidate can pass without approved sources.

### Gate 3 — three-frame still continuity

Produce narrator solo, Celeste solo, and a two-shot in one approved set. Score identity, separation, geometry, material, camera, occlusion, and seams. Repeat the difficult shared-frame method enough to distinguish a method from a lucky output.

### Gate 4 — one Coraline clip

Use approved boundary frames for one difficult action. Score every frame or sampled frame set for:

- first/last-frame adherence;
- face and button-eye stability;
- hair, wardrobe, hands, and props;
- object permanence and subject separation;
- set geometry and camera;
- painted-resin/fabric material;
- temporal flicker, morphing, color drift, and unintended motion;
- encoding, runtime, and cost.

### Gate 5 — three connected clips

Use four approved keyframes and three clips with shared boundaries. Check seam behavior and cumulative drift across the assembled sequence. A pass is required before longer production.

### Gate 6 — production rehearsal

Render one representative scene segment through the intended agent path, including approval gating, manifests, artifact export, cost closeout, and edit handoff. Only after this passes should the system plan a full multi-scene sequence.

## Generic fixture requirements

Maintain a small distributable fixture pack that contains no personal photographs:

- one simple object on a fixed background for seed and graph tests;
- one public or purpose-created character image for I2V;
- two compatible boundary images with a clearly measurable transition for FLF2V;
- expected technical metadata and reference hashes;
- no copyrighted film frames as required test inputs.

Generic fixtures test plumbing. They do not replace Coraline's production-quality gates.

## Experiment discipline

- Predeclare the test, rubric, cost cap, and stop rule.
- Freeze inputs and hashes before generation.
- Change one variable for diagnostic comparisons.
- Record failed outputs and reasons.
- Review locally with the pod down whenever possible.
- Do not promote a result because it is attractive if it fails the named requirement.
- Do not infer model behavior from rationale prose when the graph or image supplies stronger evidence.
- Do not call a model/workflow comparison fair unless sources, precision, task, and scoring conditions are matched or the asymmetry is explicitly part of the test.

## Required outputs from an evaluation session

1. Attempt records and submitted graphs.
2. Inputs and output artifacts, or stable paths plus hashes.
3. Completed rubric and human sign-off where required.
4. Cost reconciliation against the cap.
5. A decision: pass, fail, inconclusive, or blocked by missing evidence.
6. The next allowed step, limited by the benchmark ladder.

