# Gate 0 result: <PASS|FAIL>

`gate0 verify --out` fills this in for you. This is the blank form (evaluation-charter.md, "Standard
attempt record"), for recording a run by hand.

```yaml
attempt_id: gate0-YYYY-MM-DD
project_id: gate0
evaluation_case: Gate 0 - execution truth
question: Does each saved record's seed equal the seed in the graph that was submitted?
baseline_attempt:
hypothesis: the agent submits and records the same seed
changed_variable: none (control run on a neutral fixture)
controlled_variables: [template visual-workflow, prompt, size 1024x1024, steps 8, cfg 1.0]
acceptance_gate: evaluation-charter.md Gate 0
stop_rule: stop after the three images; do not iterate
session_cost_cap_usd: 1.00

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
  prompt_id:                 # one per image
  workflow_name: visual-workflow
  workflow_sha256:
  submitted_graph_path:
  submitted_graph_sha256:
  resolved_seed:
  graph_seed:
  model_files: []
  source_files: []
  output_files: []
  output_sha256: []
  started_at:
  completed_at:
  cold_load_seconds:
  inference_seconds:
  pod_uptime_seconds:

results:
  infrastructure_status:
  agent_status:              # agent-pass only if every check passed
  visual_status: n/a
  observed: []
  inferred: []
  unresolved: []
  director_signoff: false

cost:
  compute_usd:
  storage_usd:
  other_usd:
  total_usd:
```

Decision: pass, fail, inconclusive, or blocked by missing evidence.
Next allowed step: if pass and signed off, set `EXECUTION_TRUTH_VERIFIED_SINCE` and proceed to the Phase 5 tools.
