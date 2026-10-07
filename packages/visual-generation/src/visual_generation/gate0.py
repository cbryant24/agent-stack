"""Gate 0 (evaluation-charter): is the recorded execution the real execution?

A read-only check over a finished Gate 0 run. It reads the provenance saved beside each output
and the stored records, and judges the charter's criteria:

  1. each saved seed equals the sampler seed in the submitted graph;
  2. the random-seed generations used different seeds;
  3. the fixed-seed generation used the requested seed;
  4. replay inputs are preserved (graph file, hashes, outputs, sources all present and matching);
  5. a spec needing an unsupported slot is refused before submission.

It spends nothing and never contacts a pod. `render_record` turns the result into a saved record.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from visual_generation.batch_file import write_batch
from visual_generation.generate import plan_generation
from visual_generation.models import GenerationBatch, VisualGeneration, VisualSpec
from visual_generation.provenance import graph_seed, sha256_hex

DEFAULT_FIXED_SEED = 12345
REQUIRED_RANDOM = 2


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


@dataclass
class GenRow:
    gen: VisualGeneration
    prov: dict[str, Any] | None
    note: str = ""            # why provenance could not be loaded, if it could not


@dataclass
class Gate0Report:
    project: str
    template_name: str
    fixed_seed: int
    created_at: str
    git_commit: str | None = None
    working_tree: str | None = None
    rows: list[GenRow] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)

    @property
    def generations(self) -> list[VisualGeneration]:
        return [r.gen for r in self.rows]

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(c.passed for c in self.checks)


def _short(g: VisualGeneration) -> str:
    return g.entry_id[:8]


def _load_row(gen: VisualGeneration) -> GenRow:
    if not gen.provenance_path:
        return GenRow(gen, None, "no provenance recorded (made before provenance existed?)")
    path = Path(gen.provenance_path)
    if not path.is_file():
        return GenRow(gen, None, f"provenance file missing: {path}")
    try:
        return GenRow(gen, json.loads(path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as e:
        return GenRow(gen, None, f"provenance file unreadable: {e}")


def _graph_file_seed(prov: dict[str, Any]) -> tuple[int | None, str]:
    """The sampler seed read from the saved graph file itself (not from the provenance claims)."""
    p = Path(prov.get("submitted_graph_path", ""))
    if not p.is_file():
        return None, f"graph file missing: {p}"
    return graph_seed(p.read_bytes(), {"seed": prov.get("seed_slot")}), ""


def _check_seed_matches(rows: list[GenRow]) -> Check:
    name = "seed_matches_graph"
    if not rows:
        return Check(name, False, "no generations found in this project")
    bad: list[str] = []
    for r in rows:
        if r.prov is None:
            bad.append(f"{_short(r.gen)}: {r.note}")
            continue
        file_seed, why = _graph_file_seed(r.prov)
        values = {"record": r.gen.seed, "provenance": r.prov.get("resolved_seed"),
                  "graph recorded": r.prov.get("graph_seed"), "graph file": file_seed}
        if why or len(set(values.values())) != 1 or file_seed is None:
            bad.append(f"{_short(r.gen)}: " + (why or ", ".join(f"{k}={v}" for k, v in values.items())))
    if bad:
        return Check(name, False, "; ".join(bad))
    return Check(name, True, f"{len(rows)} generation(s): record, provenance and the submitted graph agree")


def _check_random_differ(rows: list[GenRow]) -> Check:
    name = "random_seeds_differ"
    seeds = [r.gen.seed for r in rows if r.prov and r.prov.get("seed_strategy") == "random"]
    if len(seeds) < REQUIRED_RANDOM:
        return Check(name, False, f"need {REQUIRED_RANDOM} random-seed generations, found {len(seeds)}")
    dupes = sorted({s for s in seeds if seeds.count(s) > 1}, key=str)
    if dupes:
        return Check(name, False, f"seed(s) repeated across random runs: {', '.join(str(d) for d in dupes)}")
    return Check(name, True, f"{len(seeds)} random-seed runs, all different: {', '.join(str(s) for s in seeds)}")


def _check_fixed(rows: list[GenRow], fixed_seed: int) -> Check:
    name = "fixed_seed_honored"
    fixed = [r for r in rows if r.prov and r.prov.get("seed_strategy") == "fixed"]
    if not fixed:
        return Check(name, False, "need 1 fixed-seed generation, found 0")
    wrong = [f"{_short(r.gen)} used {r.gen.seed}" for r in fixed if r.gen.seed != fixed_seed]
    if wrong:
        return Check(name, False, f"requested {fixed_seed}; " + "; ".join(wrong))
    return Check(name, True, f"fixed seed {fixed_seed} was submitted and recorded exactly")


def _file_problems(r: GenRow) -> list[str]:
    g, prov = r.gen, r.prov
    if prov is None:
        return [r.note]
    out: list[str] = []
    gp = Path(prov.get("submitted_graph_path", ""))
    if not gp.is_file():
        out.append(f"graph file missing ({gp})")
    else:
        digest = sha256_hex(gp.read_bytes())
        if digest != prov.get("submitted_graph_sha256") or digest != g.submitted_graph_sha256:
            out.append("graph file hash does not match the recorded hash")
    for o in prov.get("outputs", []):
        op = Path(o.get("path", ""))
        if not op.is_file():
            out.append(f"output file missing ({op})")
        elif sha256_hex(op.read_bytes()) != o.get("sha256"):
            out.append("output file hash does not match the recorded hash")
    for s in prov.get("sources", []):
        sp = Path(s.get("local_path", ""))
        if not sp.is_file():
            out.append(f"source {s.get('role')} missing ({sp})")
        elif sha256_hex(sp.read_bytes()) != s.get("sha256"):
            out.append(f"source {s.get('role')} hash does not match what was uploaded")
    return out


def _check_replay(rows: list[GenRow]) -> Check:
    name = "replay_inputs_preserved"
    if not rows:
        return Check(name, False, "no generations found in this project")
    bad = [f"{_short(r.gen)}: {p}" for r in rows for p in _file_problems(r)]
    if bad:
        return Check(name, False, "; ".join(bad))
    return Check(name, True, "graph, output and source files present, hashes match the records")


class _NoSeedSlotStore:
    """Serves the registered template with its seed slot removed, to ask the real planner what it does."""

    def __init__(self, store: Any, template: Any) -> None:
        self._store = store
        self._template = template

    async def ensure_collection(self) -> None:
        await self._store.ensure_collection()

    async def get_template_by_name(self, name: str) -> Any:
        return self._template

    async def recent_generation_costs(self, limit: int = 20) -> list[float]:
        return []

    def get_model(self, name: str) -> Any:
        return None


async def _check_refusal(store: Any, template_name: str) -> Check:
    name = "unsupported_slot_refused"
    await store.ensure_collection()
    template = await store.get_template_by_name(template_name)
    if template is None:
        return Check(name, False, f"template {template_name!r} is not registered, so the refusal could not be tested")
    variant = template.model_copy(update={"slot_map": {k: v for k, v in template.slot_map.items() if k != "seed"}})
    probe = VisualSpec(heading="gate0 refusal probe", prompt="probe", seed=1, seed_strategy="fixed",
                       workflow_ref=template_name, project="gate0")
    wrapper = _NoSeedSlotStore(store, variant)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "probe.batch.md"
        write_batch(GenerationBatch(project="gate0", specs=[probe]), path)
        plan = await plan_generation(path, all_sections=True, store=wrapper, memory_store=wrapper)  # type: ignore[arg-type]
    if plan.plans or probe.spec_id not in plan.skipped:
        return Check(name, False, "the planner accepted a spec whose template has no seed slot")
    reason = plan.skip_reasons.get(probe.spec_id, "")
    return Check(name, True, f"refused before submission: {reason}")


def _git(*args: str) -> str | None:
    try:
        r = subprocess.run(["git", *args], capture_output=True, text=True, timeout=10,
                           cwd=Path(__file__).parent)
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


async def verify_gate0(
    project: str, *, store: Any, template_name: str, fixed_seed: int = DEFAULT_FIXED_SEED
) -> Gate0Report:
    """Judge a finished Gate 0 run for `project`. Reads only; spends nothing."""
    await store.ensure_collection()
    gens = [g for g in await store.list_generations(project=project)]
    rows = [_load_row(g) for g in gens]
    dirty = _git("status", "--porcelain")
    report = Gate0Report(
        project=project, template_name=template_name, fixed_seed=fixed_seed,
        created_at=datetime.now(UTC).isoformat(), git_commit=_git("rev-parse", "HEAD"),
        working_tree=None if dirty is None else ("dirty" if dirty else "clean"), rows=rows,
    )
    report.checks = [
        _check_seed_matches(rows),
        _check_random_differ(rows),
        _check_fixed(rows, fixed_seed),
        _check_replay(rows),
        await _check_refusal(store, template_name),
    ]
    return report


def render_record(report: Gate0Report) -> str:
    """The Gate 0 result as a saved record (evaluation-charter attempt-record fields)."""
    verdict = "PASS" if report.passed else "FAIL"
    lines = [
        f"# Gate 0 result: {verdict}",
        "",
        f"Recorded {report.created_at} for project `{report.project}` (template `{report.template_name}`).",
        "",
        "| Criterion | Result | Detail |",
        "|---|---|---|",
    ]
    lines += [f"| {c.name} | {'PASS' if c.passed else 'FAIL'} | {c.detail.replace('|', '/')} |" for c in report.checks]
    lines += [
        "", "## Attempt record", "", "```yaml",
        f"attempt_id: gate0-{report.created_at[:10]}",
        f"project_id: {report.project}",
        "evaluation_case: Gate 0 - execution truth",
        "question: Does each saved record's seed equal the seed in the graph that was submitted?",
        "acceptance_gate: evaluation-charter.md Gate 0",
        "environment:",
        f"  git_commit: {report.git_commit}",
        f"  working_tree_status: {report.working_tree}",
        "execution:",
        f"  fixed_seed_requested: {report.fixed_seed}",
        "  generations:",
    ]
    for r in report.rows:
        p = r.prov or {}
        lines += [
            f"    - generation_id: {r.gen.entry_id}",
            f"      prompt_id: {p.get('prompt_id')}",
            f"      seed_strategy: {p.get('seed_strategy')}",
            f"      resolved_seed: {p.get('resolved_seed')}",
            f"      graph_seed: {p.get('graph_seed')}",
            f"      workflow_name: {(p.get('workflow') or {}).get('name')}",
            f"      workflow_sha256: {(p.get('workflow') or {}).get('sha256')}",
            f"      submitted_graph_path: {p.get('submitted_graph_path')}",
            f"      submitted_graph_sha256: {p.get('submitted_graph_sha256')}",
            f"      output_files: {[o.get('path') for o in p.get('outputs', [])]}",
            f"      output_sha256: {[o.get('sha256') for o in p.get('outputs', [])]}",
        ]
    lines += [
        "results:",
        f"  agent_status: {'agent-pass' if report.passed else 'unresolved'}",
        f"  observed: {[c.name for c in report.checks if c.passed]}",
        f"  unresolved: {[c.name for c in report.checks if not c.passed]}",
        "  director_signoff: false",
        "```",
        "",
        "Set `EXECUTION_TRUTH_VERIFIED_SINCE` to the date this passes only after the director signs off.",
    ]
    return "\n".join(lines) + "\n"
