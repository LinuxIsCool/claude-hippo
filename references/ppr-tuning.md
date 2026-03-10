# PPR (Personalized PageRank) Tuning Guide

## What PPR Does

Starting from seed nodes (entities matching the query), PPR simulates random walks through the graph. At each step, with probability (1-damping), the walk resets to a seed node. The resulting scores reflect how "reachable" each node is from the query context.

## Key Parameters

### damping_factor (default: 0.85)
- Higher (0.9-0.95): deeper exploration, more distant connections, slower convergence
- Lower (0.5-0.7): stays close to seeds, more focused results, faster convergence
- Use lower for specific queries ("what is X?")
- Use higher for exploratory queries ("what connects to X?")

### max_iterations (default: 20)
- Usually converges by 15-20 iterations
- Increase for very large graphs (>100K nodes)
- Decrease for faster response on small graphs

### top_k (default: 20)
- 5-10 for focused answers
- 20-50 for broad context gathering
- 100+ for full subgraph exploration

## Query Patterns

### Focused Retrieval
"What is FalkorDB?" → low damping (0.7), low top_k (10)

### Exploratory Retrieval
"What connects to knowledge graphs?" → high damping (0.9), high top_k (50)

### Temporal Queries
"What happened today?" → filter by date nodes first, then PPR from date

### Cross-Plugin Queries
"How does venture X relate to my journal?" → seed from both venture and journal namespaces

## Seed Node Selection

1. **Entity matching**: Direct name match in graph (exact or fuzzy)
2. **Embedding similarity**: Embed query, find top-k similar entity embeddings
3. **Hybrid**: Combine both, weight entity matches higher

## Tuning Workflow

1. Run query with defaults
2. If results too narrow: increase damping, increase top_k
3. If results too broad: decrease damping, decrease top_k
4. If missing expected results: check seed node selection, may need better entity extraction
5. Log queries and satisfaction for future tuning
