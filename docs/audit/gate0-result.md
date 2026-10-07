# Gate 0 result: PASS

Recorded 2026-10-07T17:48:52.279909+00:00 for project `gate0` (template `visual-workflow`).

| Criterion | Result | Detail |
|---|---|---|
| seed_matches_graph | PASS | 3 generation(s): record, provenance and the submitted graph agree |
| random_seeds_differ | PASS | 2 random-seed runs, all different: 2639021278, 2815346798 |
| fixed_seed_honored | PASS | fixed seed 12345 was submitted and recorded exactly |
| replay_inputs_preserved | PASS | graph, output and source files present, hashes match the records |
| unsupported_slot_refused | PASS | refused before submission: Skipped dd1d4d50-e748-43f7-a4c9-56fd5e93c2a3: workflow template 'visual-workflow' has no seed slot, so the requested seed can't be applied — use a template with a sampler seed, or register it again so the seed slot is inferred |

## Attempt record

```yaml
attempt_id: gate0-2026-10-07
project_id: gate0
evaluation_case: Gate 0 - execution truth
question: Does each saved record's seed equal the seed in the graph that was submitted?
acceptance_gate: evaluation-charter.md Gate 0
environment:
  git_commit: f6ecc51f4673d953d9bd49e5f9e739350949de4c
  working_tree_status: dirty
execution:
  fixed_seed_requested: 12345
  generations:
    - generation_id: fbec1aef-b957-4bfd-b0db-b693492610a2
      prompt_id: 8585bf4b-ee2f-4947-88f4-e3862b36289c
      seed_strategy: random
      resolved_seed: 2639021278
      graph_seed: 2639021278
      workflow_name: visual-workflow
      workflow_sha256: c681f84aff8ea12c5242351305052cc1abf17b1a04205cb37254a13b48f3199c
      submitted_graph_path: /Users/chrisbryant/agent-data/visual-generation/assets/gate0/fbec1aef-b957-4bfd-b0db-b693492610a2.graph.json
      submitted_graph_sha256: 70113f1defa0a0efd3c184dc335af9f8adb55c5d9d55bb21692b3cb407fcde49
      output_files: ['/Users/chrisbryant/agent-data/visual-generation/assets/gate0/fbec1aef-b957-4bfd-b0db-b693492610a2.png']
      output_sha256: ['a8a695d99fd30c4af71762d1c0e9b11142b52d8fab920fb05d3ee08da766988f']
    - generation_id: 4a1551ff-f8bd-498a-8dd1-5ee0d662f714
      prompt_id: 4fc4ad83-ab6b-46d5-aeb7-b097e5b550e3
      seed_strategy: random
      resolved_seed: 2815346798
      graph_seed: 2815346798
      workflow_name: visual-workflow
      workflow_sha256: c681f84aff8ea12c5242351305052cc1abf17b1a04205cb37254a13b48f3199c
      submitted_graph_path: /Users/chrisbryant/agent-data/visual-generation/assets/gate0/4a1551ff-f8bd-498a-8dd1-5ee0d662f714.graph.json
      submitted_graph_sha256: 4315d3f49673f55894b51a4785dfec878503942908f813b1387b971b2ef103d7
      output_files: ['/Users/chrisbryant/agent-data/visual-generation/assets/gate0/4a1551ff-f8bd-498a-8dd1-5ee0d662f714.png']
      output_sha256: ['fc97af591f8728afa9405b435db9c88282df7af31b89525ef5e39c0fd182d0e5']
    - generation_id: fc259aaa-fda5-4fb9-9d6d-8eaa0a44b5cb
      prompt_id: 828f984d-dd09-45dc-9ab9-2e9d35c8aa92
      seed_strategy: fixed
      resolved_seed: 12345
      graph_seed: 12345
      workflow_name: visual-workflow
      workflow_sha256: c681f84aff8ea12c5242351305052cc1abf17b1a04205cb37254a13b48f3199c
      submitted_graph_path: /Users/chrisbryant/agent-data/visual-generation/assets/gate0/fc259aaa-fda5-4fb9-9d6d-8eaa0a44b5cb.graph.json
      submitted_graph_sha256: 8a912e71416f9fe100f9a6f0b0d56c68aeb77151314453f5234ca798b332ebf1
      output_files: ['/Users/chrisbryant/agent-data/visual-generation/assets/gate0/fc259aaa-fda5-4fb9-9d6d-8eaa0a44b5cb.png']
      output_sha256: ['7d80daca42f21d7640e0d39ca0869af2956ae2754667f3d6fcfbadae8512fb2a']
results:
  agent_status: agent-pass
  observed: ['seed_matches_graph', 'random_seeds_differ', 'fixed_seed_honored', 'replay_inputs_preserved', 'unsupported_slot_refused']
  unresolved: []
  director_signoff: false
```

Set `EXECUTION_TRUTH_VERIFIED_SINCE` to the date this passes only after the director signs off.
