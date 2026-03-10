# /// script
# requires-python = ">=3.11"
# dependencies = ["redis", "httpx", "pyyaml"]
# ///
"""
Hippo retrieval pipeline — Pattern Completion.

Given a natural language query, finds seed entities in the knowledge graph,
runs Personalized PageRank in Python to discover related context, and returns
ranked results with provenance.

Usage:
    uv run hippo_recall.py "what do I know about FalkorDB?"
    uv run hippo_recall.py "gene keys shadow patterns" --mode exploratory
    uv run hippo_recall.py "legion hardware" --mode focused --top 5
    uv run hippo_recall.py "knowledge graphs" --json
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import httpx
import redis
import yaml

# --- Configuration ---

HIPPO_DIR = Path.home() / ".claude" / "local" / "hippo"
CONFIG_FILE = HIPPO_DIR / "config.yml"
SECRETS_FILE = Path.home() / ".claude" / "local" / "secrets" / "telus-api.env"
RETRIEVAL_LOG = HIPPO_DIR / "retrieval-log.jsonl"


def load_config() -> dict:
    with open(CONFIG_FILE) as f:
        return yaml.safe_load(f)


def load_secrets() -> dict:
    secrets = {}
    if SECRETS_FILE.exists():
        for line in SECRETS_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                secrets[key.strip()] = val.strip()
    return secrets


# --- FalkorDB ---

def get_redis(config: dict) -> redis.Redis:
    return redis.Redis(
        host=config["backend"]["host"],
        port=config["backend"]["port"],
        decode_responses=True,
    )


def graph_query(r: redis.Redis, db: str, cypher: str) -> list:
    return r.execute_command("GRAPH.QUERY", db, cypher)


def parse_graph_result(result: list) -> list[dict]:
    """Parse FalkorDB GRAPH.QUERY result into list of dicts."""
    if not result or len(result) < 2:
        return []
    header = result[0]
    rows = result[1] if len(result) > 1 else []
    if not header or not rows:
        return []
    return [dict(zip(header, row)) for row in rows]


# --- Entity extraction from query ---

def extract_query_entities(query: str, secrets: dict) -> list[str]:
    """Extract entity names from a natural language query using LLM."""
    url = secrets.get("TELUS_OLLAMA_URL", "")
    key = secrets.get("TELUS_OLLAMA_KEY", "")

    if not url or not key:
        return simple_entity_extract(query)

    prompt = f"""Extract the key entities (nouns, proper nouns, concepts) from this query.
Return ONLY a JSON array of lowercase strings, nothing else.

Query: {query}

