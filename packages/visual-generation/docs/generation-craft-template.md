---
title: "MODEL-NAME-craft"
document_type: "living-generation-craft-guide"
model: "MODEL NAME / VERSION"
modality: "image | video | audio | multimodal"
status: "active"
version: "0.1.0"
created: "YYYY-MM-DD"
last_updated: "YYYY-MM-DD"
maintainer: "NAME"
evidence_scope: "project-specific empirical results + external references"
next_planned_model: "optional"
---

# MODEL-NAME Craft

## Purpose

This is a living, evidence-based craft document for **[MODEL NAME / VERSION]**.

It records:

- settings and workflows that produced usable results;
- exact prompt terms and phrases that repeatedly worked;
- phrases that appeared promising but are not yet reliable;
- failed approaches and the conditions under which they failed;
- ratings, reactions, and generation context;
- targeted revisions or redrafts and their outcomes;
- model limitations and practical mitigations;
- externally sourced best practices that may confirm, contradict, or qualify internal experience.

This document is not a generic prompt guide. It is a project memory and decision system grounded in generated outputs.

---

# Instructions for a New LLM Chat

## Read this document before helping

When this document is provided to an LLM:

1. Read the entire document before proposing a prompt, workflow, redraft, or settings change.
2. Distinguish between:
   - **Locked**: repeatedly successful or explicitly approved and should be preserved verbatim unless the user asks to change it.
   - **Supported**: worked at least once and is worth reusing, but is not proven universal.
   - **Experimental**: plausible or externally recommended, but not yet validated in this project.
   - **Failed / risky**: produced an unwanted result or has a documented reliability problem.
   - **External guidance**: sourced outside the project and not automatically equivalent to an internally validated result.
3. Never convert a warning into a prohibition. State the known risk, expected cost, and mitigation, then follow the user’s creative direction.
4. Do not treat one render as proof of universal model behavior.
5. Preserve exact locked wording when the document says **verbatim**.
6. When a requested change conflicts with a locked phrase or known limitation, identify the conflict explicitly before drafting.
7. Prefer targeted changes over total prompt rewrites when the user wants continuity.
8. Keep unchanged character, camera, style, and recipe blocks intact unless the requested change requires otherwise.
9. Do not silently simplify, merge, or summarize exact character attributes marked as separate or locked.
10. After generation, always move to evaluation/update unless the user explicitly says not to report it.

## How to use this document for generation

Before writing a generation prompt:

1. Identify the model, workflow, modality, and requested outcome.
2. Pull the relevant locked recipe, prompt blocks, known successful phrases, and failure warnings.
3. Separate the request into:
   - preserve;
   - change;
   - experiment;
   - post-process later.
4. Check whether the requested composition creates a documented risk.
5. Write the prompt using the strongest internally validated wording first.
6. Keep each important character or object requirement inside that subject’s own description when attribute merging is a known failure mode.
7. Use positive, concrete visual descriptions before abstract references.
8. Recommend post-processing or inpaint only as a mitigation, not as a reason to block experimentation.
9. State which parts are expected to be reliable and which remain uncertain.
10. After generation, ask for or derive a report.

## How to update this document

When the user asks to add a result:

1. Record the generation identifier, date, model, workflow, seed, dimensions, settings, prompt, and output path when available.
2. Preserve the user’s feedback verbatim in the generation record.
3. Derive:
   - reaction;
   - rating;
   - what worked;
   - what failed;
   - what should remain locked;
   - what should change next;
   - any new hypothesis.
4. Record the exact redraft/refinement instruction used.
5. Record the resulting authored prompt, not only the short change instruction.
6. After the next generation, connect the outcome to the prior hypothesis.
7. Promote a technique to **Locked** only when it has repeated success, was explicitly locked by the user, or is a deterministic workflow fact.
8. Mark a technique **Supported** after one clear success.
9. Mark it **Experimental** when untested or externally sourced.
10. Mark it **Failed / risky** with the exact conditions of failure.
11. Never delete contradictory evidence. Add a reconciliation note.
12. Update the changelog.

---

# Evidence Rules

## Confidence labels

| Label | Meaning | Required treatment |
|---|---|---|
| **LOCKED** | Repeatedly successful, deterministically verified, or explicitly approved | Preserve verbatim unless asked to change |
| **SUPPORTED** | Worked in at least one relevant generation | Reuse with a confidence note |
| **EXPERIMENTAL** | Plausible but not validated internally | Test deliberately |
| **RISKY** | Known failure pattern under specific conditions | Warn, do not block |
| **FAILED** | Did not achieve the requested result | Preserve as negative evidence |
| **EXTERNAL** | Sourced outside this project | Keep separate until internally validated |
| **SUPERSEDED** | Replaced by better evidence | Retain for history |

