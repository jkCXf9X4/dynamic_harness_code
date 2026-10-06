---
title: Artifacts
summary: The durable, content-addressed medium agents publish, consume, and trace
---

# Artifacts

Use cases about the artifact medium itself: publishing and consuming
findings, and tracing a failure through the records it leaves.

## Owns
- The artifact contract and its traceability.

## Excludes
- The channels that carry artifact references — delegation and peer exchange, organized one layer down in Architecture.

## Contents

<!-- pb:index:start -->
- **INFO-006** [Publish and consume artifacts](publish-and-consume-artifacts.md) — Findings persist as immutable content-addressed artifacts that consumers pull headline-summary-report on demand
- **INFO-027** [Trace a failure to its provenance without re-running](trace-a-failure-to-its-provenance-without-re-running.md) — A queryable event trail — CALL, DELEGATE, COMPLETE, AWAIT, CALLBACK — tying each agent to its actions and artifacts, so a failure is diagnosed by reading records only
<!-- pb:index:end -->
