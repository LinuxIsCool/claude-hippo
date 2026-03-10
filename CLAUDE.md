# claude-hippo

Associative memory backbone. HippoRAG-inspired knowledge graph connecting all plugins.

## Quick Start
- `/hippo` — graph status, health, statistics
- `/index <source>` — index a document into the knowledge graph
- `/recall <query>` — associative retrieval via PPR
- `/consolidate` — trigger memory consolidation

## The Three Operations
1. **Indexing** (Pattern Separation) — OpenIE extracts triples from documents into FalkorDB
2. **Retrieval** (Pattern Completion) — PPR walks the graph from query entities
3. **Consolidation** (Memory Strengthening) — strengthen accessed paths, decay unused, evolve schema

## Infrastructure
- FalkorDB: `docker compose -f ~/.config/hippo/compose.yaml`
- Service: `systemctl --user {start,stop,status} hippo-graph`
- Port: 6380 (avoids Redis conflicts)

## Data Location
Config: `~/.claude/local/hippo/config.yml`
Episodes: `~/.claude/local/hippo/episodes/`
Logs: `~/.claude/local/hippo/extraction-log.jsonl`, `consolidation-log.jsonl`

## Cross-Plugin Namespaces
- `journal:YYYY-MM-DD/HH-MM-slug`
- `venture:venture-name`
- `task:task-id`
- `inventory:machine-name`
- `ground:gkNN`
