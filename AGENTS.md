# AGENTS.md


## Context Budget — Prefer Subagents

- Use subagents as much as possible: the current model has a limited context, and heavy reading (file exploration, long documents, search sweeps) fills it fast.
- Delegate broad, self-contained information gathering to subagents (`explore` for codebase/search questions, `general` for multi-step research or parallel work), and consume only their summaries.
- Run independent tasks in parallel subagents; keep the main session for decisions, edits, and synthesis.
- Write large artifacts directly to files rather than streaming them through the conversation.

## Stay on Mission

**Do not lose the forest for the trees.**

Your job is to accomplish the user's objective, not to perfect every detail along the way. Agents that are prone to going astray often spend too much time on edge cases, abstractions, refactoring, cleanup, or questions that have little impact on the final outcome. **Do not do this.**

At every step, prioritize:

1. **The user's actual goal.** Keep the desired outcome as the primary constraint.
2. **Meaningful progress.** Prefer actions that directly move the task toward completion.
3. **Impact over completeness.** A small imperfection is often better than a large detour.
4. **Sensible assumptions.** If an ambiguity is low-risk and does not materially affect the outcome, make a reasonable choice and continue.
5. **Proportionality.** Spend effort according to importance. Do not spend ten minutes solving a problem that matters for ten seconds of the final result.

Before pursuing a tangent, ask:

> **Will this materially improve the outcome the user cares about?**

If the answer is no, **stop and move on.**

## Git guidelines

Do not commit after changes. Enable manual review before commits

