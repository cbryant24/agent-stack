## Knowledge Sources

Consult these when generating or refining image/video prompts, choosing techniques, or reasoning about model behavior. Do not rely on training memory for Z-Image Turbo or Wan 2.2 — both post-date it.

### Model documentation

- **Z-Image Turbo (text-to-image):** official model card (inference params, prompting guidance) — https://huggingface.co/Tongyi-MAI/Z-Image-Turbo. Fetch before drafting Z-Image prompts or debugging generation settings.
- **Wan 2.2 (video):**
  - Official repo (architecture, prompting, variants) — https://github.com/Wan-Video/Wan2.2
  - ComfyUI workflow tutorial (matches how this agent runs the model — workflows, memory variants, sampler settings) — https://docs.comfy.org/tutorials/video/wan/wan2_2
  - Model card (T2V-A14B) — https://huggingface.co/Wan-AI/Wan2.2-T2V-A14B
  - Prefer the ComfyUI doc for pipeline/settings questions; the repo and HF card for prompting and capability questions.

### Agent stack (visual-generation)

- [`packages/visual-generation/README.md`](../packages/visual-generation/README.md) — pipeline overview ("How a generation actually happens": pod → `model sync` → `workflow register` → `draft` → `generate` → `report`), memory model, and CLI commands.
- [`packages/visual-generation/docs/z-image-turbo-craft.md`](../packages/visual-generation/docs/z-image-turbo-craft.md) — living Z-Image craft guide: recommended settings presets (cfg/steps/sampler recipe) and prompt craft.
- [`packages/visual-generation/docs/production-testing-playbook.md`](../packages/visual-generation/docs/production-testing-playbook.md) — end-to-end harness exercising every generation path in production.
- [`packages/visual-generation/docs/canon-guide.md`](../packages/visual-generation/docs/canon-guide.md) — code-enforced identity locks for characters/places.

### Qdrant knowledge base

The agent maintains a semantic knowledge base in Qdrant (generation techniques, past results, learned preferences). Search it via the agent CLI — it handles Voyage embedding and secrets:

```bash
op run --env-file=.env -- uv run visual-generation recall "<query>"
```

**When to use `recall`:**
- Before drafting a new generation prompt (check for known techniques/styles that worked)
- When choosing between models or settings for a task
- When the user references past generations or established preferences

**Coverage-audit queries** (e.g. "what do we know about X across the whole KB"): use raw Qdrant scroll instead — `recall`/`explain` can confabulate over gaps. The collection is `visual_generation_memory`; the discriminator payload key is `memory_type` (values: `generation`, `technique_lesson`, `workflow_template`):

```bash
curl -s "$QDRANT_URL/collections/visual_generation_memory/points/scroll" \
  -H "api-key: $QDRANT_API_KEY" \
  -d '{"filter": {"must": [{"key": "memory_type", "match": {"value": "generation"}}]}, "limit": 50}'
```

- For canonical/recommended settings, check `z-image-turbo-craft.md` or the model card first — `recall` surfaces past generations and lessons, not authoritative defaults.