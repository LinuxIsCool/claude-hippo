---
name: hippo
description: >
  Associative memory backbone. HippoRAG-inspired knowledge graph with three operations:
  indexing (OpenIE → triples), retrieval (PPR → context), consolidation (strengthen/decay/evolve).
  Use when: cross-plugin queries, "what's related to X?", memory retrieval, knowledge indexing,
  "what do I know about?", connecting information across plugins.
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, Skill, WebFetch
---

# Hippo Master

Associative memory for Legion's plugin ecosystem. Indexes knowledge from journal, ventures, backlog, inventory, and ground into a FalkorDB knowledge graph using OpenIE triple extraction. Retrieves context via Personalized PageRank walks that follow relationships rather than just similarity. Consolidates over time by strengthening accessed paths, decaying unused ones, pruning weak edges, and merging similar entities. This is how Legion remembers — not as isolated documents, but as a connected web of entities and relations.

## The Three Operations

### 1. Indexing (Pattern Separation)

OpenIE extraction converts documents into distinct entity-relation triples stored in FalkorDB. Inspired by the Dentate Gyrus, which separates overlapping sensory inputs into distinct neural representations.

- Input: any document (journal entry, venture doc, task, contemplation, inventory)
- Process: LLM extracts (subject, relation, object) triples + entity metadata
- Output: nodes and edges in the knowledge graph, namespaced by source plugin
- See `references/openie-prompts.md` for extraction prompt templates

### 2. Retrieval (Pattern Completion)

Personalized PageRank walks the graph from query-related seed nodes, discovering associated context through multi-hop traversal. Inspired by CA3 recurrent connections that reconstruct complete memories from partial cues.

- Input: natural language query or entity name
- Process: extract query entities → find seed nodes → PPR walk → rank results
- Output: top-k related entities with source documents and relationship paths
- See `references/ppr-tuning.md` for parameter tuning guide

### 3. Consolidation (Memory Strengthening)

Over time, the graph evolves: accessed paths strengthen, unused paths decay, weak edges get pruned, and similar entities merge. Inspired by hippocampal-neocortical memory transfer during sleep.

- Strengthen: increment edge weight on each access (+0.1 default)
- Decay: Ebbinghaus curve with configurable halflife (30 days default)
- Prune: remove edges below threshold (0.1 default)
- Merge: detect and unify synonym entities via embedding similarity

## Infrastructure

- **FalkorDB**: Docker container at port 6380, Redis-compatible protocol
- **Service**: `systemctl --user start hippo-graph` / `systemctl --user status hippo-graph`
- **Health check**: `redis-cli -p 6380 PING` (expect PONG)
- **Setup**: `bash ~/.claude/local/scripts/setup-hippo.sh` (creates container, service, directories)
- **Data directory**: `~/.claude/local/hippo/`
- **Logs**: `~/.claude/local/hippo/logs/`

## Cross-Plugin Namespaces

Every node in the graph carries a namespace prefix identifying its source plugin:

| Namespace | Source | Example Node |
|-----------|--------|-------------|
| `journal:` | claude-journal | `journal:2026-03-09` |
| `venture:` | claude-ventures | `venture:hippo-plugin` |
| `task:` | claude-backlog | `task:hippo-003` |
| `inventory:` | claude-inventory | `inventory:mothership` |
| `ground:` | claude-ground | `ground:gk47` |
| `entity:` | extracted entities | `entity:FalkorDB` |
| `relation:` | extracted relations | `relation:decided-to-use` |

Namespaces enable scoped queries ("search only journal") and cross-plugin traversal ("what journal entries mention this venture?").

## Indexing Protocol

1. **Read** the source document
2. **Determine type** from path or metadata (journal, venture, task, contemplation, inventory)
3. **Select prompt** from `references/openie-prompts.md` based on content type
4. **Extract triples** via LLM — subject, relation, object + entity types
5. **Embed entities** for similarity-based seed matching during retrieval
6. **Normalize** entity names (lowercase, merge synonyms, resolve references)
7. **Insert into graph** with namespace prefix, timestamp, source path, and initial edge weight (1.0)
8. **Log** extraction to `~/.claude/local/hippo/logs/extraction-log.jsonl`

## Retrieval Protocol

1. **Parse query** — identify intent (focused vs exploratory)
2. **Extract entities** from query text via lightweight NER
3. **Find seed nodes** — entity name match (exact + fuzzy) combined with embedding similarity
4. **Configure PPR** — set damping factor and top_k based on query intent (see `references/ppr-tuning.md`)
5. **Execute PPR walk** from seed nodes through the graph
6. **Collect top-k** results ranked by PPR score
7. **Read source documents** for the top results to assemble full context
8. **Return** ranked results with entity names, relationship paths, scores, and source excerpts

## Consolidation Protocol

1. **Strengthen** edges accessed during recent retrievals (+strengthen_increment per access)
2. **Apply decay** curve to all edges: `weight *= 0.5 ^ (days_since_access / decay_halflife)`
3. **Prune** edges with weight below prune_threshold
4. **Detect synonyms** via entity embedding cosine similarity (threshold 0.92)
5. **Merge** synonym entities — combine edges, keep the more common name
6. **Log** consolidation actions to `~/.claude/local/hippo/logs/consolidation-log.jsonl`
7. **Report** stats: edges strengthened, decayed, pruned, entities merged

## Configuration

`~/.claude/local/hippo/config.yml`:
```yaml
falkordb:
  host: localhost
  port: 6380
  graph_name: legion

ppr:
  damping_factor: 0.85
  max_iterations: 20
  default_top_k: 20

consolidation:
  decay_halflife: 30          # days
  prune_threshold: 0.1
  strengthen_increment: 0.1
  synonym_threshold: 0.92     # cosine similarity for merge
  schedule: weekly             # how often to run consolidation

extraction:
  batch_size: 5
  model: default               # LLM for OpenIE extraction
  log_path: ~/.claude/local/hippo/logs/extraction-log.jsonl

namespaces:
  - journal
  - venture
  - task
  - inventory
  - ground
  - entity
  - relation
```

## Subskills

### @hippo-indexing
**Trigger**: index, add, ingest, extract, "add this to the graph", "index this document"
Handles OpenIE extraction and graph insertion for any content type.

### @hippo-retrieval
**Trigger**: recall, search, find, query, "what's related to", "what do I know about", "find connections"
Handles PPR-based retrieval and context assembly.

### @hippo-consolidation
**Trigger**: consolidate, strengthen, decay, prune, merge, "clean up the graph", "maintenance"
Handles edge weight management, decay, pruning, and entity deduplication.

### @hippo-backends
**Trigger**: FalkorDB, graph database, setup, health, docker, infrastructure, service
Handles FalkorDB container lifecycle, health checks, and troubleshooting.

### @hippo-integration
**Trigger**: cross-plugin, namespace, connect, integration, "link journal to venture", bridge
Handles cross-plugin namespace queries and multi-source traversal.

## Routing

When invoked:
1. **Indexing request** (index, add, ingest, extract) → @hippo-indexing
2. **Retrieval query** (recall, search, find, "what's related") → @hippo-retrieval
3. **Consolidation request** (consolidate, decay, prune, merge) → @hippo-consolidation
4. **Infrastructure question** (FalkorDB, docker, setup, health) → @hippo-backends
5. **Integration question** (cross-plugin, namespace, bridge) → @hippo-integration
6. **No args / "status"** → graph stats: node count, edge count, namespaces, last consolidation, health
