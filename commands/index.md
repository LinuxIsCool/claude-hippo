---
description: "Index a document or directory into the knowledge graph"
argument-hint: "<source> [--type journal|venture|task|asset|ground|url]"
allowed-tools: [Read, Write, Edit, Glob, Grep, Bash, Skill, WebFetch]
---

# /index — Index Content into the Knowledge Graph

Parse the user's input to determine what to index:

| Input | Action |
|-------|--------|
| `<filepath>` | Index a single file |
| `<directory>` | Glob for .md files, index each |
| `<url>` | WebFetch URL content, index it |
| `all` | Reindex all configured sources from config.yml |

Optional flag: `--type <type>` to override automatic type detection.
Valid types: `journal`, `venture`, `task`, `asset`, `ground`, `url`

---

## Protocol

### 1. Resolve Source

- **File path**: Verify the file exists. Read its content.
- **Directory**: Glob for `**/*.md` files. List them, confirm count with user if > 20.
- **URL**: Use WebFetch to retrieve the content. Store a local cache copy.
- **`all`**: Read `~/.claude/plugins/local/legion-plugins/plugins/claude-hippo/config.yml` for configured source patterns. Glob each pattern.

### 2. Determine Source Type

If `--type` flag provided, use it. Otherwise infer from path:

| Path pattern | Type |
|-------------|------|
| `*/journal/*` or `*/journals/*` | journal |
| `*/ventures/*` or `*/venture/*` | venture |
| `*/tasks/*` or `*/todo/*` | task |
| `*/assets/*` or `*/inventory/*` | asset |
| `*/ground-truth/*` or `*/references/*` | ground |
| URL input | url |
| Anything else | general |

### 3. Check Episode Tracking

Read `~/.claude/plugins/local/legion-plugins/plugins/claude-hippo/episode-hashes.jsonl`.

For each file, compute a content hash. If the hash matches the last recorded hash for that source path, skip it (content unchanged). Report skipped files.

### 4. Select Extraction Prompt

Read `~/.claude/plugins/local/legion-plugins/plugins/claude-hippo/references/openie-prompts.md`.

Select the prompt section matching the source type. Each type has domain-specific extraction guidance (what entities to look for, what relations matter).

### 5. Extract

Invoke the `@hippo-indexing` subskill with:
- Document content
- Source type
- Extraction prompt
- Source metadata (path, timestamp, hash)

The subskill handles:
- Entity extraction (with types and attributes)
- Relation extraction (subject, predicate, object, confidence)
- Episode creation (source tracking)
- Graph upsert (create or update nodes/edges in FalkorDB)

### 6. Log & Report

Append to `~/.claude/plugins/local/legion-plugins/plugins/claude-hippo/extraction-log.jsonl`:
```json
{"timestamp": "...", "source": "...", "type": "...", "hash": "...", "entities_created": N, "entities_updated": N, "relations_created": N, "triples_extracted": N}
```

Update `episode-hashes.jsonl` with new hash for this source.

Remove from `.pending-index` if it was queued.

Report to user:
```
Indexed: path/to/file.md (journal)
├─ Triples extracted: 12
├─ Entities: 5 created, 3 updated
├─ Relations: 12 created
└─ Duration: 2.3s
```

For batch operations (directory or `all`), show a summary table:
```
Indexed 15 files (3 skipped, unchanged)
├─ Total triples: 187
├─ Entities: 45 created, 23 updated
├─ Relations: 187 created
└─ Duration: 34.1s
```
