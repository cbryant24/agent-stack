# Gate 0 — execution truth: how to run it

Gate 0 (from `evaluation-charter.md`) asks one question: **is the recorded execution the real
execution?** You run three images on a neutral fixture, then a read-only command judges the evidence.
This is the entry gate for the Phase 5 generation and pod tools: do not build on them until it passes.

It costs a few minutes of one pod (three images on a warm pod, well under $1). The only GPU spend is
step 3. Everything else is free.

## What passes it

| Check | Passes when |
|---|---|
| `seed_matches_graph` | for every image, the seed on the stored record, the seed in the provenance file, and the sampler seed **in the saved graph file itself** are all the same |
| `random_seeds_differ` | the two random-seed images used different seeds |
| `fixed_seed_honored` | the fixed-seed image used exactly the requested seed (12345) |
| `replay_inputs_preserved` | each image has its saved graph, the graph's hash matches, the output file's hash matches, and any source file's hash matches what was uploaded |
| `unsupported_slot_refused` | a spec whose template has no seed slot is refused at plan time, before anything is submitted |

## The fixture

`batch.md` (this folder): project `gate0`, template `z-image-turbo-lora`, a plain red ceramic mug on a
white table. Two random-seed specs and one fixed-seed spec (seed 12345). No character, no LoRA, no
source image, so the run isolates the platform and the agent from any art-direction difficulty. The
workflow bakes in a character LoRA; the agent now switches it off when a spec asks for none, and the
gate shows that line.

## Steps

```bash
cd ~/dev/agent-stack

# 0. Free: make sure the template is registered (skip the register line if it is listed).
agent visual-generation workflow list
agent visual-generation workflow register packages/visual-generation/workflows/z-image-turbo-lora-api.json \
    --name z-image-turbo-lora --descriptor "Z-Image-Turbo stills with a LoRA loader"

# 1. Free: look at the cost gate without spending. Answer n. You should see the three specs, the
#    per-run estimate, and "switched off template-baked LoRA(s): narrator-zimage.safetensors".
agent visual-generation generate packages/visual-generation/docs/gate0/batch.md --all \
    --endpoint http://127.0.0.1:8188

# 2. Bring up a pod and ComfyUI (see scripts/README.md for the SSH/tunnel details). Billing starts at `up`.
./scripts/pod up
#    scp + run scripts/comfyui-bootstrap on the pod, open the tunnel:
#    ssh -N -L 8188:127.0.0.1:8188 root@<IP> -p <PORT> -i ~/.ssh/id_ed25519
agent visual-generation model sync --endpoint http://127.0.0.1:8188

# 3. The only spend: three images. The ceiling stops the run early if something is wrong.
agent visual-generation generate packages/visual-generation/docs/gate0/batch.md --all \
    --endpoint http://127.0.0.1:8188 --max-session-cost 1.00

# 4. Delete the pod now. Verification reads local files only; do not leave it billing.
./scripts/pod down

# 5. Free and read-only: judge the evidence and write the record.
agent visual-generation gate0 verify --project gate0 --template z-image-turbo-lora \
    --fixed-seed 12345 --out docs/audit/gate0-result.md
```

`gate0 verify` prints PASS or FAIL per check and exits non-zero on any failure. The record it writes
follows the charter's attempt record (see `record-template.md` for the blank form).

## If it passes

1. Read `docs/audit/gate0-result.md`, and look at the three images if you want to (appearance is not
   part of Gate 0; this gate is about the record).
2. If you accept it, set the date execution became trustworthy, in your environment (`.env`):

   ```bash
   EXECUTION_TRUTH_VERIFIED_SINCE=2026-10-07   # use today's date
   ```

   From then on, evaluations of newer generations stop being marked `agent_status=unresolved`.
   Generations made before that date stay marked, by design.
3. The Phase 5 generation and pod tools can now be built.

## If it fails

Do not set `EXECUTION_TRUTH_VERIFIED_SINCE`. The failing check's detail names the generation and what
disagreed. Keep the record (`--out`) with the failure in it; that is the evidence for the next fix.
A FAIL on `replay_inputs_preserved` for a generation made before this change simply means it has no
provenance: run Gate 0 on fresh images only.
