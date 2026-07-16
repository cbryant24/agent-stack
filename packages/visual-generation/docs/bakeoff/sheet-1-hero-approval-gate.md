# Sheet 1 — Hero Approval Gate (audit Phase 1)

One sheet per hero candidate. A hero passes only when **every** criterion is PASS and director
sign-off is recorded. No multi-view derivation starts on an unapproved hero. Per guardrail 2,
the candidate image is labeled with full lineage before scoring.

```
Candidate ID: ______________   Character: [ ] Celeste   [ ] Narrator
Source lineage (model, workflow, seed, source refs, gen-id): ______________________________
Date: __________   Session: __________
```

## Universal criteria (audit Phase 1)

| # | Criterion | Definition of PASS | P/F | Notes |
|---|---|---|---|---|
| 1 | Face structure | Reads as the real person's facial structure translated to puppet; would be recognized side-by-side with the reference photo | | |
| 2 | Button eyes | Small, round, flat black; matched size; symmetric placement; catch-light consistent | | |
| 3 | Hair topology | Correct style per character spec (below); sculpted-strand look with soft lacquered gloss, no yarn/fiber | | |
| 4 | Proportions | Natural real-person proportions; not elongated, lanky, or chibi | | |
| 5 | Material treatment | Smooth matte clay-resin skin with subtle satin sheen; fabric texture on garments only, never on skin; no waxy CGI gloss | | |
| 6 | Wardrobe & shoes | Exact per character spec (below), no substitutions | | |
| 7 | Neutral lighting | Soft even key, no colored cast, no dramatic mood lighting baked into the identity | | |
| 8 | No background dependence | Plain neutral backdrop; identity readable if background replaced | | |
| 9 | Resolution & cleanliness | ≥1024px on the short edge; no artifacts on face, hands, or wardrobe edges | | |
| 10 | Director sign-off | Explicit, recorded (date + note) | | |

## Character spec — Celeste (from celeste-v2-design-TARGET.md)

- Smooth clean skin — **no freckles, no blush, no gray**; warm peach-ivory clay.
- Dark brown curly hair **up in a voluminous textured bun**, **one long curly strand** falling in
  front of her face.
- **Smiling by default.**
- Black long-sleeve collared button-down, black slim jeans, small pendant necklace (+ thin
  bracelet), black low sneakers with **white soles + white ankle socks**.

## Character spec — Narrator (from canon)

- Warm medium caramel-brown smooth sculpted clay skin, subtle satin sheen.
- Clean-shaven, **no facial hair**. Long dreadlocks to mid-back.
- Long black distressed long-sleeve shirt, dark denim jeans, red-and-white Jordan 1s.

## Result

```
[ ] APPROVED — hero_id assigned: ______________ (e.g. celeste_hero_v1)
[ ] REJECTED — failing criteria #s: __________  disposition: [ ] re-derive  [ ] re-source photo
Sign-off: ______________   Date: __________
```

Failure discipline (guardrail 3): three rejected candidates from the same derivation recipe →
stop, write the architecture question (is the recipe, the source photo, or the editor at
fault?), change exactly one variable before candidate 4.
