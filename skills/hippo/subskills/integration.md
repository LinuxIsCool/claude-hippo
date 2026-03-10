---
name: hippo-integration
description: >
  Cross-plugin integration — namespace conventions, knowledge event detection, source patterns.
  Trigger: cross-plugin, namespace, connect, integration, "how do plugins connect".
allowed-tools: Read, Write, Glob, Grep, Bash, Skill
---

# Integration — Cross-Plugin Knowledge Flow

## What This Does

Defines how Hippo connects with every other plugin in the Legion ecosystem. Each plugin
produces knowledge artifacts; Hippo indexes them into the graph. Each plugin can query the
graph for context. Integration is the connective tissue — without it, plugins are isolated
silos. With it, a journal entry about a venture decision automatically enriches the graph
that informs tomorrow's session context.

## The Five Ws Integration

| Plugin | Namespace | Index Pattern | Triple Examples |
|---|---|---|---|
| journal | `journal:path` | `~/.claude/local/journal/**/*.md` | (Legion, reflected-on, knowledge-graphs), (decision, chose, FalkorDB) |
| ventures | `venture:name` | `~/.claude/local/ventures/*.md` | (venture-X, status, active), (milestone-1, deadline, 2026-03-15) |
| backlog | `task:id` | `~/.claude/local/backlog/task-*.md` | (task-42, completed, 2026-03-09), (task-42, blocked-by, infra-setup) |
| inventory | `inventory:machine` | `~/.claude/local/inventory/assets/**/*.md` | (legion-t5, has-gpu, rtx-4070), (rtx-4070, vram, 12gb) |
| ground | `ground:gkNN` | `~/.claude/local/ground/keys/*.md` | (legion, contemplated, gk-23), (gk-23, frequency, gift) |

### Namespace Design

Namespaces prevent entity collision and enable scoped queries. Format: `{plugin}:{identifier}`.

- `journal:2026-03-09/session` — a specific journal entry
- `venture:knowledge-infra` — a venture by name
- `task:42` — a backlog task by ID
- `inventory:legion-t5` — a machine by hostname
- `ground:gk23` — a Gene Key by number

Namespaces appear in edge `source` properties, enabling queries like "show me everything
sourced from journal entries this week."

## Knowledge Event Detection

### PostToolUse Hook

The primary integration point. After any Write or Edit tool call, check if the target
path matches a known source pattern:

```
Path: ~/.claude/local/journal/2026-03-09/evening.md
Match: journal/**/*.md → queue for indexing as journal:2026-03-09/evening
```

Detection logic:
1. Extract the file path from the tool result
2. Match against registered source patterns (ordered by specificity)
3. If match found, add to pending index queue
4. If no match, ignore (not everything is knowledge)

### Pending Index Queue

Location: `~/.claude/local/hippo/.pending-index`

One file path per line. Processed at:
- Session end (PostSessionEnd hook)
- Manual `/index` command
- When queue exceeds 20 items (batch trigger)

Format:
```
journal:~/.claude/local/journal/2026-03-09/evening.md
venture:~/.claude/local/ventures/knowledge-infra.md
ground:~/.claude/local/ground/keys/gk23-complexity-simplicity-quintessence.md
```

## Session Memory Loading

### SessionStart Hook

At session start, Hippo preloads relevant context:

1. Determine current project from working directory
2. Extract key terms from project path and recent git log
3. Run a focused retrieval query (see retrieval.md)
4. Inject top-5 results as session context
5. Log what was loaded for transparency

This means Legion starts every session already knowing what's relevant — no manual
"remind me what we were doing" needed.

### Context Injection Format

```
[hippo] Preloaded context for project: legion-plugins
  - falkordb → decided-to-use → legion (journal:2026-03-09, weight: 3.2)
  - hippo → implements → hipporag-paper (study:hipporag, weight: 2.8)
  - knowledge-graph → enables → associative-retrieval (study:hipporag, weight: 2.1)
```

## Cross-Plugin Queries

Queries that span multiple plugins reveal emergent connections:

**"What decisions affected this venture?"**
Seeds from `venture:knowledge-infra`, traverse to `journal:*` sources, filter for
relation types containing "decided" or "chose".

**"What ground keys relate to my current work?"**
Seeds from current project entities, traverse to `ground:*` nodes, surface which
Gene Keys are connected to active work.

**"What tasks are blocked by knowledge gaps?"**
Seeds from `task:*` nodes with "blocked-by" relations, check if blocking entities
have low graph connectivity (indicating knowledge gaps).

**"What did I learn about X across all sources?"**
Pure entity query — find entity X, retrieve all edges regardless of source namespace,
group results by namespace for a cross-cutting view.

## Plugin Registration

New plugins integrate with Hippo by adding an entry to `~/.claude/local/hippo/sources.yml`:

```yaml
sources:
  journal:
    pattern: "~/.claude/local/journal/**/*.md"
    namespace: "journal"
    extraction_prompt: "journal"
  ventures:
    pattern: "~/.claude/local/ventures/*.md"
    namespace: "venture"
    extraction_prompt: "venture"
```

This keeps integration configuration declarative and extensible — adding a new plugin
to the knowledge graph requires only a YAML entry and an extraction prompt.

## Event Flow Diagram

```
Write/Edit → PostToolUse hook → path match? → .pending-index queue
                                                    ↓
Session end → process queue → indexing.md → FalkorDB
                                                    ↓
Session start → SessionStart hook → retrieval.md → context injection
```

The cycle is automatic. Write something, it gets indexed. Start a session, relevant
knowledge surfaces. Use knowledge, it gets strengthened. Ignore knowledge, it decays.
The graph is alive.
