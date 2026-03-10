---
name: hippo-consolidation
description: >
  Memory Strengthening — edge weight management, temporal decay, schema evolution.
  Maintains graph health over time.
  Trigger: consolidate, strengthen, decay, prune, merge, cleanup, "graph maintenance".
allowed-tools: Read, Write, Bash, Skill
---

# Consolidation — Memory Strengthening

## What This Does

Manages the knowledge graph's health over time — strengthening important connections,
decaying unused ones, merging duplicate entities, and evolving the schema. Without
consolidation, the graph accumulates noise and loses signal. With it, frequently
accessed knowledge becomes increasingly reliable while stale connections fade gracefully.

## Biological Analog

**Hippocampal-Neocortical Memory Transfer During Sleep** — during slow-wave sleep, the
hippocampus replays recent experiences, gradually strengthening cortical connections.
Over time, memories transfer from hippocampal (episodic) to neocortical (semantic)
storage. Consolidation is Legion's sleep — the process that turns raw experience into
durable knowledge.

## Three Mechanisms

### 1. Strengthen

Increment weight on recently accessed edges. Every retrieval that touches an edge
increases its weight, making it more likely to surface in future queries.

```cypher
MATCH ()-[r:RELATES]->()
WHERE r.last_accessed > $since
SET r.weight = LEAST(r.weight + $increment, $max_weight)
```

Parameters:
- `increment`: 0.1 per access
- `max_weight`: 10.0 (prevents runaway reinforcement)
- `since`: last consolidation timestamp

Strengthening is the reward signal — knowledge that proves useful becomes more prominent.

### 2. Decay

Apply Ebbinghaus forgetting curve. Edges that haven't been accessed decay exponentially,
modeling natural forgetting. This prevents the graph from growing monotonically — old,
unused connections gracefully fade.

```cypher
MATCH ()-[r:RELATES]->()
SET r.weight = r.weight * POW(0.5, $days_since_access / $halflife)
```

Parameters:
- `halflife`: 30 days (weight halves every 30 days without access)
- Computed per-edge from `r.last_accessed` relative to current timestamp

The forgetting curve is a feature, not a bug. Knowledge that matters gets reinforced
through use. Knowledge that doesn't fades — but never fully disappears until pruned.

### 3. Prune

Remove edges whose weight has decayed below a threshold. This is the garbage collector —
connections too weak to matter get cleaned up, keeping the graph navigable.

```cypher
MATCH ()-[r:RELATES]->()
WHERE r.weight < $threshold
DELETE r
```

After edge pruning, clean up orphaned nodes (entities with no remaining connections):

```cypher
MATCH (n:Entity)
WHERE NOT (n)-[:RELATES]-() AND NOT (n)<-[:RELATES]-()
DELETE n
```

Parameters:
- `threshold`: 0.1 (edges below this are noise)
- Always log pruned edges before deletion for potential recovery

## Schema Evolution

### Entity Merging

Detect and merge duplicate entities that represent the same concept:

```cypher
MATCH (a:Entity), (b:Entity)
WHERE a.name <> b.name
AND gds.similarity.cosine(a.embedding, b.embedding) > 0.95
RETURN a.name, b.name
```

Merge strategy: keep the entity with more connections, redirect all edges from the
other, combine properties, delete the duplicate. Log every merge.

### Relation Normalization

Standardize relation types across the graph:
- Lowercase all relation type values
- Hyphenate multi-word relations ("decided to use" → "decided-to-use")
- Merge semantically identical relations (manual review, logged suggestions)

### Contradiction Detection

Find edges that may contradict each other:

```cypher
MATCH (s:Entity)-[r1:RELATES]->(o:Entity), (s)-[r2:RELATES]->(o)
WHERE r1 <> r2 AND r1.type <> r2.type
RETURN s.name, r1.type, r2.type, o.name
```

Flag contradictions for review rather than auto-resolving. Store in
`~/.claude/local/hippo/contradictions.jsonl` for human review.

## Consolidation Schedule

- **Automatic**: PostSessionEnd hook triggers decay + strengthen
- **Daily**: Cron job runs full consolidation (strengthen + decay + prune)
- **Manual**: `/consolidate` command for on-demand runs
- **Deep**: Monthly schema evolution (merge, normalize, contradiction scan)

## Logging

Each consolidation run appends to `~/.claude/local/hippo/consolidation-log.jsonl`:

```json
{
  "timestamp": "2026-03-09T03:00:00Z",
  "operation": "full",
  "edges_strengthened": 45,
  "edges_decayed": 312,
  "edges_pruned": 8,
  "entities_merged": 2,
  "orphans_removed": 3,
  "duration_ms": 1200
}
```
