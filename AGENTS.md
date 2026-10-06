# AGENTS.md


## Context Budget — Prefer Subagents

- Use subagents as much as possible: the current model has a limited context, and heavy reading (file exploration, long documents, search sweeps) fills it fast.
- Delegate broad, self-contained information gathering to subagents (`explore` for codebase/search questions, `general` for multi-step research or parallel work), and consume only their summaries.
- Run independent tasks in parallel subagents; keep the main session for decisions, edits, and synthesis.
- Write large artifacts directly to files rather than streaming them through the conversation.


## Git guidelines

Do not commit after changes. Enable manual review before commits

