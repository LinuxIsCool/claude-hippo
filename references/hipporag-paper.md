# HippoRAG: Key Concepts

Source: HippoRAG (NeurIPS 2024), HippoRAG v2 (ICML 2025)
GitHub: https://github.com/OSU-NLP-Group/HippoRAG
Paper: https://arxiv.org/pdf/2405.14831

## Core Idea

RAG systems inspired by the hippocampal memory indexing theory. The hippocampus doesn't store memories — it indexes them, creating associative links that enable multi-hop retrieval from partial cues.

## Three Operations (Biological Analogs)

### 1. Pattern Separation (Dentate Gyrus → OpenIE)

The Dentate Gyrus takes overlapping sensory inputs and creates distinct, separable neural representations. In HippoRAG, OpenIE (Open Information Extraction) converts overlapping documents into distinct entity-relation triples.

Input: "Legion decided to use FalkorDB for the knowledge graph. Neo4j is more mature but FalkorDB's Redis-based in-memory speed fits the single-machine setup."

Output triples:
- (Legion, decided-to-use, FalkorDB)
- (FalkorDB, is-a, graph-database)
- (FalkorDB, characteristic, Redis-based-in-memory)
- (Neo4j, is-a, graph-database)
- (Legion, setup-type, single-machine)

### 2. Pattern Completion (CA3 → PPR)

CA3 neurons have recurrent connections — given a partial cue, they reconstruct complete memories by activating connected neurons. In HippoRAG, Personalized PageRank (PPR) walks the knowledge graph from query-related seed nodes, discovering associated context through multi-hop traversal.

Query: "What do I know about knowledge graphs?"
1. Extract query entities: ["knowledge graphs"]
2. Find seed nodes: [FalkorDB, Neo4j, Graphiti]
3. PPR walk discovers: FalkorDB → Redis → speed → decided-to-use → Legion → journal entries
4. Multi-hop naturally emerges from graph structure

Key advantage over vector search: PPR follows relationships, not just similarity.

### 3. Memory Consolidation (Hippocampal-Neocortical Transfer)

During sleep, the hippocampus replays memories to the neocortex, gradually transferring episodic memories into semantic knowledge. In HippoRAG:
- Edge strengthening: frequently accessed paths get higher weights
- Temporal decay: Ebbinghaus curve (halflife configurable)
- Schema evolution: merge similar entities, normalize relations
- Pruning: remove edges below threshold

## Key Parameters

| Parameter | Default | What It Controls |
|-----------|---------|-----------------|
| damping_factor | 0.85 | PPR exploration depth (lower = wider exploration) |
| max_iterations | 20 | PPR convergence iterations |
| top_k | 10-50 | Number of results returned |
| decay_halflife | 30 days | How fast unused edges weaken |
| prune_threshold | 0.1 | Minimum edge weight before removal |
| strengthen_increment | 0.1 | Weight added per access |

## HippoRAG v2 Additions

- Online retrieval (no full reindex needed)
- Continual learning
- Improved synonym detection via SchemaLink
- Better entity normalization
