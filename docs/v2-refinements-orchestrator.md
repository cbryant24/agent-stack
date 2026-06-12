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

**What shipped.** The **delegation seam**: `diagnostics.RemediationHandler` (a `Protocol`
with `async remediate(report) -> RemediationOutcome`), a module-level registry
(`register_remediation_handler` / `get_remediation_handler`), and
`delegate_remediation(report)` which transitions the report `open → delegated`, invokes the
registered handler, sets the report to the handler's achieved status, and rewrites the
report file at each transition. The shared report types (`DiagnosticReport` /
`RemediationSpec` / `RemediationOutcome` / `Status`) live in `agent_runtime.diagnostics`
(re-exported from `orchestrator.diagnostics`) so an owning agent can implement a handler
without importing the orchestrator. `delegate_remediation` is **not** an orchestrator tool,
so the autonomous loop can never trigger a write.

**What's built now (re-tag).** **music-curation** has the first real handler:
`MusicCurationStore.remediate(report)` executes a machine-readable `RemediationSpec`
(`kind="retag"`, a `match` payload filter, and the `set` payload changes) as a
filter-parameterized generalization of its one-shot `migrate_approved_to_liked()` — scroll
the matched points, `set_payload` on each, no re-embedding, idempotent. It validates first
(own collection, supported kind, well-formed spec) and **refuses by returning
`status="open"`** so a refused report lands back as a manual work order rather than
stranding at `delegated`. The handler is registered (`register_remediation_handlers()` in
`orchestrator/tools.py`) only for the explicit **`orchestrator remediate <report-path>`**
CLI command (load → refuse-unless-open-with-spec → show spec → confirm (`-y` to skip) →
`delegate_remediation`). The spec round-trips through the report markdown (rendered as a
`## Remediation spec` YAML block; parsed back by `load_diagnostic_report`). Reports with no
registered handler still stay `open` as a human/Claude-Code-actionable work order.

**Still deferred — re-embed.** The highest-value remediation — re-embedding a whole
collection to fix a cross-model embedding-space mismatch (`voyage-3-large` vs
`voyage-multimodal-3`) — is a bulk, irreversible-in-practice Qdrant write that is risky to
ship under-tested and needs careful validation against live data. It slots into the same
seam as a new `RemediationSpec.kind` (`"reembed"`) + handler branch, built deliberately
once the re-tag path is proven. Remediation handlers for the **other owning agents**
(voiceover-direction, visual-generation, …) are likewise follow-ups on the same seam.

**How another handler lands (the seam).** For each owning agent:
1. Add `async remediate(self, report) -> RemediationOutcome` on the agent's store
   (matching the `RemediationHandler` protocol structurally), executing the report's
   `RemediationSpec` under the agent's ownership; validate-and-refuse before writing.
2. Register it in `register_remediation_handlers()` (`orchestrator/tools.py`).
3. The `orchestrator remediate` CLI path already handles load → confirm → status
   transitions → report rewrite.

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
