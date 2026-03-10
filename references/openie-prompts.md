# OpenIE Extraction Prompts

Prompt templates for extracting knowledge graph triples from different content types.

## General Extraction Prompt

```
You are an Open Information Extraction system. Given the following text, extract all meaningful entity-relation triples.

Rules:
- Entities should be specific and normalized (e.g., "FalkorDB" not "the database")
- Relations should be verbs or verb phrases (e.g., "decided-to-use", "is-a", "relates-to")
- Include entity types when obvious (person, tool, concept, venture, date)
- Extract temporal information as separate triples
- Preserve proper nouns exactly

Output format (JSON):
{
  "triples": [
    {"subject": "entity1", "relation": "verb-phrase", "object": "entity2"},
    ...
  ],
  "entities": [
    {"name": "entity1", "type": "tool"},
    ...
  ]
}

Text:
{text}
```

## Content-Type Specific Prompts

### Journal Entry
Additional focus: decisions made, tools evaluated, people mentioned, ventures referenced, emotional tone, temporal markers.

### Venture Document
Additional focus: goals, milestones, stakeholders, technologies, dependencies, status, deadlines.

### Backlog Task
Additional focus: deliverables, blockers, assignees, milestones, completion criteria.

### Ground Contemplation
Additional focus: Gene Key identity, shadow patterns observed, gift emergences, frequency assessment, connections to other keys.

### Inventory/System Data
Additional focus: hardware specs, software versions, service status, metrics, thresholds.

## Batch Extraction

For directories with many files, extract in batches of 5 to manage LLM context:
1. Read 5 files
2. Extract triples from each
3. Deduplicate entities across batch
4. Insert into graph
5. Log to extraction-log.jsonl
6. Next batch
