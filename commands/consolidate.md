---
description: "Trigger memory consolidation (strengthen, decay, evolve)"
argument-hint: "[--strengthen | --decay | --prune | --schema | --stats]"
allowed-tools: [Bash]
---

# /consolidate — Memory Consolidation

Run the hippo consolidation pipeline.

## Routing

| Input | Command |
|-------|---------|
| (none) | `uv run ~/.claude/plugins/local/legion-plugins/plugins/claude-hippo/scripts/hippo_consolidate.py` (full) |
| `--strengthen` | Only strengthen recently accessed edges |
| `--decay` | Only apply temporal decay |
| `--prune` | Only remove weak edges and orphans |
| `--schema` | Only normalize relations and find duplicates |
| `--stats` | Show graph health dashboard |

```bash
uv run ~/.claude/plugins/local/legion-plugins/plugins/claude-hippo/scripts/hippo_consolidate.py [options]
```

Run the command via Bash and present the output.
