# Phase 4 first job: the retrospective's lesson corrections (§B1)

`docs/agent-retrospective-corrections.md` §B1 lists three technique lessons to rewrite and three to add, and says
those are "follow-up actions for their own sessions". Doing them through the chat is the acceptance exercise for
Phase 4. This needs your real keys and Qdrant, so it is a work list for you to run, not something already applied.

```bash
op run --env-file=.env -- env EXECUTION_TRUTH_VERIFIED_SINCE= uv run visual-generation chat --project celeste-you-dangerous
```

Start with `lesson_list` (include unconfirmed) so you can see the eight lessons and their full ids. Then, for each
row below, ask the chat to do it. Every step shows a confirm panel; a *rewrite* is two steps (remove the old
lesson, add the new one). The old text is kept in the audit log (`lesson_rm` records the removed statement in
its result data), so nothing is lost by removing it.

## Rewrite (remove the old lesson, then add the corrected one)

| Old id (prefix) | What was wrong | New statement (verbatim from §B1) | scope / valence / layer / topic |
|---|---|---|---|
| `6f5638ea` "Run each character LoRA near 1.0; a two-character two-shot is 1.0 + 1.0" | known-wrong as an isolation recipe | Turbo-trained LoRAs apply at ~1.0 (2.0+ take = base-trained, retrain); strength does NOT isolate identities in multi-character frames — two-shots require per-region conditioning (sequential masked insertion), not strength pairs. | model / negative / conditioning_asset / identity |
| `7570c0d4` base-on-Turbo bleeds at 2.0+; "Fix: retrain on Turbo so it applies near 1.0" | right observation, fix over-claims | …Retraining on Turbo restores prompt adherence at ~1.0; it does not prevent cross-figure identity bleed in shared frames — that is a conditioning/routing gap no strength value fixes. | model / negative / conditioning_asset / identity |
| `878d32da` don't stack same-character LoRAs; "let canon… own which file and strength represents a character" | category-confused | Never stack two LoRA files for one character (muddy likeness). One pinned file per character prevents muddiness only — canon pinning is bookkeeping, not an identity authority. | model / negative / conditioning_asset / identity |

The `7570c0d4` row's text starts with an ellipsis in the retrospective: write out the full original sentence first
(keep its first half, which was right) and replace only the over-claiming fix. Use `lesson_list` to read it.
Use the original lesson's own scope and valence if `lesson_list` shows they differ from the table.

## Add (new lessons)

| Statement (verbatim from §B1) | scope / valence / layer / topic | claim |
|---|---|---|
| Identity bleed between two globally-applied character LoRAs is structural — no spatial routing exists; prompt phrasing ('left/right', 'must not look alike'), strength balancing, and seed sweeps cannot fix it. Two-character frames use sequential masked single-identity edits on a locked plate. | model / negative / conditioning_asset / identity | tuned |
| Text canon is a prompt macro: it raises the probability of broad semantic traits and cannot pin geometry, materials, camera, or region assignment. Identity and set authority are versioned reference images and approved plates. | workflow / negative / conditioning_asset / set | tuned |
| Validated two-shot path: solo base frame + masked inpaint insertion of the second character (gen `359471ab`, Phase-E shot 5 final); whole-frame two-LoRA generation is deprecated. | workflow / positive / conditioning_asset / set | tuned (one tuned two-shot is not validation) |

All six are conditioning-layer lessons, so none needs a `falsification_test` (that rule is for *prompt*-layer
lessons about identity, staging or set). None should be marked `validated`: that needs `evidence_n >= 5` and a
held-out evaluation, which this evidence does not have. Cite the supporting generations in the lesson's
`source_eval_ids` only if you have recorded evaluations for them.

## Check it worked

- `lesson_list` shows the three corrected lessons and the three new ones, and not the three old ones.
- The audit log (`~/agent-data/runs/<date>/visual-generation/<session>/audit.jsonl`) has, for each step, the
  arguments, your decision, and the written or removed id.
- The §B1 "STILL-VALID" lessons (`87dd8981`, `2e5fc7ee`, `2ed60fc9`, `6ea3619d`, `a3528547`) are untouched. The
  retrospective also asks for scope labels on two of them ("Z-Image ideation path"); that is a separate edit, not
  part of this list.