Output format: ["entity1", "entity2"]"""

    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post(
                f"{url}/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": "gpt-oss:120b",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0,
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()
            if content.startswith("```"):
                content = re.sub(r"^```\w*\n?", "", content)
                content = re.sub(r"\n?```$", "", content)
            decoder = json.JSONDecoder()
            entities, _ = decoder.raw_decode(content.strip())
            if isinstance(entities, list):
                return [e.lower().strip() for e in entities if isinstance(e, str)]
    except Exception as e:
        print(f"  LLM entity extraction failed, using simple: {e}", file=sys.stderr)

    return simple_entity_extract(query)


def simple_entity_extract(query: str) -> list[str]:
    """Fallback: extract words, skip stopwords."""
    stopwords = {"what", "how", "why", "when", "where", "who", "is", "are", "was",
                 "were", "do", "does", "did", "the", "a", "an", "in", "on", "at",
                 "to", "for", "of", "with", "by", "from", "about", "i", "my", "me",
                 "know", "tell", "show", "find", "get", "related", "all"}
    words = re.findall(r'\b[a-zA-Z][\w-]*\b', query.lower())
    return [w for w in words if w not in stopwords and len(w) > 1]


# --- Embedding utilities ---

def embed_query(text: str, secrets: dict) -> list[float] | None:
    """Embed a query string via TELUS AI."""
    url = secrets.get("TELUS_EMBED_URL", "")
    key = secrets.get("TELUS_EMBED_KEY", "")
    if not url or not key:
        return None
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post(
                url,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "input": [text],
                    "model": "nvidia/nv-embedqa-e5-v5",
                    "input_type": "query",
                },
            )
            resp.raise_for_status()
            return resp.json()["data"][0]["embedding"]
    except Exception:
        return None


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# --- Seed node finding ---

def find_seed_nodes(r: redis.Redis, db: str, entities: list[str],
                    query_embedding: list[float] | None = None) -> list[str]:
    """Find graph nodes matching query entities via direct match, fuzzy match, and embedding similarity."""
    seeds = set()

    # 1. Direct name match
    for entity in entities:
        esc = entity.replace('"', '\\"')
        cypher = f'MATCH (n:Entity) WHERE n.name = "{esc}" RETURN n.name'
        try:
            for row in parse_graph_result(graph_query(r, db, cypher)):
                seeds.add(row["n.name"])
        except redis.exceptions.ResponseError:
            pass

    # 2. Fuzzy/CONTAINS match for entities not found directly
    for entity in entities:
        if any(entity in s or s in entity for s in seeds):
            continue
        esc = entity.replace('"', '\\"')
        cypher = f'MATCH (n:Entity) WHERE n.name CONTAINS "{esc}" RETURN n.name LIMIT 5'
        try:
            for row in parse_graph_result(graph_query(r, db, cypher)):
                seeds.add(row["n.name"])
        except redis.exceptions.ResponseError:
            pass

    # 3. Embedding similarity (if query embedding available and few seeds found)
    if query_embedding and len(seeds) < 5:
        cypher = 'MATCH (n:Entity) WHERE n.embedding IS NOT NULL RETURN n.name, n.embedding'
        try:
            rows = parse_graph_result(graph_query(r, db, cypher))
            similarities = []
            for row in rows:
                try:
                    node_emb = json.loads(row["n.embedding"])
                    sim = cosine_similarity(query_embedding, node_emb)
                    similarities.append((row["n.name"], sim))
                except (json.JSONDecodeError, TypeError):
                    continue
            # Add top-5 similar entities not already in seeds
            similarities.sort(key=lambda x: x[1], reverse=True)
            for name, sim in similarities[:5]:
                if sim > 0.5 and name not in seeds:
                    seeds.add(name)
        except redis.exceptions.ResponseError:
            pass

    return list(seeds)


# --- Pull subgraph into Python ---

def pull_graph(r: redis.Redis, db: str) -> tuple[dict, dict, set, dict]:
    """Pull the entire edge list into Python for PPR computation.

    Returns:
        adj_out: {src: [(dst, weight), ...]}
        adj_in:  {dst: [(src, weight), ...]}
        all_nodes: set of all node names
        edge_meta: {(src, dst): {weight, source}}
    """
    cypher = """
    MATCH (s:Entity)-[r:RELATES]->(o:Entity)
    RETURN s.name AS src, o.name AS dst, r.weight AS weight, r.source AS source
    """
    rows = parse_graph_result(graph_query(r, db, cypher))

    adj_out = defaultdict(list)
    adj_in = defaultdict(list)
    all_nodes = set()
    edge_meta = {}

    for row in rows:
        src = row["src"]
        dst = row["dst"]
        w = float(row["weight"]) if row["weight"] else 1.0
        all_nodes.add(src)
        all_nodes.add(dst)
        adj_out[src].append((dst, w))
        adj_in[dst].append((src, w))
        edge_meta[(src, dst)] = {"weight": w, "source": row.get("source", "")}

    return adj_out, adj_in, all_nodes, edge_meta


def run_ppr(adj_out: dict, adj_in: dict, all_nodes: set,
            seeds: list[str], damping: float = 0.85,
            iterations: int = 30, epsilon: float = 1e-6) -> dict[str, float]:
    """Personalized PageRank computed in Python.

    Standard PPR formula:
      score(v) = (1-d) * personalization(v) + d * sum(score(u) * w(u,v) / out_weight(u))

    where d = damping, personalization is uniform over seeds.
    Scores are normalized to sum to 1.
    """
    n = len(all_nodes)
    if n == 0:
        return {}

    # Personalization vector: uniform over seeds
    seed_set = set(seeds) & all_nodes
    if not seed_set:
        return {}
    p = {node: (1.0 / len(seed_set) if node in seed_set else 0.0) for node in all_nodes}

    # Initialize scores to personalization vector
    scores = dict(p)

    # Precompute out-degree weight sums for normalization
    out_weight_sum = {}
    for node in all_nodes:
        total = sum(w for _, w in adj_out.get(node, []))
        out_weight_sum[node] = total if total > 0 else 1.0

    for iteration in range(iterations):
        new_scores = {}
        max_delta = 0.0

        for node in all_nodes:
            # Sum incoming contributions (normalized by source out-weight)
            incoming = 0.0
            for src, w in adj_in.get(node, []):
                incoming += scores.get(src, 0.0) * (w / out_weight_sum[src])

            new_scores[node] = (1 - damping) * p[node] + damping * incoming
            max_delta = max(max_delta, abs(new_scores[node] - scores.get(node, 0.0)))

        scores = new_scores

        if max_delta < epsilon:
            break

    return scores


# --- Context assembly ---

def get_entity_context(r: redis.Redis, db: str, entity: str) -> list[dict]:
    """Get all relationships for an entity."""
    esc = entity.replace('"', '\\"')

    cypher_out = f"""
    MATCH (s:Entity {{name: "{esc}"}})-[r:RELATES]->(o:Entity)
    RETURN s.name AS subject, r.type AS relation, o.name AS object,
           r.source AS source, r.weight AS weight
    ORDER BY r.weight DESC LIMIT 10
    """
    cypher_in = f"""
    MATCH (s:Entity)-[r:RELATES]->(o:Entity {{name: "{esc}"}})
    RETURN s.name AS subject, r.type AS relation, o.name AS object,
           r.source AS source, r.weight AS weight
    ORDER BY r.weight DESC LIMIT 10
    """

    context = []
    for cypher in [cypher_out, cypher_in]:
        try:
            context.extend(parse_graph_result(graph_query(r, db, cypher)))
        except redis.exceptions.ResponseError:
            pass

    return context


def format_results(ranked: list[dict], contexts: dict[str, list[dict]],
                   output_json: bool = False) -> str:
    """Format retrieval results for display."""
    if output_json:
        return json.dumps({
            "results": [
                {
                    "entity": r["entity"],
                    "score": round(r["score"], 6),
                    "relationships": contexts.get(r["entity"], []),
                }
                for r in ranked
            ]
        }, indent=2)

    lines = []
    for i, r in enumerate(ranked, 1):
        score = r["score"]
        entity = r["entity"]
        lines.append(f"\n{i}. [{score:.4f}] {entity}")

        ctx = contexts.get(entity, [])
        seen = set()
        for c in ctx[:5]:
            triple_key = f"{c['subject']}|{c['relation']}|{c['object']}"
            if triple_key not in seen:
                seen.add(triple_key)
                source = c.get("source", "")
                weight = c.get("weight", 1.0)
                lines.append(f"     {c['subject']} —{c['relation']}→ {c['object']}  (w:{weight}, src:{source})")

    return "\n".join(lines)


# --- Logging ---

def log_retrieval(query: str, entities: list[str], seeds: list[str],
                  mode: str, result_count: int):
    """Log retrieval for consolidation strengthening."""
    from datetime import datetime, timezone
    HIPPO_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "query": query,
        "entities": entities,
        "seeds": seeds,
        "mode": mode,
        "results": result_count,
    }
    with open(RETRIEVAL_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


# --- Query modes ---

MODES = {
    "focused":     {"damping": 0.70, "top_k": 5,  "desc": "specific factual lookups"},
    "balanced":    {"damping": 0.85, "top_k": 10, "desc": "general queries"},
    "exploratory": {"damping": 0.92, "top_k": 20, "desc": "discover connections"},
}


def main():
    parser = argparse.ArgumentParser(description="Hippo retrieval — Pattern Completion")
    parser.add_argument("query", help="Natural language query")
    parser.add_argument("--mode", choices=MODES.keys(), default="balanced",
                        help="Query mode: focused, balanced (default), exploratory")
    parser.add_argument("--top", type=int, help="Override top-K results")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--seeds-only", action="store_true",
                        help="Only show seed nodes, skip PPR")
    args = parser.parse_args()

    if not CONFIG_FILE.exists():
        print("Error: Hippo not initialized.", file=sys.stderr)
        sys.exit(1)

    config = load_config()
    secrets = load_secrets()
    r = get_redis(config)
    db = config["backend"]["database"]

    try:
        r.ping()
    except redis.ConnectionError:
        print("Error: FalkorDB unreachable on port 6380.", file=sys.stderr)
        sys.exit(1)

    # Step 1: Extract entities from query
    entities = extract_query_entities(args.query, secrets)
    if not entities:
        print("No entities extracted from query.", file=sys.stderr)
        sys.exit(1)

    if not args.json:
        print(f"Query entities: {entities}")

    # Step 2: Find seed nodes (with optional embedding similarity)
    query_emb = embed_query(args.query, secrets)
    seeds = find_seed_nodes(r, db, entities, query_embedding=query_emb)
    if not seeds:
        print("No matching nodes found in graph.", file=sys.stderr)
        sys.exit(1)

    if not args.json:
        print(f"Seed nodes ({len(seeds)}): {seeds[:10]}{'...' if len(seeds) > 10 else ''}")

    if args.seeds_only:
        for s in seeds:
            ctx = get_entity_context(r, db, s)
            print(f"\n--- {s} ---")
            for c in ctx:
                print(f"  {c['subject']} —{c['relation']}→ {c['object']}  (src:{c.get('source','')})")
        return

    # Step 3: Pull graph and run PPR in Python
    mode = MODES[args.mode]
    top_k = args.top or mode["top_k"]
    damping = mode["damping"]

    if not args.json:
        print(f"Running PPR (mode={args.mode}, damping={damping}, top_k={top_k})...")

    adj_out, adj_in, all_nodes, edge_meta = pull_graph(r, db)

    if not all_nodes:
        print("Graph is empty.", file=sys.stderr)
        sys.exit(1)

    scores = run_ppr(adj_out, adj_in, all_nodes, seeds, damping=damping)

    # Rank by score, exclude near-zero
    ranked_all = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    ranked = [{"entity": name, "score": score}
              for name, score in ranked_all[:top_k] if score > 1e-6]

    if not ranked:
        print("No results from PPR.", file=sys.stderr)
        sys.exit(1)

    # Step 4: Get context for top results
    contexts = {}
    for item in ranked:
        contexts[item["entity"]] = get_entity_context(r, db, item["entity"])

    # Step 5: Log retrieval (for consolidation strengthening)
    log_retrieval(args.query, entities, seeds, args.mode, len(ranked))

    # Step 6: Format and output
    output = format_results(ranked, contexts, output_json=args.json)
    print(output)


if __name__ == "__main__":
    main()
