# Golden feedback strings

`feedback.jsonl` holds real feedback strings for `propose_interpretation`. One JSON object per line;
lines starting with `#` are ignored.

```json
{"feedback": "<your words, exactly as you said them>", "context_labels": ["attempt-03"], "attempts": 8}
```

- `feedback` (required): the sentence(s) as you wrote them.
- `context_labels` (optional): labels the feedback mentions, so the live test knows which should
  resolve. A label beyond `attempts` is expected to land in `open_questions`.
- `attempts` (optional, default 8): how many generations the test project has when the string is run.

Replace the 3 examples with up to 20 real strings from your records (an unresolvable label such as
`attempt-14` is a useful case to keep). The offline test only checks this format. The live test
(`AGENT_SHELL_LIVE=1`, skipped by default) gives each string to a real model and asserts the tool
produced a valid interpretation and that every unresolved label is in `open_questions`.
