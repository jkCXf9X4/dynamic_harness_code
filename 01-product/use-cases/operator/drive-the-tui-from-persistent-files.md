---
id: INFO-028
type: info
title: Minimalistic UI/TUI 
summary: The operator's TUI is a minimal chat whose content and layout come from persistent files
date: 2026-10-05
status: current
---

# Drive the TUI from persistent files

- The TUI is as small as possible: it is just a simple chat — a scrolling message stream and an input line — with no extra panes, menus, or dashboards.
- As much of context info, debug info and additional information as possible lives in persistent files.

## Owns
- The operator-facing TUI shell: a chat-only view
