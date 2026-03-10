# /// script
# requires-python = ">=3.11"
# dependencies = ["redis", "httpx", "pyyaml"]
# ///
"""
Hippo retrieval pipeline — Pattern Completion.

Given a natural language query, finds seed entities in the knowledge graph,
runs Personalized PageRank to discover related context, and returns
ranked results with provenance.

Usage:
    uv run hippo_recall.py "what do I know about FalkorDB?"
    uv run hippo_recall.py "gene keys shadow patterns" --mode exploratory
    uv run hippo_recall.py "legion hardware" --mode focused --top 5
    uv run hippo_recall.py "knowledge graphs" --json
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

import httpx
import redis
import yaml

# --- Configuration ---

HIPPO_DIR = Path.home() / ".claude" / "local" / "hippo"
CONFIG_FILE = HIPPO_DIR / "config.yml"
SECRETS_FILE = Path.home() / ".claude" / "local" / "secrets" / "telus-api.env"


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
        # Fallback: simple word extraction
        return simple_entity_extract(query)

    prompt = f"""Extract the key entities (nouns, proper nouns, concepts) from this query.
Return ONLY a JSON array of lowercase strings, nothing else.

Query: {query}

Example output: ["falkordb", "knowledge graph", "legion"]"""

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
            # Strip code blocks
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


# --- Seed node finding ---

def find_seed_nodes(r: redis.Redis, db: str, entities: list[str]) -> list[str]:
    """Find graph nodes matching query entities via direct and fuzzy match."""
    seeds = set()

    # Direct match
    for entity in entities:
        esc = entity.replace('"', '\\"')
        cypher = f'MATCH (n:Entity) WHERE n.name = "{esc}" RETURN n.name'
        try:
            result = parse_graph_result(graph_query(r, db, cypher))
            for row in result:
                seeds.add(row["n.name"])
        except redis.exceptions.ResponseError:
            pass

    # Fuzzy/CONTAINS match for entities not found directly
    for entity in entities:
        if entity in seeds:
            continue
        esc = entity.replace('"', '\\"')
        cypher = f'MATCH (n:Entity) WHERE n.name CONTAINS "{esc}" RETURN n.name LIMIT 5'
        try:
            result = parse_graph_result(graph_query(r, db, cypher))
            for row in result:
                seeds.add(row["n.name"])
        except redis.exceptions.ResponseError:
            pass

    return list(seeds)


# --- Personalized PageRank ---

def run_ppr(r: redis.Redis, db: str, seeds: list[str],
            damping: float = 0.85, iterations: int = 20,
            top_k: int = 10) -> list[dict]:
    """Run Personalized PageRank from seed nodes.

    Since FalkorDB doesn't have native PPR, we implement it
    iteratively via Cypher queries.
    """
    if not seeds:
        return []

    # Initialize: set ppr scores on all nodes to 0
    graph_query(r, db, "MATCH (n:Entity) SET n.ppr = 0.0")

    # Set seed scores
    seed_score = 1.0 / len(seeds)
    for seed in seeds:
        esc = seed.replace('"', '\\"')
        graph_query(r, db, f'MATCH (n:Entity {{name: "{esc}"}}) SET n.ppr = {seed_score}')

    # Get total node count for teleport
    result = parse_graph_result(graph_query(r, db, "MATCH (n:Entity) RETURN COUNT(n) AS cnt"))
    total = result[0]["cnt"] if result else 1

    # PPR iterations
    teleport = (1 - damping) / total
    seed_filter = " OR ".join(f'n.name = "{s.replace(chr(34), chr(92)+chr(34))}"' for s in seeds)

    for i in range(iterations):
        # Spread activation through edges (weight-aware)
        cypher = f"""
        MATCH (n:Entity)-[r:RELATES]->(m:Entity)
        WHERE n.ppr > 0.001
        WITH m, SUM(n.ppr * r.weight) AS incoming
        SET m.ppr = {teleport} + {damping} * incoming
        """
        try:
            graph_query(r, db, cypher)
        except redis.exceptions.ResponseError as e:
            print(f"  PPR iteration {i} warning: {e}", file=sys.stderr)
            break

        # Re-inject seed bias (teleport back to seeds)
        for seed in seeds:
            esc = seed.replace('"', '\\"')
            graph_query(r, db,
                f'MATCH (n:Entity {{name: "{esc}"}}) SET n.ppr = n.ppr + {seed_score * (1 - damping)}')

    # Collect top-K results
    cypher = f"""
    MATCH (n:Entity)
    WHERE n.ppr > 0.001
    RETURN n.name AS entity, n.ppr AS score
    ORDER BY n.ppr DESC
    LIMIT {top_k}
    """
    results = parse_graph_result(graph_query(r, db, cypher))

    # Clean up ppr scores
    graph_query(r, db, "MATCH (n:Entity) SET n.ppr = 0.0")

    return results


# --- Context assembly ---

def get_entity_context(r: redis.Redis, db: str, entity: str) -> list[dict]:
    """Get all relationships for an entity."""
    esc = entity.replace('"', '\\"')

    # Outgoing
    cypher_out = f"""
    MATCH (s:Entity {{name: "{esc}"}})-[r:RELATES]->(o:Entity)
    RETURN s.name AS subject, r.type AS relation, o.name AS object,
           r.source AS source, r.weight AS weight
    ORDER BY r.weight DESC LIMIT 10
    """
    # Incoming
    cypher_in = f"""
    MATCH (s:Entity)-[r:RELATES]->(o:Entity {{name: "{esc}"}})
    RETURN s.name AS subject, r.type AS relation, o.name AS object,
           r.source AS source, r.weight AS weight
    ORDER BY r.weight DESC LIMIT 10
    """

    context = []
    try:
        out = parse_graph_result(graph_query(r, db, cypher_out))
        context.extend(out)
    except redis.exceptions.ResponseError:
        pass
    try:
        inp = parse_graph_result(graph_query(r, db, cypher_in))
        context.extend(inp)
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
                    "score": round(float(r["score"]), 4),
                    "relationships": contexts.get(r["entity"], []),
                }
                for r in ranked
            ]
        }, indent=2)

    lines = []
    for i, r in enumerate(ranked, 1):
        score = float(r["score"])
        entity = r["entity"]
        lines.append(f"\n{i}. [{score:.3f}] {entity}")

        ctx = contexts.get(entity, [])
        seen = set()
        for c in ctx[:5]:
            triple = f"  {c['subject']} —{c['relation']}→ {c['object']}"
            if triple not in seen:
                seen.add(triple)
                source = c.get("source", "")
                weight = c.get("weight", 1.0)
                lines.append(f"  {triple}  (w:{weight}, src:{source})")

    return "\n".join(lines)


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
                        help="Query mode: focused (specific), balanced (default), exploratory (broad)")
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

    # Step 1: Extract entities
    entities = extract_query_entities(args.query, secrets)
    if not entities:
        print("No entities extracted from query.", file=sys.stderr)
        sys.exit(1)

    if not args.json:
        print(f"Query entities: {entities}")

    # Step 2: Find seeds
    seeds = find_seed_nodes(r, db, entities)
    if not seeds:
        print("No matching nodes found in graph.", file=sys.stderr)
        sys.exit(1)

    if not args.json:
        print(f"Seed nodes: {seeds}")

    if args.seeds_only:
        for s in seeds:
            ctx = get_entity_context(r, db, s)
            print(f"\n--- {s} ---")
            for c in ctx:
                print(f"  {c['subject']} —{c['relation']}→ {c['object']}  (src:{c.get('source','')})")
        return

    # Step 3: PPR
    mode = MODES[args.mode]
    top_k = args.top or mode["top_k"]
    damping = mode["damping"]

    if not args.json:
        print(f"Running PPR (mode={args.mode}, damping={damping}, top_k={top_k})...")

    ranked = run_ppr(r, db, seeds, damping=damping, top_k=top_k)

    if not ranked:
        print("No results from PPR.", file=sys.stderr)
        sys.exit(1)

    # Step 4: Get context for each result
    contexts = {}
    for r_item in ranked:
        entity = r_item["entity"]
        contexts[entity] = get_entity_context(r, db, entity)

    # Step 5: Format and output
    output = format_results(ranked, contexts, output_json=args.json)
    print(output)


if __name__ == "__main__":
    main()
