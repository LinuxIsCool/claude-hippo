---
description: "Associative retrieval from the knowledge graph"
argument-hint: "<query> [--mode focused|balanced|exploratory] [--top <K>]"
allowed-tools: [Bash]
---

# /recall — Associative Retrieval from the Knowledge Graph

Run the hippo retrieval pipeline using Personalized PageRank.

## Routing

```bash
uv run ~/.claude/plugins/local/legion-plugins/plugins/claude-hippo/scripts/hippo_recall.py "<query>" [options]
```

Options:
- `--mode focused`: Low damping (0.70), top 5. Specific factual lookups.
- `--mode balanced`: Default damping (0.85), top 10. General queries.
- `--mode exploratory`: High damping (0.92), top 20. Discover connections.
- `--top N`: Override number of results.
- `--json`: Machine-readable output.
- `--seeds-only`: Show matching entities without running PPR.

Run the command via Bash and present the results. After showing results, offer to explore deeper with follow-up queries.
