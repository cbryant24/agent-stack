# Production Testing Playbook — visual-generation (`celeste-you-dangerous`)

## Phase 0 — Prerequisites (shared by all workflows)

❯ curl -s <http://localhost:6333/> | head -1
{"title":"qdrant - vector search engine","version":"1.18.1","commit":"e01c207f40a2fe01ed23a191957a76e224fe5726"}%
❯ curl -s <http://localhost:6333/> | head -1
{"title":"qdrant - vector search engine","version":"1.18.1","commit":"e01c207f40a2fe01ed23a191957a76e224fe5726"}%
❯ agent visual-generation canon show celeste-you-dangerous
ls ~/agent-projects/celeste-you-dangerous/
Canon for 'celeste-you-dangerous' (1 subject(s)):

  • aliases: the narrator, narrator, @narrator
    locked:  a felt-and-clay stop-motion puppet of a young Black man, deep caramel-brown felt skin, long black yarn dreadlocks falling to mid-back
    forbid:  short hair, shoulder-length, buzz cut
directed.md     refs            script.md       story.md        techniques.md   visual-batch.md workflows
❯ agent visual-generation canon set celeste-you-dangerous \
    --alias "Celeste" --alias "the waitress" \
    --locked "a felt-and-clay stop-motion puppet of a young woman, smooth matte felt skin, long black yarn hair falling just past her
  shoulders, bare felt face with no makeup, glossy black stitched sewing-button eyes"
Canon set for 'celeste-you-dangerous' (subject 'Celeste'):
  aliases: Celeste, the waitress
  locked:  a felt-and-clay stop-motion puppet of a young woman, smooth matte felt skin, long black yarn hair falling just past her
  shoulders, bare felt face with no makeup, glossy black stitched sewing-button eyes

Stored at: ~/agent-data/visual-generation/canon/celeste-you-dangerous.json
❯ agent visual-generation canon show celeste-you-dangerous
ls ~/agent-projects/celeste-you-dangerous/
Canon for 'celeste-you-dangerous' (2 subject(s)):

  • aliases: the narrator, narrator, @narrator
    locked:  a felt-and-clay stop-motion puppet of a young Black man, deep caramel-brown felt skin, long black yarn dreadlocks falling to mid-back
    forbid:  short hair, shoulder-length, buzz cut

  • aliases: Celeste, the waitress
    locked:  a felt-and-clay stop-motion puppet of a young woman, smooth matte felt skin, long black yarn hair falling just past her
  shoulders, bare felt face with no makeup, glossy black stitched sewing-button eyes
directed.md     refs            script.md       story.md        techniques.md   visual-batch.md workflows
❯ agent visual-generation canon set celeste-you-dangerous \
    --alias "the narrator" --alias "narrator" --alias "@narrator" \
    --alias "Chris" --alias "the man" \
    --locked "a felt-and-clay stop-motion puppet of a young Black man, deep caramel-brown felt skin, long black yarn dreadlocks falling to
  mid-back" \
    --forbid "short hair" --forbid "shoulder-length" --forbid "buzz cut"
Canon set for 'celeste-you-dangerous' (subject 'the narrator'):
  aliases: the narrator, narrator, @narrator, Chris, the man
  locked:  a felt-and-clay stop-motion puppet of a young Black man, deep caramel-brown felt skin, long black yarn dreadlocks falling to
  mid-back
  forbid:  short hair, shoulder-length, buzz cut

Stored at: ~/agent-data/visual-generation/canon/celeste-you-dangerous.json
❯ agent visual-generation canon show celeste-you-dangerous
ls ~/agent-projects/celeste-you-dangerous/
Canon for 'celeste-you-dangerous' (2 subject(s)):

  • aliases: Celeste, the waitress
    locked:  a felt-and-clay stop-motion puppet of a young woman, smooth matte felt skin, long black yarn hair falling just past her
  shoulders, bare felt face with no makeup, glossy black stitched sewing-button eyes

  • aliases: the narrator, narrator, @narrator, Chris, the man
    locked:  a felt-and-clay stop-motion puppet of a young Black man, deep caramel-brown felt skin, long black yarn dreadlocks falling to
  mid-back
    forbid:  short hair, shoulder-length, buzz cut
