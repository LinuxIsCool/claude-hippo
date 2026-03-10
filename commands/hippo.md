---
description: "Knowledge graph status, health, and statistics"
argument-hint: "[status | stats | health | graph <entity>]"
allowed-tools: [Read, Write, Edit, Glob, Grep, Bash, Skill]
---

# /hippo — Knowledge Graph Status & Inspection

Parse the user's input to determine the subcommand:

| Input | Action |
|-------|--------|
| (none) or `status` | Quick status |
| `stats` | Detailed statistics |
| `health` | Full health check |
| `graph <entity>` | 2-hop subgraph around named entity |

---

## status (default)

Quick overview of the knowledge graph state.

1. **Connectivity**: Run `redis-cli -p 6380 PING` — report UP or DOWN
2. **Node count**: `redis-cli -p 6380 GRAPH.QUERY hippo "MATCH (n) RETURN count(n)"`
3. **Edge count**: `redis-cli -p 6380 GRAPH.QUERY hippo "MATCH ()-[r]->() RETURN count(r)"`
4. **Last indexed**: Read the last line of `~/.claude/plugins/local/legion-plugins/plugins/claude-hippo/extraction-log.jsonl` — show source and timestamp
5. **Last consolidated**: Read the last line of `~/.claude/plugins/local/legion-plugins/plugins/claude-hippo/consolidation-log.jsonl` — show timestamp and summary
6. **Pending queue**: Count files in `~/.claude/plugins/local/legion-plugins/plugins/claude-hippo/.pending-index` if it exists

Present as a compact status block:

```
hippo 🧠
├─ FalkorDB: UP
├─ Nodes: 1,234 | Edges: 3,456
├─ Last indexed: journal/2026-03-08.md (2h ago)
├─ Last consolidated: 2026-03-07 03:00 (2d ago)
└─ Pending: 3 files
```

---

## stats

Detailed statistics about graph contents.

1. Run all status checks first
2. **Entities by type**:
   ```cypher
   MATCH (n) RETURN labels(n) AS type, count(n) AS count ORDER BY count DESC
   ```
3. **Relations by type**:
   ```cypher
   MATCH ()-[r]->() RETURN type(r) AS relation, count(r) AS count ORDER BY count DESC
   ```
4. **Top 20 entities by degree** (most connected):
   ```cypher
   MATCH (n)-[r]-() RETURN n.name AS entity, labels(n) AS type, count(r) AS degree ORDER BY degree DESC LIMIT 20
   ```

Present entities by type and relations by type as tables. Present top-20 as a ranked list.

---

## health

Full health and diagnostics check.

1. Run all status checks
2. **Container status**: `docker stats hippo-graph --no-stream --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}"`
3. **Redis memory**: `redis-cli -p 6380 INFO memory` — extract used_memory_human, used_memory_peak_human, mem_fragmentation_ratio
4. **Index freshness**: For each source pattern in config.yml, check if any matching files have been modified since last indexing
5. **Pending queue**: List all files in `.pending-index` with their age

Report any warnings:
- FalkorDB unreachable
- Memory usage > 80% of available
- Files unindexed for > 24 hours
- No consolidation in > 7 days
- Fragmentation ratio > 1.5

---

## graph <entity>

Show the 2-hop neighborhood around a named entity.

1. **Find the entity** — fuzzy match by name:
   ```cypher
   MATCH (n) WHERE toLower(n.name) CONTAINS toLower($entity) RETURN n.name, labels(n) LIMIT 5
   ```
   If multiple matches, show them and ask user to clarify. If one match, proceed.

2. **2-hop subgraph**:
   ```cypher
   MATCH path = (center)-[*1..2]-(neighbor)
   WHERE center.name = $exact_name
   RETURN path
   ```

3. **Display as text graph**:
   ```
   [Entity A] ──uses──> [Entity B]
                         ├──part_of──> [Entity C]
                         └──related_to──> [Entity D]
   [Entity A] ──authored──> [Entity E]
   ```

Group by first-hop entity, show second-hop entities nested underneath. Include relation types on the edges.