## Evidence hierarchy

Use this order when sources conflict:

1. The user’s explicit current creative instruction.
2. A user-approved locked generation or phrase.
3. Repeated internal empirical results under similar conditions.
4. Single internal empirical result.
5. Official model documentation and implementation guidance.
6. Third-party tutorials or community claims.
7. General diffusion-model assumptions.

External guidance may challenge an internal assumption, but it must not silently overwrite project evidence.

---

# Model Identity and Environment

## Model

- **Model name:**
- **Checkpoint / identifier:**
- **Version / hash:**
- **Architecture:**
- **Text encoder:**
- **VAE:**
- **Precision:**
- **Runtime:**
- **Workflow:**
- **Hardware:**
- **VRAM:**

## Known workflow variants

| Workflow | Purpose | Inputs | Outputs | Status |
|---|---|---|---|---|
| Text-to-image | New generation | Prompt, seed, recipe | Image | |
| Image-to-image | Global refinement | Source image, prompt, denoise | Image | |
| Inpaint | Local correction | Source, mask, prompt, denoise | Image | |
| Video generation | Motion synthesis | Prompt, image/video source | Video | |
| Other | | | | |

---

# Locked Recipe

| Parameter | Locked value | Confidence | Evidence |
|---|---:|---|---|
| Steps / NFEs | | | |
| CFG / guidance | | | |
| Sampler | | | |
| Scheduler | | | |
| Width × height | | | |
| Seed strategy | | | |
| Negative prompt behavior | | | |
| LoRA stack | | | |
| Other | | | |

## Recipe cautions

- 
- 

---

# Prompt Construction Framework

## Prompt order

1. Highest-priority correction or defining visual requirement.
2. Medium/style and surface construction.
3. Camera position and framing.
4. Primary subject, with full non-merged attribute block.
5. Secondary subject, with full non-merged attribute block.
6. Spatial relationships and depth.
7. Lighting.
8. Environment and props.
9. Rendering finish and production quality.
10. Explicitly preserved elements.

## Stable prompt blocks

### Style block

```text
[exact reusable style language]
```

### Character A block

```text
[exact reusable character language]
```

### Character B block

```text
[exact reusable character language]
```

### Camera block

```text
[exact reusable camera language]
```

### Lighting block

```text
[exact reusable lighting language]
```

### Finish block

```text
[exact reusable finish language]
```

---

# Technique Ledger

## Locked techniques

### Technique: [name]

- **Status:** LOCKED
- **Exact phrase / setting:**
- **What it controls:**
- **Conditions where it worked:**
- **Known conflicts:**
- **Evidence generations:**
- **Do not rewrite as:**

## Supported techniques

### Technique: [name]

- **Status:** SUPPORTED
- **Exact phrase / setting:**
- **Observed outcome:**
- **Confidence limitation:**
- **Evidence generations:**

## Experimental techniques

### Technique: [name]

- **Status:** EXPERIMENTAL
- **Hypothesis:**
- **Proposed wording / settings:**
- **Test design:**
- **Success criteria:**
- **Failure criteria:**

## Failed or risky techniques

### Technique: [name]

- **Status:** FAILED | RISKY
- **Exact wording / condition:**
- **Observed failure:**
- **Likely cause:**
- **Mitigation:**
- **Evidence generations:**

---

# Subject and Attribute Consistency

## Character / subject registry

| Subject | Locked identity block | Variable attributes | Identity-bearing assets |
|---|---|---|---|
| | | | |

## Attribute collision rules

- Do not merge attributes between subjects.
- Repeat critical attributes inside each subject block when omission or transfer has occurred.
- State one color, material, or action per object when combinations have been misread.
- Keep facial details readable by matching requested detail to subject size in frame.
- Treat identity LoRAs, reference images, trigger tokens, and locked descriptor blocks as recipe-level continuity controls.

---

# Composition and Camera Ledger

| Composition | Result | Confidence | Notes |
|---|---|---|---|
| Solo close shot | | | |
| Two-person same depth | | | |
| Two-person different depths | | | |
| Face-forward two-shot | | | |
| Over-the-shoulder | | | |
| POV | | | |
| Wide shot | | | |
| Other | | | |

## Camera wording that worked

```text
[exact phrases]
```