directed.md     refs            script.md       story.md        techniques.md   visual-batch.md workflows
❯ agent visual-generation model sync --endpoint <https://<pod-id>-8188.proxy.runpod.net/>
Endpoint: <https://<pod-id>-8188.proxy.runpod.net/>
Sync plan: +0 new, ~14 refreshed, 0 kept-absent, -0 dropped.
Write this registry? [y/N]: y
Registry written: 14 asset(s) at ~/agent-data/visual-generation/models.json
❯ agent visual-generation model list
14 registered asset(s):

  [checkpoint] wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors  <synced>
  [checkpoint] wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors  <synced>
  [checkpoint] wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors  <synced>
  [checkpoint] wan2.2_t2v_low_noise_14B_fp8_scaled.safetensors  <synced>
  [checkpoint] z_image_turbo_bf16.safetensors  <synced>
  [clip      ] qwen_3_4b.safetensors  <synced>
  [clip      ] umt5_xxl_fp8_e4m3fn_scaled.safetensors  <synced>
  [lora      ] wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors  <synced>
  [lora      ] wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors  <synced>
  [lora      ] wan2.2_t2v_lightx2v_4steps_lora_v1.1_high_noise.safetensors  <synced>
  [lora      ] wan2.2_t2v_lightx2v_4steps_lora_v1.1_low_noise.safetensors  <synced>
  [vae       ] ae.safetensors  <synced>
  [vae       ] pixel_space  <synced>
  [vae       ] wan_2.1_vae.safetensors  <synced>

### Workflow 1 — Prove the knowledge surfaces (free, read-only) ⭐

❯ agent visual-generation knowledge-verify \
  "z-image turbo dreadlocks rooftop puppet" --project celeste-you-dangerous
Query: z-image turbo dreadlocks rooftop puppet
Project: celeste-you-dangerous

── Collection sizes ─────────────────────────────────
  visual_generation_memory: 61
  user_knowledge: 832
  tutorial_research: 2211
  technique_research_outputs: 22

