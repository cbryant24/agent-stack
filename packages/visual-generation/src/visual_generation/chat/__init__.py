"""`visual-generation chat`: a conversational front end over the agent's read and craft functions.

Built on agent-shell. This package is the only part of visual_generation that may import
agent_shell (an import-linter contract enforces it). It reads, crafts, interprets feedback,
writes to memory, and (Phase 5) renders and drives the pod lifecycle; every write and every
spend goes through the shell's confirmation gate.
"""
