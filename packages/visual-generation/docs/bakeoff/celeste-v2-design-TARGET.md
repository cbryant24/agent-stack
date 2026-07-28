# Celeste v2 — hero reference design (2026-07-10)

Director-locked redesign of Celeste for the reference/edit bake-off. Supersedes the
Phase-C puppet refs (`refsheets/celeste/`), which the director rejected as too
long/lanky/thin/awkward, too sad, wrong hair, wrong outfit. Anchored on 5 new, clearer
real photos of Celeste (`refs/IMG_60{36,45,46,47,48}.PNG`, staged here role-named).
Real photos stay LOCAL — used only as reference/img2img sources on our own pod.

## Locked spec

- **Identity/proportions:** her real face + slim natural real-woman proportions (fixes lanky).
- **Face:** pretty, kept structure, **smooth clean skin — NO freckles**.
- **Eyes:** Coraline **button eyes** (kept — consistent with the narrator).
- **Hair:** dark brown, curly/textured, worn **UP in a voluminous bun**, with **one long
  curly strand hanging down in front of her face** (per `celeste-real-face-hero.png`).
- **Expression:** **smiling by default.**
- **Skin:** warm moderate peach-ivory clay, subtle satin sheen, **no gray, no blush**.
- **Outfit:** black long-sleeve collared button-down + black slim jeans + small pendant
  necklace (+ thin bracelet).
- **Shoes:** black low sneakers with **white soles + white ankle socks** (corrects the old
  Chuck-Taylor canon).
- **Style:** LAIKA/Coraline hand-sculpted clay-resin puppet, matte with satin sheen.
- **Default poses to mint:** (1) both hands on hips, confident "superman"; (2) arms crossed.

## Reference roles (this folder)

| file | source | role |
|---|---|---|
| `celeste-real-face-hero.png` | IMG_6048 | primary face + the long face-strand |
| `celeste-real-hair-bun.png` | IMG_6036 | curly bun volume + collar |
| `celeste-real-face-profile.png` | IMG_6045 | backup face/profile |
| `celeste-real-outfit-fullbody.png` | IMG_6046 | outfit + shoes + true proportions (best full body) |
| `celeste-real-outfit-profile.png` | IMG_6047 | secondary full-body |

## Qwen-Edit instruction (draft)

> Convert the woman in the reference photos into a hand-sculpted LAIKA/Coraline
> stop-motion puppet: smooth matte clay-resin with warm cream peach-ivory skin and a
> subtle satin sheen (no gray, no freckles, no blush). Keep her real facial structure
> and prettiness. Small round black Coraline button eyes. Dark brown curly hair worn UP
> in a voluminous textured bun with a single long curly strand falling down in front of
> her face. She is smiling warmly. Black long-sleeve collared button-down shirt, black
> slim jeans, a small pendant necklace, black low sneakers with white soles and white
> ankle socks. Natural slim real-woman proportions, not elongated or lanky. Full-body
> front view, plain neutral studio backdrop, soft theatrical key light, shallow DOF.

Pose tails: "…standing with both hands on her hips in a confident stance, smiling." /
"…standing with her arms crossed, smiling."

## Follow-ups (after a render validates the design)
- Update canon Celeste (`canon edit`): hair→curly bun + face-strand; add forbids
  `freckles`, `blush`; shoes→white-soled black sneakers; remove obsolete straight-hair /
  Chuck-Taylor locks. Do NOT lock canon to this until a render is director-approved.
