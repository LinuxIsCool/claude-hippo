---
description: "Associative retrieval from the knowledge graph"
argument-hint: "<query> [--hops <N>] [--top <K>]"
allowed-tools: [Read, Glob, Grep, Bash, Skill]
---

# /recall — Associative Retrieval from the Knowledge Graph

Retrieve memories from the knowledge graph using Personalized PageRank for associative, context-aware recall.

---

## Input Parsing

Parse the user's input:
- **query** (required): The natural language query or entity name to recall around
- **--hops N** (optional, default 2): Maximum graph traversal depth
- **--top K** (optional, default 20): Maximum results to return

---

## Protocol

### 1. Parse & Validate

Extract the query string, hops, and top-K from the input. If no query provided, prompt the user.

### 2. Invoke Retrieval

Invoke the `@hippo-retrieval` subskill with:
- Query text
- Hops parameter
- Top-K parameter

The subskill handles:
- Query embedding (via configured embedding model)
- Seed node selection (entities matching query by embedding similarity)
- Personalized PageRank traversal from seed nodes
- Result ranking by PPR score
- Provenance tracking (which source documents contributed each result)

### 3. Present Results

Display results ranked by relevance score:

```
recall: "knowledge graph architecture"

 1. [0.92] Knowledge Graph (concept)
    "A graph-structured knowledge base storing entities and relations"
    Source: studies/knowledge-graphs.md (2026-03-05)
    Connections: 15 edges, 8 neighbors

 2. [0.85] FalkorDB (tool)
    "Graph database used for hippo knowledge storage"
    Source: ground-truth/stack.md (2026-03-01)
    Connections: 7 edges, 5 neighbors

 3. [0.71] Graphiti (tool)
    "Temporal knowledge graph library by Zep"
    Source: studies/graphiti-study.md (2026-03-04)
    Connections: 12 edges, 9 neighbors
    ...
```

Each result includes:
- **Score**: PPR relevance score (0-1)
- **Entity name and type**
- **Description or summary** (from node attributes)
- **Source provenance**: Which document(s) this entity was extracted from
- **Connection density**: Edge count and neighbor count

### 4. Offer Deeper Exploration

After presenting results, offer:
- **"graph N"** — Show 2-hop subgraph around result N (delegates to `/hippo graph`)
- **"more"** — Increase top-K and re-run
- **"related <entity>"** — Pivot to a new recall centered on a specific result
- **"sources N"** — Show the full source passages that mentioned result N

---

## Edge Cases

- **No results**: Report that no matching entities were found. Suggest broader query terms or check if the relevant content has been indexed.
- **Too many results**: If top-K > 50, warn that results may be noisy. Suggest narrowing the query.
- **FalkorDB unreachable**: Report the error clearly. Suggest running `/hippo health`.
