"""The operator's side of the repo.

The human-facing I/O and the operator's own files: the single
human<->mesh operator door, the prompt-only interactive terminal, the
run-overview review files (:mod:`dhc.ui.state`), and the operator's
resumability store surfaced via the terminal's ``/resume``
(:mod:`dhc.ui.checkpoint`, decision 0012).

The peer communication channels live in :mod:`dhc.tooling` (decision
0015) — they are composed agent tooling, not operator surface.
"""
