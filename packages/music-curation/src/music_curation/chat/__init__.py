"""`music-curation chat`: a conversational front end over the agent's library functions.

Built on agent-shell. This package is the only part of music_curation that may import agent_shell
(an import-linter contract enforces it). It reads memory, writes Suno prompts (an LLM call),
structures the director's reactions, and writes to memory only through the shell's confirmation gate.
"""
