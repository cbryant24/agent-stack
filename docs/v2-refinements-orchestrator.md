---
title: Orchestrator — v2 Refinements (captured, not built)
type: v2-refinements
agent: orchestrator
project: agent-stack
status: active
---

# Orchestrator — v2 Refinements

The durable record of captured-but-not-built orchestrator items: things deliberately
deferred past Phase 3 because they're larger/architectural or exceed the smaller-touch
bar. Each entry states the item, why it was deferred, and the seam it will land on so a
later build doesn't re-derive the design.

## Per-agent remediation entry points (the diagnostics write paths)

**What.** The orchestrator's vector-DB diagnostics shipped **diagnose-only** (read-only
inspection + behavioral probe + a diagnostic report; see
`ai-director-agent-system.md` → Orchestrator → "Vector-DB diagnostics", and
`orchestrator/diagnostics.py`). The design has the orchestrator **delegate** each fix to
the owning agent, which performs the actual Qdrant write (re-embed / re-tag payload /
move points) under its own ownership — preserving the rule that only an owner writes to
its own collection, and only `UserKnowledgeStore` writes to `user_knowledge`. The
orchestrator never writes to Qdrant.

**What shipped.** The **delegation seam** is built and stub-tested:
`diagnostics.RemediationHandler` (a `Protocol` with `async remediate(report) ->
RemediationOutcome`), a module-level registry (`register_remediation_handler` /
`get_remediation_handler`), and `delegate_remediation(report)` which transitions the
report `open → delegated`, invokes the registered handler (which flips it to `fixed`),
and rewrites the report file. The registry **ships empty** — no agent registers a
handler — and `delegate_remediation` is **not** exposed as an orchestrator tool, so the
autonomous loop cannot trigger any write. With no handler, each diagnostic report stays
`open` and doubles as a human/Claude-Code-actionable work order.

**Why deferred.** Wiring a real remediation entry point into every owning agent exceeds
Phase 3's smaller-touch bar. The highest-value remediation — re-embedding a whole
collection to fix a cross-model embedding-space mismatch (`voyage-3-large` vs
`voyage-multimodal-3`) — is a bulk, irreversible-in-practice Qdrant write that is risky
to ship under-tested, and it needs careful validation against live data. Building it
deliberately (one agent at a time, well-tested) is the right shape, not a Phase 3
drive-by.

**How it lands later (the seam).** For each owning agent, in v2:
1. Add a remediation entry point on the agent (a method on its store / a library
   function) that accepts a `DiagnosticReport` and performs the write under the agent's
   ownership, returning a `RemediationOutcome`.
2. `register_remediation_handler("<agent-name>", handler)` at agent/orchestrator wiring
   time.
3. Add a `delegate_remediation` orchestrator tool (or a CLI/admin path) so a diagnosed
   report can be handed off; the seam already handles the status transitions and report
   rewrite.

**Cheapest first candidate.** **music-curation** already has the simplest write surface:
`MusicCurationStore` owns `scroll` + `MemoryStore.set_payload`, and there's precedent in
its one-shot `migrate_approved_to_liked()` (`music_curation/store.py`). A **re-tag**
remediation (rewrite a payload field, no re-embedding) is the smallest proof of the
end-to-end `open → delegated → fixed` path. The riskier **re-embed** remediation (the
actual cross-model fix) should follow once the re-tag path is proven.

## Per-session cost ceiling

**What.** A cumulative cost ceiling across a conversation session, beyond the existing
per-turn `BudgetEnvelope`. The orchestrator CLI already surfaces a **soft per-session
cumulative cost tally** (inform-only).

**Why deferred.** Low-value polish — the soft tally already gives the user visibility
into accumulated spend, which is the main need. Building a ceiling on top of it isn't
worth a slice on its own.

**Constraint if ever built — warn-only, never a hard cap.** A checkpointed thread is
meant to **resume across sessions**, so a cumulative hard cap would either brick a useful
thread or govern nothing (the user just starts a new session). Any future ceiling must be
a **soft warning threshold** that informs and keeps going, not a hard brick. The per-turn
`BudgetEnvelope` remains the real enforcement boundary.
