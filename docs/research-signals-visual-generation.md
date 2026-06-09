# Research signals — visual-generation (Phase 1 → Phase 2)

Between-phase knowledge gathering. Two arms: **course-doc ingestion** into `user_knowledge` (`comfyui_mechanics`) and **`tutorial-research` delegations** for gaps the course doesn't cover.

The key finding from Phase 1: the course (*Diffusion Mastery: Flux, Stable Diffusion, Midjourney & more*) teaches ComfyUI/Flux/SDXL in depth but for a **local M1 + Google Colab Pro** setup. It has **no RunPod content** and does not teach driving ComfyUI headlessly via API. So `comfyui_mechanics` is well-seeded by the docs, while `runpod_mechanics` and the remote-pod/API deployment are genuine gaps.

---

## Arm 1 — course docs → `user_knowledge` (`comfyui_mechanics`)

Ingested via the promoted `knowledge ingest-docs` path. **This arm runs after the first Phase 2 build session lands the runtime extraction + the knowledge path** — the command doesn't exist yet. The list is ready now; ingestion is sequenced early in Phase 2.

The ingest-docs folder is a durable queue (dedups, deferred items reappear), so over-inclusion is safe — defer/skip at the confirmation prompt.

**Tier 1 — core ComfyUI backend (ingest first):**
- `Section-09-Summary-ComfyUI-Basics-Flux-and-More.md` — node architecture; the default workflow (Load Checkpoint, CLIP Text Encode, Empty Latent, KSampler, VAE Decode, Save Image); Flux vs SDXL settings; LoRA node placement; GGUF; workflow JSON/metadata
- `Section-11-Summary-ComfyUI-Flux-Expert.md` — ControlNet, IP-Adapter, upscaling, the ComfyUI video-tool ecosystem
- `Section-08-Summary-Flux-Basics-Forge-WebUI.md` — Flux model formats (FP8/FP16/GGUF), the CFG=1.0 + separate Flux-guidance behavior, no-negative-prompt, Forge→ComfyUI mapping

**Tier 2 — diffusion fundamentals + settings semantics (feeds the tutor role):**
- `Section-02-Summary-How-Diffusion-Models-Work.md`
- `Section-04-Summary-Basics-of-Stable-Diffusion.md`
- `Section-03-Summary-DALL-E-and-Prompt-Engineering.md`
- `Section-06-Summary-Stable-Diffusion-Pro-Techniques.md`

**Tier 3 — LoRA (use-context for v1; training is deferred):**
- `Section-07-Summary-Train-Your-Own-SDXL-LoRA.md`
- `Section-10-Summary-Train-Your-Own-Flux-LoRA.md`

**Skip / defer for stills-v1:**
- `Section-05` (Fooocus — a different UI, not the agent's backend)
- `Section-12` (web platforms — not the backend; has some ComfyUI node-equivalent tables if wanted)
- The Veo3 / Google Flow lesson docs (Google video, a different path than WAN — defer with the video fast-follow)
- Standalone SD lessons (`1/2/3-...-stable-diffusion.md`) — overlap with Section-04; optional

---

## Arm 2 — `tutorial-research` delegations (gaps not in the course docs)

`tutorial-research` already exists, so **these can run now** to pre-seed the `tutorial_research` collection before Phase 2. Invocation is a direct CLI call to your existing agent — no Claude Code coding step. Match the exact subcommand/flags to your `tutorial-research` CLI (not reproduced here, as its README isn't in this context).

**Required for stills-v1 (the real gap):**

```bash
# RunPod pod lifecycle + running ComfyUI on a RunPod pod (the course teaches local + Colab, not RunPod)
tutorial-research "RunPod GPU pod setup ComfyUI deployment network volume"

# Driving ComfyUI headlessly via its API on a remote pod (course is UI-only)
tutorial-research "ComfyUI API headless prompt endpoint remote server"
```

**Optional for stills-v1 (course already covers these well — run only if a gap surfaces):**

```bash
# Sampler / scheduler tradeoffs beyond the course's defaults
tutorial-research "ComfyUI sampler scheduler comparison CFG steps tuning"
```

The course's ComfyUI technique coverage (samplers, CFG, ControlNet, IP-Adapter, LoRA use, upscaling) is rich, so technique delegations are low-priority for v1 — the doc ingest plus the agent's own accumulating `technique_lesson`s cover the stills MVP. Run technique delegations on demand once real generation surfaces specific gaps (Q9's prompt-on-gap).

**Manual ingest alternative for RunPod:** RunPod's own docs export cleanly to markdown — saving the relevant pages and running them through `knowledge ingest-docs` with `domain=runpod_mechanics` is a deterministic alternative (or complement) to the `tutorial-research` route above.

---

## Deferred research (with the video fast-follow, not now)

- **WAN 2.2 ComfyUI workflow** — the T2V/I2V/VACE graphs and the high/low-noise split. The course mentions WAN only in passing (a list of video models) and teaches different video tools (LivePortrait, Animate Anyone, Deforum) plus Google Veo3. WAN-via-ComfyUI is unseeded and will need `tutorial-research` when video work begins.
- **I2V input handling** (`/upload/image`) and keyframe selection — surfaces with video.
