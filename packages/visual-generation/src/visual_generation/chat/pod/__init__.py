"""Pod lifecycle for the chat: subprocess calls to scripts/pod and scripts/comfyui-bootstrap,
session bookkeeping, the REPL hooks, and the `/pod rebuild` runbook. The scripts stay the single
implementation of the lifecycle; nothing here re-derives what they do."""
