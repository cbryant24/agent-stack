# Sample outputs

Real, chained sample outputs from one project run through the agent stack. Each
file is the actual output of one agent, feeding the next — useful as a concrete
reference for what each stage produces.

The chain:

1. `script-draft.md` — a sample **concept-script** output.
2. `script-draft.directed.md` — the **voiceover-direction** `direct` output over (1).
3. `script-draft.edit-brief.md` — the **edit-brief** `draft` output over (2).

`script-draft.edit-brief.md` does double duty: it is also the live fixture for
the **feedback-iteration** smoke test
(`packages/feedback-iteration/tests/test_smoke_fixture.py`, with the parser test
in `conftest.py` reading it too). Keep it a valid, parseable edit brief if you
edit it.