## Camera wording that failed or was unreliable

```text
[exact phrases]
```

---

# Lighting Ledger

| Lighting phrase | Result | Status | Evidence |
|---|---|---|---|
| | | | |

---

# Text, Logos, Clothing Graphics, and Fine Detail

## Text rendering

- Internal result:
- External guidance:
- Current policy:

## Clothing graphics and logos

- Internal result:
- Current policy:
- Composite/post-process plan:

## Fine facial details

- Internal result:
- At-risk compositions:
- Prompt-level mitigation:
- Workflow-level mitigation:

---

# Refinement and Inpaint Rules

## When to redraft

Use redraft when:

- the result should remain a fresh text-to-image generation;
- the parent recipe and seed should remain locked;
- the requested change is primarily prompt, composition, wardrobe, or lighting language;
- lineage to the prior generation should be recorded.

## When not to redraft

Prefer refinement or inpaint when:

- the composition is already correct;
- a small local region is wrong;
- the model repeatedly fails to resolve a tiny detail;
- preserving exact pixels outside the edit is more important than rerendering.

## Mask rules

- Mask only the intended editable region.
- Keep masks inset from frames, bezels, and adjacent props unless those should also change.
- Record denoise and mask extent.
- Save the pre-edit generation as the parent.

---

# Evaluation and Reporting Protocol

## Default rule

After every generation, report it unless the user explicitly says not to.

## Rating scale

| Rating | Reaction | Meaning |
|---:|---|---|
| 5 | loved | Keeper; requested outcome landed |
| 4 | loved or liked_with_changes | Strong; minor or isolated fixes remain |
| 3 | liked_with_changes | Useful direction; meaningful changes remain |
| 2 | disliked-ish | Weak; mostly off-target |
| 1 | disliked | Wrong direction or discard |
| N/A | render_failed | Technical failure; do not judge visual quality |

## Report fields

- **Context:** Why the user reacted that way; what worked and should inform future generations.
- **Notes:** What should change next; consumed by the next directed revision when supported.
- **Reaction:** Categorical evaluation.
- **Rating:** Numeric strength of evaluation.

## Generation record template

### Generation: `[gen_id]`

- **Date:**
- **Parent / revised from:**
- **Model / checkpoint:**
- **Workflow:**
- **Seed:**
- **Settings:**
- **Prompt:**
- **Asset:**
- **Reaction:**
- **Rating:**
- **User feedback, verbatim:**
- **Context:**
- **Notes:**
- **What worked:**
- **What failed:**
- **New locked phrases:**
- **New risks:**
- **Next action:**
- **Result of next action:**

---

# Directed Revision Template

## Preserve

```text
Keep verbatim:
- [staging]
- [poses]
- [framing]
- [identity blocks]
- [lighting]
- [wardrobe]
- [successful props]
```

## Apply only these changes

```text
1. 
2. 
3. 
```

## Critical non-merging instruction

```text
Repeat each critical attribute inside the corresponding subject description. Do not summarize, merge, or replace the separate descriptions with “matching,” “same,” or “both have.”
```

## Risk statement

- **Known risk:**
- **Why it may occur:**
- **Prompt-level mitigation:**
- **Workflow-level fallback:**
- **Cost / iteration impact:**

---

# External Best Practices

## Source handling rules

For each external claim:

- cite the source;
- note whether it is official, implementation documentation, research, or community guidance;
- state whether it agrees with, contradicts, or has not yet been tested against internal evidence;
- do not label it locked until internally validated.

## External claim template

### Claim: [claim]

- **Source:**
- **Source class:** official | implementation | paper | community
- **Published / accessed:**
- **Guidance:**
- **Relationship to internal evidence:** confirms | contradicts | qualifies | untested
- **Internal validation status:**
- **Planned test:**

---

# Contradiction Register

| Internal claim | External claim | Resolution | Status |
|---|---|---|---|
| | | | |

---

# Open Experiments

## Experiment: [name]

- **Question:**
- **Parent generation:**
- **Controlled variables:**
- **Changed variable:**
- **Prompt:**
- **Settings:**
- **Expected outcome:**
- **Observed outcome:**
- **Decision:**

---

# Post-Production Ledger

| Element | Why deferred | Tool | Instructions | Status |
|---|---|---|---|---|
| Text/logo | | | | |
| Background blur | | | | |
| Color correction | | | | |
| Other | | | | |

---

# Changelog

## YYYY-MM-DD

- Added:
- Changed:
- Evidence:
- Confidence promotions/demotions:
