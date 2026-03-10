---
description: "Index a document or directory into the knowledge graph"
argument-hint: "<source> [--type journal|venture|task|ground|inventory] [--force]"
allowed-tools: [Bash]
---

# /index — Index Content into the Knowledge Graph

Run the hippo indexing pipeline script.

## Routing

| Input | Command |
|-------|---------|
| `<filepath>` | `uv run ~/.claude/plugins/local/legion-plugins/plugins/claude-hippo/scripts/hippo_index.py <filepath>` |
| `<directory>` | `uv run ~/.claude/plugins/local/legion-plugins/plugins/claude-hippo/scripts/hippo_index.py <directory>` |
| `all` | `uv run ~/.claude/plugins/local/legion-plugins/plugins/claude-hippo/scripts/hippo_index.py --all` |
| `pending` | `uv run ~/.claude/plugins/local/legion-plugins/plugins/claude-hippo/scripts/hippo_index.py --pending` |
| `embed` | `uv run ~/.claude/plugins/local/legion-plugins/plugins/claude-hippo/scripts/hippo_index.py --embed-missing` |

Optional flags:
- `--type <type>`: Override content type detection
- `--force`: Reindex even if file hasn't changed

Run the command via Bash and present the output to the user.
