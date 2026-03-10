---
name: hippo-retrieval
description: >
  Pattern Completion — Personalized PageRank retrieval from knowledge graph.
  Multi-hop associative retrieval from partial cues.
  Trigger: recall, search, find, query, "what's related", "what do I know about".
allowed-tools: Read, Glob, Grep, Bash, Skill
---

# Retrieval — Pattern Completion

## What This Does

Given a natural language query, finds and assembles relevant context through graph traversal.
Starts from seed entities, radiates outward via Personalized PageRank, returns ranked results
with provenance. The graph doesn't just store facts — it completes partial cues into full context.

## Biological Analog

**CA3 Pattern Completion** — the hippocampal CA3 region reconstructs complete memories from
partial cues via dense recurrent connections. Hear three notes of a song, recall the whole thing.
See one entity name, retrieve the entire web of related knowledge. PPR mimics this spreading
activation — energy flows from seeds through weighted connections, settling into a relevance
distribution across the entire graph.

## Retrieval Protocol

### Step 1: Extract Query Entities

Parse the natural language query into candidate entity names:
- Use TELUS Ollama for complex queries (extracts noun phrases, named entities)
- For simple queries, extract nouns and proper nouns directly
- Lowercase and normalize to match graph conventions

### Step 2: Find Seed Nodes

Three matching strategies, combined and deduplicated:

**a. Direct name match:**
```cypher
MATCH (n:Entity) WHERE n.name IN $query_entities RETURN n
```

**b. Embedding similarity search:**
Embed the full query text via TELUS AI `nvidia/nv-embedqa-e5-v5`. Find top-5 entities
by cosine similarity against stored entity embeddings.

**c. Fuzzy name match:**
```cypher
MATCH (n:Entity) WHERE n.name CONTAINS $partial RETURN n LIMIT 5
```

Combine all found nodes, deduplicate by entity name.

### Step 3: Run Personalized PageRank

Initialize seed nodes with equal probability. Iterate PPR:

```cypher
// Initialize seeds
MATCH (n:Entity) WHERE n.name IN $seeds
SET n.ppr = 1.0 / $seed_count

// Iterate (repeat N times externally)
MATCH (n:Entity)-[r:RELATES]->(m:Entity)
WHERE n.ppr > 0
WITH m, SUM(n.ppr * r.weight) AS incoming
SET m.ppr = (1 - $damping) / $total + $damping * incoming
```

Parameters:
- `damping_factor`: 0.85 (default, configurable per query type)
- `iterations`: 20
- Convergence check: stop early if max delta < 0.001

### Step 4: Rank Results

Collect all nodes with ppr > 0, sort descending by score. The top-K nodes are the
retrieval results. Default K=10, adjustable.

### Step 5: Retrieve Source Documents

For each top-K node, follow edge metadata to find source document paths.
Read the source documents to provide full context, not just triple summaries.

### Step 6: Assemble Response

Each result includes provenance — the user sees where knowledge came from:

```
Query: "knowledge graphs"

1. [0.82] FalkorDB — decided-to-use → Legion (journal:2026-03-09/12-11-roadmap)
2. [0.65] Neo4j — is-a → graph-database (journal:2026-03-09/12-11-roadmap)
3. [0.41] Graphiti — relates-to → temporal-knowledge-graph (study:hipporag)
4. [0.33] embeddings — enables → similarity-search (study:hipporag)
5. [0.21] knowledge-processing — indexes → documents (journal:2026-03-05/session)
```

## Query Types

### Focused Query
Low damping (0.7), low K (5). Stays close to seeds. Best for specific factual lookups.
Example: "What GPU does Legion have?"

### Exploratory Query
High damping (0.92), high K (20). Wanders far from seeds. Best for discovering connections.
Example: "What's related to my philosophy of intents over implementations?"

### Temporal Query
Standard PPR but with date-filtered edges. Only traverse edges whose `last_accessed` or
`source` timestamp falls within the specified window.
Example: "What did I learn about FalkorDB this week?"

## Tuning

PPR parameters significantly affect retrieval quality. See `references/ppr-tuning.md` for:
- Damping factor sensitivity analysis
- Optimal iteration counts for different graph sizes
- Weight normalization strategies
- Benchmark queries and expected results

## Integration with Session Context

When invoked automatically at session start, retrieval uses the current project path and
recent file edits as implicit query terms. This preloads relevant context without explicit
user action — the graph anticipates what you need.
