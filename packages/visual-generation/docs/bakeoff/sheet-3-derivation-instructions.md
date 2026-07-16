# Sheet 3 — Hero Derivation Instruction Set (Celeste + Narrator)

How to turn the staged source images into hero candidates, per editor. Real photos remain
LOCAL-to-pod only (opsec rule from celeste-v2-design-TARGET.md); nothing derived from real
photos leaves the secured asset root unless it has fully converted to puppet.

## Source staging

Celeste (roles per celeste-v2-design-TARGET.md):
- `celeste-real-face-hero.png` — primary face + the long face-strand (IMG_6048)
- `celeste-real-outfit-fullbody.png` — outfit + shoes + true proportions (IMG_6046)
- `celeste-real-hair-bun.png` — bun volume backup (IMG_6036)

Narrator: source is the approved solo puppet render (`proof-solo-narrator-GOOD-4452cf44` lineage
gen) — already in-style, so narrator derivation is puppet→views, easier than photo→puppet.
Fall back to real photos only if the render's face fails the hero gate.

Fixed settings both editors: 1024×1024 minimum, fixed seed per attempt series (log every seed),
full-quality steps for gate candidates (Lightning/accelerated passes allowed for exploration
only — label them `explore`, they cannot enter the hero gate).

## Celeste — Qwen-Image-Edit 2511 (multi-image, image-addressed)

Inputs: image 1 = face hero photo; image 2 = outfit full-body photo. Instruction (from the
TARGET.md draft, image-addressed):

> Convert the woman from image 1 into a hand-sculpted LAIKA/Coraline stop-motion puppet: smooth
> matte clay-resin with warm cream peach-ivory skin and a subtle satin sheen (no gray, no
> freckles, no blush). Keep her real facial structure and prettiness. Small round flat black
> Coraline button eyes. Dark brown curly hair worn UP in a voluminous textured bun with a single
> long curly strand falling down in front of her face. She is smiling warmly. She wears the
> outfit from image 2: black long-sleeve collared button-down shirt, black slim jeans, a small
> pendant necklace, black low sneakers with white soles and white ankle socks. Natural slim
> real-woman proportions, not elongated or lanky. Full-body front view, plain neutral studio
> backdrop, soft even studio key light.

Iteration rules: change ONE clause per re-attempt; log which clause; three failures of the same
defect → stop per guardrail 3 and note the architecture question. Known defect→clause map to
try first: waxy skin → strengthen "matte clay-resin… subtle satin sheen, not glossy"; blush →
prepend "bare-faced, no makeup, no blush"; strand missing → move the strand clause earlier;
proportions drift → "keep the body proportions from image 2".

## Celeste — FLUX Kontext (single-image chain)

Kontext takes one input image, so identity and outfit can't ride separate references. Chain:

1. Input = `celeste-real-outfit-fullbody.png` (proportions + outfit + face in one frame),
   instruction = the same conversion text minus the image-2 clause ("She wears her black
   long-sleeve collared button-down…").
2. If the face is weak at full-body distance: second pass on the output, face-region edit
   referencing the descriptive face spec (structure, button eyes, bun + strand, smiling).

Record that Kontext heroes are a 1–2 pass chain; drift introduced by pass 2 counts against
Test B1's cumulative scoring later — don't hide it.

## Narrator — both editors

Input: the approved solo render. Instruction:

> Keep this exact stop-motion puppet character unchanged — same face, same caramel-brown clay
> skin, same mid-back dreadlocks, same black distressed long-sleeve shirt, dark denim jeans, and
> red-and-white Jordan 1 sneakers. Full-body front view, standing relaxed facing camera, plain
> neutral studio backdrop, soft even studio key light.

(The narrator hero task is a re-stage, not a conversion; it doubles as each editor's first
identity-preservation data point.)

## From approved hero → Test A pack

Per view, input = the approved hero (Qwen may add the outfit photo as image 2 for wardrobe
fidelity on turns). Instruction pattern:

> Keep this exact puppet character unchanged — same face, button eyes, hair, outfit, materials.
> Change only the camera/pose: [three-quarter view, body turned 45° | full profile facing left |
> back view, back to camera | seated on a stool, hands in lap]. Same neutral backdrop and even
> studio light.

Pose tails for later production minting (post-bake-off): hands-on-hips confident; arms crossed;
pointing + laughing — the TARGET.md defaults.

## Session order

1. Pod up (eval volume) → stage sources → narrator re-stage on both editors (fast signal).
2. Celeste hero candidates: Qwen first (expected winner on multi-ref), then Kontext chain.
3. Gate candidates on Sheet 1 as they land — pod DOWN if a gate review will exceed 15 min.
4. First approved hero per character → Test A derivations → Sheet 2 scoring.
5. B1 on the stronger Test A performer first; B2/D with the plate candidate; decision rule.