── Knowledge surfaced (deterministic) ───────────────
  [strong] Prior generations (visual_generation_memory): 8 hit(s), top 0.40
      ↳ storybook stop-motion short-film production still, Coraline-inspired handmade felt and cla…
      ↳ storybook stop-motion short-film production still, Coraline-inspired handmade felt and cla…
      ↳ storybook stop-motion short-film production still, Coraline-inspired handmade felt and cla…
  [strong] Technique lessons (visual_generation_memory): 4 hit(s), top 0.44
      ↳ Z-Image Turbo renders at cfg 1.0, 8 steps, sampler res_multistep, scheduler simple, and us…
      ↳ 1152x896 wedges Z-Image (model stalls); render at 1024x1024.
      ↳ Inpaint with a tight, region-only mask (e.g. a screen's glass, inset inside its bezel), ne…
  [strong] Technique reports (technique_research_outputs): 6 hit(s), top 0.36
      ↳ Illustrated Storybook Visual Generation (Stop-Motion / Puppet-World Aesthetic)
      ↳ Handcrafted Texture & Grain Compositing (Paper, Stitch, Canvas Overlay)
      ↳ Anime Stylization Layering on Illustrated Frames (Limited Framerate + Smear Logic)
  [strong] Platform facts (user_knowledge): 8 hit(s), top 0.58
      ↳ - Official model card: <https://huggingface.co/Tongyi-MAI/Z-Image-Turbo> - GitHub: <https://g…>
      ↳ Download the Z-Image-Turbo text-to-image workflow JSON file. Run this workflow directly on…
      ↳ Z-Image Turbo CAN be LoRA-trained despite the model card's 'fine-tunability N/A': train di…
  [reference] Tutorial research (tutorial_research): 8 hit(s), top 0.46
      ↳ this cartoon bunny I made with the Qwen image model. Let's see if Zimage can reproduce tha…
      ↳ ем так. Вот здесь у нас теперь точно 5 изображений. Не знаю, у CRT нод вот такой баг есть,…
      ↳ In today's video, we are going to see how to train a LoRA for Zimage Turbo — how to unlock…
  [reference] Workflow templates (visual_generation_memory): 3 hit(s), top 0.45
      ↳ visual-workflow-img2img
      ↳ visual-workflow
      ↳ visual-workflow-inpaint

✓ No gaps flagged — relevant knowledge is reachable for this query.
❯ agent visual-generation knowledge-verify \
  "z-image turbo dreadlocks rooftop puppet"
Query: z-image turbo dreadlocks rooftop puppet

── Collection sizes ─────────────────────────────────
  visual_generation_memory: 61
  user_knowledge: 832
  tutorial_research: 2211
  technique_research_outputs: 22

── Knowledge surfaced (deterministic) ───────────────
  [strong] Prior generations (visual_generation_memory): 8 hit(s), top 0.40
      ↳ storybook stop-motion short-film production still, Coraline-inspired handmade felt and cla…
      ↳ storybook stop-motion short-film production still, Coraline-inspired handmade felt and cla…
      ↳ storybook stop-motion short-film production still, Coraline-inspired handmade felt and cla…
  [strong] Technique lessons (visual_generation_memory): 4 hit(s), top 0.44
      ↳ Z-Image Turbo renders at cfg 1.0, 8 steps, sampler res_multistep, scheduler simple, and us…
      ↳ 1152x896 wedges Z-Image (model stalls); render at 1024x1024.
      ↳ Inpaint with a tight, region-only mask (e.g. a screen's glass, inset inside its bezel), ne…
  [strong] Technique reports (technique_research_outputs): 6 hit(s), top 0.36
      ↳ Illustrated Storybook Visual Generation (Stop-Motion / Puppet-World Aesthetic)
      ↳ Handcrafted Texture & Grain Compositing (Paper, Stitch, Canvas Overlay)
      ↳ Anime Stylization Layering on Illustrated Frames (Limited Framerate + Smear Logic)
  [strong] Platform facts (user_knowledge): 8 hit(s), top 0.59
      ↳ - Official model card: <https://huggingface.co/Tongyi-MAI/Z-Image-Turbo> - GitHub: <https://g…>
      ↳ Download the Z-Image-Turbo text-to-image workflow JSON file. Run this workflow directly on…
      ↳ Z-Image Turbo CAN be LoRA-trained despite the model card's 'fine-tunability N/A': train di…
  [reference] Tutorial research (tutorial_research): 8 hit(s), top 0.46
      ↳ this cartoon bunny I made with the Qwen image model. Let's see if Zimage can reproduce tha…
      ↳ ем так. Вот здесь у нас теперь точно 5 изображений. Не знаю, у CRT нод вот такой баг есть,…
      ↳ In today's video, we are going to see how to train a LoRA for Zimage Turbo — how to unlock…
  [reference] Workflow templates (visual_generation_memory): 3 hit(s), top 0.45
      ↳ visual-workflow-img2img
      ↳ visual-workflow
      ↳ visual-workflow-inpaint

✓ No gaps flagged — relevant knowledge is reachable for this query.
❯ agent visual-generation knowledge-verify \
  "z-image turbo"
Query: z-image turbo

── Collection sizes ─────────────────────────────────
  visual_generation_memory: 61
  user_knowledge: 832
  tutorial_research: 2211
  technique_research_outputs: 22

── Knowledge surfaced (deterministic) ───────────────
  [strong] Prior generations (visual_generation_memory): 8 hit(s), top 0.24
      ↳ professional stop-motion film production still, Laika Studios quality, Coraline-level hand…
      ↳ storybook stop-motion anime hybrid still, Coraline-inspired handmade felt and clay texture…
      ↳ storybook stop-motion anime hybrid still, Coraline-inspired handmade felt and clay texture…
  [strong] Technique lessons (visual_generation_memory): 4 hit(s), top 0.59
      ↳ Z-Image Turbo renders at cfg 1.0, 8 steps, sampler res_multistep, scheduler simple, and us…
      ↳ 1152x896 wedges Z-Image (model stalls); render at 1024x1024.
      ↳ Inpaint with a tight, region-only mask (e.g. a screen's glass, inset inside its bezel), ne…
  [strong] Technique reports (technique_research_outputs): 6 hit(s), top 0.35
      ↳ Handcrafted Texture & Grain Compositing (Paper, Stitch, Canvas Overlay)
      ↳ Anime Stylization Layering on Illustrated Frames (Limited Framerate + Smear Logic)
      ↳ Lyrical Chapter Song Integration & Music-Picture Sync
  [strong] Platform facts (user_knowledge): 8 hit(s), top 0.74
      ↳ Z-Image is a 6B-parameter open-source text-to-image model family from Alibaba's Tongyi Lab…
      ↳ - Official model card: <https://huggingface.co/Tongyi-MAI/Z-Image-Turbo> - GitHub: <https://g…>
      ↳ - **Z-Image-Turbo** — distilled, 8 steps, CFG off. Visual quality Very High, diversity **L…
  [reference] Tutorial research (tutorial_research): 8 hit(s), top 0.57
      ↳ Welcome to episode 72 of our ComfyUI tutorial series. Today I will talk about the Zimage T…
      ↳ Welcome to episode 72 of our ComfyUI tutorial series. Today I will talk about the Zimage T…
      ↳ 190 seconds.Here is a chart showing the difference in time taken when generating an image…
  [reference] Workflow templates (visual_generation_memory): 3 hit(s), top 0.59
      ↳ visual-workflow
      ↳ visual-workflow-img2img
      ↳ visual-workflow-inpaint

✓ No gaps flagged — relevant knowledge is reachable for this query.
❯ agent knowledge-verify "suno music mastering chain"
error: Failed to spawn: `knowledge-verify`
  Caused by: No such file or directory (os error 2)
❯ agent music-curation knowledge-verify "suno music mastering chain"
Usage: music-curation [OPTIONS] COMMAND [ARGS]...
Try 'music-curation --help' for help.

Error: No such command 'knowledge-verify'.
❯ agent visual-generation digest celeste-you-dangerous
Digest for 'celeste-you-dangerous'

── Recent generations (8 of 48) ──────────
  cefe22ed-783  [PENDING]  storybook stop-motion short-film production still, Coraline-inspired h
  765ff814-184  [PENDING]  storybook stop-motion short-film production still, Coraline-inspired h
  f4124768-6a0  [PENDING]  storybook stop-motion short-film production still, Coraline-inspired h
  ff05f972-9f5  [DISLIKED ★2]  storybook stop-motion short-film production still, Coraline-inspired h
  7d4dde48-f11  [LIKED WITH CHANGES ★4]  storybook stop-motion short-film production still, Coraline-inspired h
  8dc68508-f42  [LIKED WITH CHANGES ★4]  storybook stop-motion short-film production still, Coraline-inspired h
  ee7ee937-b9d  [DISLIKED ★2]  storybook stop-motion short-film production still, Coraline-inspired h
  de5b3c7e-8a5  [LIKED WITH CHANGES ★4]  storybook stop-motion short-film production still, Coraline-inspired h

── Awaiting your reaction (6) ───────────────
  3784932f-a45  storybook stop-motion anime hybrid still frame, Coraline-inspired hand
  30991827-169  storybook stop-motion anime hybrid still frame, Coraline-inspired hand
  255f5d9d-184  Storybook stop-motion anime hybrid still frame, Coraline-inspired hand
  f4124768-6a0  storybook stop-motion short-film production still, Coraline-inspired h
  765ff814-184  storybook stop-motion short-film production still, Coraline-inspired h
  cefe22ed-783  storybook stop-motion short-film production still, Coraline-inspired h
  → record with: visual-generation report <id> <reaction>

── Confirmed technique lessons (4) ──────────
  [positive/settings] Z-Image Turbo renders at cfg 1.0, 8 steps, sampler res_multistep, scheduler simp
  [negative/settings] 1152x896 wedges Z-Image (model stalls); render at 1024x1024.
  [negative/workflow] When inpainting a screen, masking the prop's bezel/frame instead of glass-only l
  [positive/workflow] Inpaint with a tight, region-only mask (e.g. a screen's glass, inset inside its)

### Workflow 2 — Single hand-guided draft → generate → report (the core loop)

❯ agent visual-generation draft \
  "the narrator on a rooftop at dusk, wide cinematic shot, neon glow" \
  --project celeste-you-dangerous
Status:   completed
Cost:     $0.0348  (Claude — GPU is spent at `generate`)
Spec:     044064a8-ca06-4380-8a23-50c4ac50e6d1
Template: visual-workflow
Model:    z_image_turbo_bf16.safetensors

Prompt:   storybook stop-motion short-film production still, Coraline-inspired handmade felt and clay puppet aesthetic, visible woven fabric texture and stitched seams on every surface, rich saturated color palette, film grain overlay, cinematic frame composition. Wide cinematic rooftop shot at dusk: a Black American man stands alone at the edge of a Buenos Aires rooftop, full-body framing, seen from a low-angle wide lens that emphasizes the vast city skyline behind him, he leans on a felt-textured parapet railing looking out over the city, thoughtful and still. Dusk sky rendered in deep indigo-purple felt panels fading to amber-orange at the horizon, scattered neon signs below cast upward pools of electric magenta and cyan light onto the rooftop surface and the back of his clothing, warm golden streetlight glow from below mixing with cool neon haze. City skyline built from layered felt and clay building cutouts receding into atmospheric haze, hand-stitched window lights dotting every facade. Rooftop surface of dark charcoal felt with visible seam lines, scattered clay chimney props and antenna details. Puppet-world physical depth, slight imperfect edge registration, stop-motion tactile weight, every surface reads as handcrafted material. Saturated shadows, deep focus from foreground railing to midground figure to background skyline, cinematic 2.39:1 widescreen composition.
Settings: {'steps': 8, 'cfg': 1.0, 'sampler': 'res_multistep', 'scheduler': 'simple'}

── Compiled from (your project docs) ────────────────
  • directed.md
  • story.md
  • techniques.md

── Knowledge surfaced (deterministic) ───────────────
  [strong] Prior generations (visual_generation_memory): 5 hit(s), top 0.40
      ↳ storybook stop-motion short-film production still, Coraline-inspired handmade felt and cla…
      ↳ storybook stop-motion short-film production still, Coraline-inspired handmade felt and cla…
  [strong] Technique lessons (visual_generation_memory): 4 hit(s), top 0.45
      ↳ 1152x896 wedges Z-Image (model stalls); render at 1024x1024.
      ↳ When inpainting a screen, masking the prop's bezel/frame instead of glass-only lets the mo…
  [strong] Technique reports (technique_research_outputs): 3 hit(s), top 0.50
      ↳ Theatrical Act-Break Title Cards with Hard-Cut Grammar
      ↳ Voiceover-Led Narrative Editing & Pacing
  [strong] Platform facts (user_knowledge): 5 hit(s), top 0.53
      ↳ Try modifying the text in the **CLIP Text Encoder** ![CLIP Text Encoder](/images/comfy_cor…
      ↳ 1. Try modifying the `denoise` parameter in the **KSampler** node, gradually changing it f…
  [reference] Tutorial research (tutorial_research): 5 hit(s), top 0.45
      ↳ details and shown which parts of the lyrics were replaced later. As you can see, the style…
      ↳ K-Sampler. Попробуем. И вот такой selfie получился у нас. Давайте попробуем что-то больше…
  [reference] Workflow templates (visual_generation_memory): 3 hit(s), top 0.39
      ↳ visual-workflow
      ↳ visual-workflow-img2img

Rationale: Z-Image Turbo canonical settings: cfg 1.0, 8 steps, res_multistep/simple, no negative prompt — per your verified USER FACT that the graph zeroes the negative via ConditioningZeroOut and your TECHNIQUE LESSON confirming 1024x1024 to avoid model stalls at 1152x896. The prompt leads with the Coraline stop-motion storybook visual identity established across your LIKED prior generations (felt panels, stitched seams, visible fabric weave on every surface, puppet-world physical depth), then places the narrator on a wide-angle rooftop at dusk with neon uplight from the Buenos Aires cityscape below — a new establishing shot that fits the film's theatrical chapter structure without restating locked character appearance.

── Your own technique lessons (relevant) ────────────
  • 1152x896 wedges Z-Image (model stalls); render at 1024x1024.
  • When inpainting a screen, masking the prop's bezel/frame instead of glass-only lets the model reinterpret the whole prop and yields a framed poster, not a lit screen; mask the glass region only.
  • Inpaint with a tight, region-only mask (e.g. a screen's glass, inset inside its bezel), never the surrounding frame/prop, so the model can't reinterpret the whole object; masked inpaint tolerates denoise ~0.8 because the rest of the frame is untouched.
  • Z-Image Turbo renders at cfg 1.0, 8 steps, sampler res_multistep, scheduler simple, and uses no negative prompt (its graph zeroes the negative via ConditioningZeroOut).

Appended to: ~/agent-data/visual-generation/batches/celeste-you-dangerous.batch.md
Next: visual-generation generate ~/agent-data/visual-generation/batches/celeste-you-dangerous.batch.md --section 044064a8-ca06-4380-8a23-50c4ac50e6d1 --endpoint <url>
❯ agent visual-generation draft \
  "an empty neon rooftop, rain, no people" \
  --project celeste-you-dangerous
Status:   completed
Cost:     $0.0309  (Claude — GPU is spent at `generate`)
Spec:     cabc8e97-52c1-43f2-8a88-250c23f4ceeb
Template: visual-workflow-inpaint
Model:    z_image_turbo_bf16.safetensors

Prompt:   storybook stop-motion short-film production still, Coraline-inspired handmade felt and clay puppet texture with visible fabric weave and stitched seams on every surface, rich saturated color palette, film grain overlay, cinematic frame composition. Empty rooftop at night in Buenos Aires: rain falling in visible streaks across the frame, wet felt-textured rooftop surface reflecting neon light in puddles, glowing neon signage in warm magenta and electric blue casting colored light pools across the rooftop floor, distant city skyline rendered in dark layered felt panels, no people, no figures, complete solitude, rain mist rising from warm concrete, low fog drifting across rooftop edge, dramatic overhead cinematic composition, handcrafted puppet-world depth, three-dimensional stop-motion set feeling, deep focus, saturated-but-shadowy color, physically weighted surfaces
Settings: {'steps': 8, 'cfg': 1.0, 'sampler': 'res_multistep', 'scheduler': 'simple', 'denoise': 0.75}

── Compiled from (your project docs) ────────────────
  • directed.md
  • story.md
  • techniques.md

── Knowledge surfaced (deterministic) ───────────────
  [strong] Prior generations (visual_generation_memory): 5 hit(s), top 0.38
      ↳ storybook stop-motion short-film production still, Coraline-inspired handmade felt and cla…
      ↳ storybook stop-motion short-film production still, Coraline-inspired handmade felt and cla…
  [strong] Technique lessons (visual_generation_memory): 4 hit(s), top 0.38
      ↳ When inpainting a screen, masking the prop's bezel/frame instead of glass-only lets the mo…
      ↳ 1152x896 wedges Z-Image (model stalls); render at 1024x1024.
  [strong] Technique reports (technique_research_outputs): 3 hit(s), top 0.38
      ↳ Theatrical Act-Break Title Cards with Hard-Cut Grammar
      ↳ Handcrafted Texture & Grain Compositing (Paper, Stitch, Canvas Overlay)
  [strong] Platform facts (user_knowledge): 5 hit(s), top 0.45
      ↳ If you encounter this situation, you have three choices: 1. **Start with zero GPUs for dat…
      ↳ Run workflows on Comfy's managed infrastructure. No GPU setup required. Run ComfyUI as a s…
  [reference] Tutorial research (tutorial_research): 5 hit(s), top 0.37
      ↳ ем так. Вот здесь у нас теперь точно 5 изображений. Не знаю, у CRT нод вот такой баг есть,…
      ↳ details and shown which parts of the lyrics were replaced later. As you can see, the style…
  [reference] Workflow templates (visual_generation_memory): 3 hit(s), top 0.34
      ↳ visual-workflow-inpaint
      ↳ visual-workflow

Rationale: Using Z-Image Turbo at cfg 1.0, 8 steps, res_multistep/simple per your confirmed technique lesson ('Z-Image Turbo renders at cfg 1.0, 8 steps, sampler res_multistep, scheduler simple'). Resolution locked to 1024x1024 per your lesson that '1152x896 wedges Z-Image.' This is an inpaint template so denoise 0.75 is set to allow the model latitude on the masked region while preserving any source frame context; no negative prompt as Z-Image zeroes the negative internally. The prompt anchors the Coraline/stop-motion visual identity consistent with all prior LIKED generations, with neon rain and empty rooftop as the scene's sole subject.

── Your own technique lessons (relevant) ────────────
  • When inpainting a screen, masking the prop's bezel/frame instead of glass-only lets the model reinterpret the whole prop and yields a framed poster, not a lit screen; mask the glass region only.
  • 1152x896 wedges Z-Image (model stalls); render at 1024x1024.
  • Inpaint with a tight, region-only mask (e.g. a screen's glass, inset inside its bezel), never the surrounding frame/prop, so the model can't reinterpret the whole object; masked inpaint tolerates denoise ~0.8 because the rest of the frame is untouched.
  • Z-Image Turbo renders at cfg 1.0, 8 steps, sampler res_multistep, scheduler simple, and uses no negative prompt (its graph zeroes the negative via ConditioningZeroOut).

Appended to: ~/agent-data/visual-generation/batches/celeste-you-dangerous.batch.md
Next: visual-generation generate ~/agent-data/visual-generation/batches/celeste-you-dangerous.batch.md --section cabc8e97-52c1-43f2-8a88-250c23f4ceeb --endpoint <url>
❯ agent visual-generation generate ~/agent-data/visual-generation/batches/celeste-you-dangerous.batch.md --section cabc8e97-52c1-43f2-8a88-250c23f4ceeb --endpoint <https://<pod-id>-8188.proxy.runpod.net/>
Usage: visual-generation generate [OPTIONS] BATCH
Try 'visual-generation generate --help' for help.

Error: Unknown section id 'cabc8e97-52c1-43f2-8a88-250c23f4ceeb'. Known specs: 044064a8-ca06-4380-8a23-50c4ac50e6d1
❯ agent visual-generation generate ~/agent-data/visual-generation/batches/celeste-you-dangerous.batch.md --section 044064a8-ca06-4380-8a23-50c4ac50e6d1 --endpoint <https://<pod-id>-8188.proxy.runpod.net/>
── GPU cost gate (soft-inform — advises, never blocks) ──
  Specs to generate:  1
  Per-run estimate:   $0.0069  (learned)
  GPU rate:           $0.69/hr (user-supplied)
  Est. session cost:  $0.0069  (≈ uptime proxy; real billing began at spin-up)
  Local cumulative:   $0.6721
Spend ~$0.0069 of GPU time on 1 generation(s)? [y/N]: y

Status:       completed
Generated:    1 spec(s)
Session cost: $0.0128  (GPU, agent-local)

── Generation 04c0fcbd-d43 (spec 044064a8-ca06-4380-8a23-50c4ac50e6d1) ──
Asset:    ~/agent-data/visual-generation/assets/celeste-you-dangerous/04c0fcbd-d437-4282-a96e-d1c86c72cdb5.png
GPU cost: $0.0124  (running $0.0124)
Recipe:   Z-Image Turbo canonical settings: cfg 1.0, 8 steps, res_multistep/simple, no negative prompt — per your verified USER FACT that the graph zeroes the negative via ConditioningZeroOut and your TECHNIQUE LESSON confirming 1024x1024 to avoid model stalls at 1152x896. The prompt leads with the Coraline stop-motion storybook visual identity established across your LIKED prior generations (felt panels, stitched seams, visible fabric weave on every surface, puppet-world physical depth), then places the narrator on a wide-angle rooftop at dusk with neon uplight from the Buenos Aires cityscape below — a new establishing shot that fits the film's theatrical chapter structure without restating locked character appearance.

── Batch drained ───────────────────────────────────
Stop your pod now to stop GPU billing — the agent issues no RunPod stop.
⚠ Idle warning: every minute the pod stays up keeps billing, even idle.

Review, then: visual-generation report <gen_id> --reaction <X>

Report: ~/obsidian/agent-reports/visual-generation/2026-06-29 01KW8WK2VTH7.md
❯ agent visual-generation report gen_id cabc8e97-52c1-43f2-8a88-250c23f4ceeb --reaction disliked --rating 2 --notes "hair is completely wrong, hair is not dreadlocks and the length is wrong character is also to tall and skinny" --context "arrival shot at the bar"
Usage: visual-generation report [OPTIONS] GEN_ID
Try 'visual-generation report --help' for help.

Error: Got unexpected extra argument (cabc8e97-52c1-43f2-8a88-250c23f4ceeb)
❯ agent visual-generation report cabc8e97-52c1-43f2-8a88-250c23f4ceeb --reaction disliked --rating 2 --notes "hair is completely wrong, hair is not dreadlocks and the length is wrong character is also to tall and skinny" --context "arrival shot at the bar"
Warning: --rating is unusual for 'disliked' (ratings are meaningful for positive reactions). Recording it anyway.
Error: generation 'cabc8e97-52c1-43f2-8a88-250c23f4ceeb' not found.
❯ agent visual-generation report cabc8e97-52c1-43f2-8a88-250c23f4ceeb --reaction disliked --rating 2 --notes "hair is completely wrong, hair is not dreadlocks and the length is wrong character is also to tall and skinny" --context "arrival shot at the bar"
Warning: --rating is unusual for 'disliked' (ratings are meaningful for positive reactions). Recording it anyway.
Error: generation 'cabc8e97-52c1-43f2-8a88-250c23f4ceeb' not found.
❯ agent visual-generation report 044064a8-ca06-4380-8a23-50c4ac50e6d1 --reaction disliked --rating 2 --notes "hair is completely wrong, hair is not dreadlocks and the length is wrong character is also to tall and skinny" --context "arrival shot at the bar"
Warning: --rating is unusual for 'disliked' (ratings are meaningful for positive reactions). Recording it anyway.
Error: generation '044064a8-ca06-4380-8a23-50c4ac50e6d1' not found.
❯ agent visual-generation report 04c0fcbd-d43 --reaction disliked --rating 2 --notes "hair is completely wrong, hair is not dreadlocks and the length is wrong character is also to tall and skinny" --context "arrival shot at the bar"
Warning: --rating is unusual for 'disliked' (ratings are meaningful for positive reactions). Recording it anyway.
Traceback (most recent call last):
  File "~/projects/agent-stack/.venv/bin/visual-generation", line 10, in <module>
    sys.exit(cli())
             ^^^^^
  File "~/projects/agent-stack/.venv/lib/python3.12/site-packages/click/core.py", line 1524, in **call**
    return self.main(*args, **kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "~/projects/agent-stack/.venv/lib/python3.12/site-packages/click/core.py", line 1445, in main
    rv = self.invoke(ctx)
         ^^^^^^^^^^^^^^^^
  File "~/projects/agent-stack/.venv/lib/python3.12/site-packages/click/core.py", line 1912, in invoke
    return _process_result(sub_ctx.command.invoke(sub_ctx))
                           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "~/projects/agent-stack/.venv/lib/python3.12/site-packages/click/core.py", line 1308, in invoke
    return ctx.invoke(self.callback,**ctx.params)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "~/projects/agent-stack/.venv/lib/python3.12/site-packages/click/core.py", line 877, in invoke
    return callback(*args, **kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^^
  File "~/projects/agent-stack/packages/visual-generation/src/visual_generation/cli.py", line 681, in report
    gen = report_sync(gen_id, reaction, rating=rating, notes=notes, context=context)
          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "~/projects/agent-stack/packages/visual-generation/src/visual_generation/report.py", line 45, in report_sync
    return asyncio.run(report(gen_id, reaction,**kwargs))
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "~/.pyenv/versions/3.12.1/lib/python3.12/asyncio/runners.py", line 194, in run
    return runner.run(main)
           ^^^^^^^^^^^^^^^^
  File "~/.pyenv/versions/3.12.1/lib/python3.12/asyncio/runners.py", line 118, in run
    return self._loop.run_until_complete(task)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "~/.pyenv/versions/3.12.1/lib/python3.12/asyncio/base_events.py", line 684, in run_until_complete
    return future.result()
           ^^^^^^^^^^^^^^^
  File "~/projects/agent-stack/packages/visual-generation/src/visual_generation/report.py", line 35, in report
    gen = await store.get_generation(gen_id)
          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "~/projects/agent-stack/packages/visual-generation/src/visual_generation/store.py", line 130, in get_generation
    records = await self._store.retrieve_points(self._collection, [entry_id])
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "~/projects/agent-stack/packages/agent-runtime/src/agent_runtime/memory/store.py", line 89, in retrieve_points
    return await self._client.retrieve(
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "~/projects/agent-stack/.venv/lib/python3.12/site-packages/qdrant_client/async_qdrant_client.py", line 1080, in retrieve
    return await self._client.retrieve(
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "~/projects/agent-stack/.venv/lib/python3.12/site-packages/qdrant_client/async_qdrant_remote.py", line 1199, in retrieve
    await self.openapi_client.points_api.get_points(
  File "~/projects/agent-stack/.venv/lib/python3.12/site-packages/qdrant_client/http/api/points_api.py", line 708, in get_points
    return await self._build_for_get_points(
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "~/projects/agent-stack/.venv/lib/python3.12/site-packages/qdrant_client/http/api_client.py", line 184, in request
    return await self.send(request, type_)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "~/projects/agent-stack/.venv/lib/python3.12/site-packages/qdrant_client/http/api_client.py", line 219, in send
    raise UnexpectedResponse.for_response(response)
qdrant_client.http.exceptions.UnexpectedResponse: Unexpected Response: 400 (Bad Request)
Raw response content:
b'{"status":{"error":"Format error in JSON body: value 04c0fcbd-d43 is not a valid point ID, valid values are either an unsigned integer or a UUID at line 1 column 64"},"time":0.0}'
❯ agent visual-generation report 044064a8-ca06-4380-8a23-50c4ac50e6d1 --reaction disliked --rating 2 --notes "hair is completely wrong, hair is not dreadlocks and the length is wrong character is also to tall and skinny" --context "arrival shot at the bar"
Warning: --rating is unusual for 'disliked' (ratings are meaningful for positive reactions). Recording it anyway.
Error: generation '044064a8-ca06-4380-8a23-50c4ac50e6d1' not found.
