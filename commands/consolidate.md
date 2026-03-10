---
description: "Trigger memory consolidation (strengthen, decay, evolve)"
argument-hint: "[--full | --strengthen | --decay | --schema | --prune]"
allowed-tools: [Read, Write, Bash, Skill]
---

# /consolidate — Memory Consolidation

Trigger consolidation operations on the knowledge graph. Inspired by hippocampal memory consolidation: strengthen important memories, decay unused ones, merge duplicates, prune noise.

---

## Routing

| Input | Action |
|-------|--------|
| (none) or `--full` | Run all consolidation operations in sequence |
| `--strengthen` | Only strengthen recently accessed edges |
| `--decay` | Only apply temporal decay to edge weights |
| `--prune` | Only prune edges below weight threshold |
| `--schema` | Only merge/normalize duplicate entities |

---

## Protocol

### 1. Invoke Consolidation

Invoke the `@hippo-consolidation` subskill with the specified mode.

The subskill handles each operation:

#### Strengthen (reactivation-based strengthening)
- Find edges that were traversed during recent `/recall` queries (check retrieval-log.jsonl)
- Increase their weight proportional to access frequency
- Biological analog: Long-term potentiation — frequently accessed pathways get stronger

#### Decay (temporal decay)
- Apply exponential decay to all edge weights based on time since last access
- Decay formula: `weight *= exp(-lambda * days_since_access)`
- Lambda (decay rate) configured in config.yml, default 0.01
- Biological analog: Synaptic weakening of unused connections

#### Prune (garbage collection)
- Remove edges with weight below configured threshold (default 0.1)
- Remove orphan nodes (nodes with no remaining edges)
- Log pruned entities and relations for audit
- Biological analog: Synaptic pruning of weak connections

#### Schema (entity normalization)
- Find candidate duplicate entities by embedding similarity (threshold from config.yml)
- Find entities with similar names (fuzzy string matching)
- Merge duplicates: combine attributes, redirect edges, keep the most descriptive name
- Normalize relation types (e.g., "is part of" → "part_of", "belongs to" → "part_of")
- Biological analog: Memory integration and abstraction during sleep

### 2. Log Results

Append to `~/.claude/plugins/local/legion-plugins/plugins/claude-hippo/consolidation-log.jsonl`:
```json
{"timestamp": "...", "mode": "full", "edges_strengthened": N, "edges_decayed": N, "edges_pruned": N, "nodes_pruned": N, "entities_merged": N, "relations_normalized": N, "duration_s": N}
```

### 3. Report

```
Consolidation complete (full)
├─ Strengthened: 45 edges (avg +0.12 weight)
├─ Decayed: 1,234 edges (avg -0.03 weight)
├─ Pruned: 23 edges, 5 orphan nodes
├─ Schema: 3 entity merges, 12 relation normalizations
└─ Duration: 8.2s
```

For single-mode runs, only show the relevant section.

---

## Scheduling Notes

Full consolidation should run periodically. The memory-architect agent can advise on scheduling. Typical cadence:
- **Strengthen**: After every session (or on `/recall`)
- **Decay**: Daily
- **Prune**: Weekly
- **Schema**: Weekly or on-demand
- **Full**: Weekly (e.g., Sunday night)
