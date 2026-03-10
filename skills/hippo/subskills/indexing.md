---
name: hippo-indexing
description: >
  Pattern Separation — OpenIE triple extraction from documents into FalkorDB knowledge graph.
  Handles journal entries, ventures, tasks, inventory, ground contemplations, and external content.
  Trigger: index, add, ingest, extract, "add to graph", "index this".
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, Skill, WebFetch
---

# Indexing — Pattern Separation

## What This Does

Converts unstructured markdown into structured knowledge graph triples via LLM-powered
Open Information Extraction (OpenIE). Each document becomes a set of (subject, relation, object)
triples stored in FalkorDB, with entity embeddings for similarity search.

## Biological Analog

**Pattern Separation in the Dentate Gyrus** — overlapping inputs become distinct, orthogonal
representations. Two similar journal entries about "knowledge graphs" produce non-overlapping
graph structures, each with unique provenance. The dentate gyrus ensures memories don't blur
together; indexing ensures documents don't collapse into ambiguity.

## Indexing Protocol

### Step 1: Read Source Document

Read the full document content. Never truncate. Identify document type from path.

### Step 2: Determine Content Type

| Path Pattern | Content Type | Namespace |
|---|---|---|
| `journal/**/*.md` | journal | `journal:path` |
| `ventures/**/*.md` | venture | `venture:name` |
| `backlog/task-*.md` | task | `task:id` |
| `inventory/**/*.md` | inventory | `inventory:machine` |
| `ground/keys/*.md` | ground | `ground:gkNN` |
| everything else | external | `external:url-or-path` |

### Step 3: Select Extraction Prompt

Load the appropriate OpenIE prompt from `references/openie-prompts.md` based on content type.
Each type has tuned instructions — journal entries emphasize decisions and reflections, ventures
emphasize milestones and blockers, ground emphasizes frequencies and contemplations.

### Step 4: Call LLM for Triple Extraction

Use TELUS Ollama GPT OSS 120B via the telus-ai skill. Send the document content with the
extraction prompt. Parse the returned JSON array of triples.

### Step 5: Normalize Entities

- Lowercase all entity names
- Merge synonyms (e.g., "FalkorDB" and "falkordb" → "falkordb")
- Strip trailing punctuation
- Collapse whitespace

### Step 6: Embed Entities

Call TELUS AI `nvidia/nv-embedqa-e5-v5` for each unique entity. Cache embeddings to avoid
redundant API calls. Store embedding dimension in graph node properties.

### Step 7: Insert into FalkorDB

```cypher
MERGE (s:Entity {name: $subject})
ON CREATE SET s.type = $subject_type, s.embedding = $embedding, s.created = $timestamp
MERGE (o:Entity {name: $object})
ON CREATE SET o.type = $object_type, o.embedding = $embedding, o.created = $timestamp
MERGE (s)-[r:RELATES {type: $relation}]->(o)
SET r.weight = COALESCE(r.weight, 0) + 1,
    r.last_accessed = $timestamp,
    r.source = $source
```

### Step 8: Log Extraction

Append to `~/.claude/local/hippo/extraction-log.jsonl`:
```json
{"timestamp": "2026-03-09T14:30:00Z", "source": "journal:2026-03-09/session", "triples_count": 12, "entities_count": 8}
```

### Step 9: Mark as Indexed

Write marker to `~/.claude/local/hippo/episodes/{source_type}/{filename}.indexed` containing
the file's SHA-256 hash. On reindex, compare hashes — skip unchanged files.

## Batch Indexing

For directory targets, glob all matching `.md` files. Process in batches of 5 to manage
API rate limits and memory. Report progress after each batch.

## Source Namespace Convention

Namespaces prevent collision across content types. Format: `{type}:{identifier}`.
The identifier is the minimal unique path or name within that type.

## Deduplication

Before inserting any entity:
1. Check exact name match in graph
2. If no match, compute embedding similarity against existing entities
3. If similarity > 0.95, merge into existing entity (update properties, don't duplicate)
4. Log merges for auditability

## Episode Tracking

Episodes are the indexing memory — which files have been processed and when.
Structure: `~/.claude/local/hippo/episodes/{content_type}/{filename}.indexed`
Each marker contains: `{hash, timestamp, triples_count, entity_count}`.
The `reindex` command reprocesses only files whose hash has changed.
