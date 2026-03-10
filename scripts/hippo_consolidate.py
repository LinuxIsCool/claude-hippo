# /// script
# requires-python = ">=3.11"
# dependencies = ["redis", "httpx", "pyyaml"]
# ///
"""
Hippo consolidation pipeline — Memory Strengthening.

Manages knowledge graph health: strengthen accessed edges,
decay unused ones, prune weak connections, merge duplicate entities.

Usage:
    uv run hippo_consolidate.py                   # full consolidation
    uv run hippo_consolidate.py --strengthen       # only strengthen
    uv run hippo_consolidate.py --decay            # only decay
    uv run hippo_consolidate.py --prune            # only prune
    uv run hippo_consolidate.py --schema           # merge duplicates + normalize
    uv run hippo_consolidate.py --stats            # show graph health stats
"""

import argparse
import json
import math
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import redis
import yaml

# --- Configuration ---

HIPPO_DIR = Path.home() / ".claude" / "local" / "hippo"
CONFIG_FILE = HIPPO_DIR / "config.yml"
CONSOLIDATION_LOG = HIPPO_DIR / "consolidation-log.jsonl"
RETRIEVAL_LOG = HIPPO_DIR / "retrieval-log.jsonl"
PRUNE_LOG = HIPPO_DIR / "prune-log.jsonl"


def load_config() -> dict:
    with open(CONFIG_FILE) as f:
        return yaml.safe_load(f)


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
    if not result or len(result) < 2:
        return []
    header = result[0]
    rows = result[1] if len(result) > 1 else []
    if not header or not rows:
        return []
    return [dict(zip(header, row)) for row in rows]


# --- Strengthen ---

def strengthen(r: redis.Redis, db: str, config: dict) -> dict:
    """Strengthen edges that were accessed via retrieval since last consolidation."""
    increment = config.get("consolidation", {}).get("strengthen_increment", 0.1)
    max_weight = config.get("consolidation", {}).get("max_edge_weight", 10.0)

    # Find last consolidation timestamp
    last_ts = None
    if CONSOLIDATION_LOG.exists():
        try:
            lines = CONSOLIDATION_LOG.read_text().strip().split("\n")
            for line in reversed(lines):
                if line.strip():
                    entry = json.loads(line)
                    if entry.get("operation") in ("full", "strengthen"):
                        last_ts = entry["timestamp"]
                        break
        except (json.JSONDecodeError, KeyError):
            pass

    # Read retrieval log for recently accessed entities
    accessed_entities = set()
    if RETRIEVAL_LOG.exists():
        for line in RETRIEVAL_LOG.read_text().strip().split("\n"):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
                ts = entry.get("timestamp", "")
                if last_ts and ts <= last_ts:
                    continue
                for seed in entry.get("seeds", []):
                    accessed_entities.add(seed)
            except json.JSONDecodeError:
                continue

    if not accessed_entities:
        print("  No recently accessed entities to strengthen.")
        return {"edges_strengthened": 0}

    strengthened = 0
    for entity in accessed_entities:
        esc = entity.replace('"', '\\"')
        # Strengthen outgoing edges
        cypher = f"""
        MATCH (n:Entity {{name: "{esc}"}})-[r:RELATES]->()
        WHERE r.weight < {max_weight}
        SET r.weight = CASE WHEN r.weight + {increment} > {max_weight}
                            THEN {max_weight}
                            ELSE r.weight + {increment} END,
            r.last_accessed = "{datetime.now(timezone.utc).isoformat()}"
        RETURN COUNT(r) AS cnt
        """
        try:
            result = parse_graph_result(graph_query(r, db, cypher))
            if result:
                strengthened += result[0].get("cnt", 0)
        except redis.exceptions.ResponseError:
            pass

        # Strengthen incoming edges
        cypher = f"""
        MATCH ()-[r:RELATES]->(n:Entity {{name: "{esc}"}})
        WHERE r.weight < {max_weight}
        SET r.weight = CASE WHEN r.weight + {increment} > {max_weight}
                            THEN {max_weight}
                            ELSE r.weight + {increment} END,
            r.last_accessed = "{datetime.now(timezone.utc).isoformat()}"
        RETURN COUNT(r) AS cnt
        """
        try:
            result = parse_graph_result(graph_query(r, db, cypher))
            if result:
                strengthened += result[0].get("cnt", 0)
        except redis.exceptions.ResponseError:
            pass

    print(f"  Strengthened {strengthened} edges from {len(accessed_entities)} accessed entities.")
    return {"edges_strengthened": strengthened}


# --- Decay ---

def decay(r: redis.Redis, db: str, config: dict) -> dict:
    """Apply temporal decay to all edge weights based on last access time."""
    halflife_days = config.get("consolidation", {}).get("decay_halflife_days", 30)
    now = datetime.now(timezone.utc)
    lambda_decay = math.log(2) / halflife_days

    # Get all edges with timestamps
    cypher = """
    MATCH (s:Entity)-[r:RELATES]->(o:Entity)
    RETURN ID(s) AS sid, s.name AS src, ID(o) AS oid, o.name AS dst,
           r.weight AS weight, r.last_accessed AS last_accessed, r.source AS source
    """
    rows = parse_graph_result(graph_query(r, db, cypher))

    decayed = 0
    for row in rows:
        last_accessed = row.get("last_accessed", "")
        weight = float(row.get("weight", 1.0))

        if not last_accessed:
            continue

        try:
            la_dt = datetime.fromisoformat(last_accessed.replace("Z", "+00:00"))
            days_since = (now - la_dt).total_seconds() / 86400
        except (ValueError, TypeError):
            continue

        if days_since < 0.5:
            continue  # Don't decay very recent edges

        new_weight = weight * math.exp(-lambda_decay * days_since)
        if abs(new_weight - weight) < 0.001:
            continue  # Skip negligible changes

        src_esc = row["src"].replace('"', '\\"')
        dst_esc = row["dst"].replace('"', '\\"')
        cypher_update = f"""
        MATCH (s:Entity {{name: "{src_esc}"}})-[r:RELATES]->(o:Entity {{name: "{dst_esc}"}})
        SET r.weight = {new_weight:.6f}
        """
        try:
            graph_query(r, db, cypher_update)
            decayed += 1
        except redis.exceptions.ResponseError:
            pass

    print(f"  Decayed {decayed} edges (halflife: {halflife_days} days).")
    return {"edges_decayed": decayed}


# --- Prune ---

def prune(r: redis.Redis, db: str, config: dict) -> dict:
    """Remove edges below weight threshold and orphaned nodes."""
    threshold = config.get("consolidation", {}).get("prune_threshold", 0.1)
    now_iso = datetime.now(timezone.utc).isoformat()

    # Find edges below threshold
    cypher = f"""
    MATCH (s:Entity)-[r:RELATES]->(o:Entity)
    WHERE r.weight < {threshold}
    RETURN s.name AS src, r.type AS rel, o.name AS dst, r.weight AS weight, r.source AS source
    """
    weak_edges = parse_graph_result(graph_query(r, db, cypher))

    # Log before deleting
    if weak_edges:
        with open(PRUNE_LOG, "a") as f:
            for edge in weak_edges:
                f.write(json.dumps({
                    "timestamp": now_iso,
                    "operation": "prune_edge",
                    "src": edge["src"],
                    "rel": edge["rel"],
                    "dst": edge["dst"],
                    "weight": edge["weight"],
                    "source": edge.get("source", ""),
                }) + "\n")

    # Delete weak edges
    cypher_delete = f"""
    MATCH ()-[r:RELATES]->()
    WHERE r.weight < {threshold}
    DELETE r
    RETURN COUNT(r) AS cnt
    """
    result = parse_graph_result(graph_query(r, db, cypher_delete))
    edges_pruned = result[0]["cnt"] if result else 0

    # Find and remove orphaned nodes (no edges in either direction)
    # FalkorDB doesn't support EXISTS() in WHERE, so use OPTIONAL MATCH approach
    cypher_orphans = """
    MATCH (n:Entity)
    OPTIONAL MATCH (n)-[r1:RELATES]->()
    OPTIONAL MATCH ()-[r2:RELATES]->(n)
    WITH n, r1, r2
    WHERE r1 IS NULL AND r2 IS NULL
    DELETE n
    RETURN COUNT(n) AS cnt
    """
    try:
        result = parse_graph_result(graph_query(r, db, cypher_orphans))
        nodes_pruned = result[0]["cnt"] if result else 0
    except redis.exceptions.ResponseError:
        # Fallback: skip orphan cleanup if Cypher variant not supported
        nodes_pruned = 0

    print(f"  Pruned {edges_pruned} edges (threshold: {threshold}), {nodes_pruned} orphan nodes.")
    return {"edges_pruned": edges_pruned, "nodes_pruned": nodes_pruned}


# --- Schema normalization ---

def normalize_schema(r: redis.Redis, db: str) -> dict:
    """Normalize relation types and detect duplicate entities."""
    # 1. Find duplicate relation types that should be merged
    cypher = """
    MATCH ()-[r:RELATES]->()
    RETURN DISTINCT r.type AS rel_type, COUNT(r) AS cnt
    ORDER BY cnt DESC
    """
    rels = parse_graph_result(graph_query(r, db, cypher))

    normalized = 0
    for rel in rels:
        rel_type = rel["rel_type"]
        if not rel_type:
            continue
        # Normalize: lowercase, spaces to hyphens
        clean = rel_type.lower().strip().replace(" ", "-").replace("_", "-")
        if clean != rel_type:
            esc_old = rel_type.replace('"', '\\"')
            esc_new = clean.replace('"', '\\"')
            cypher_update = f"""
            MATCH ()-[r:RELATES]->()
            WHERE r.type = "{esc_old}"
            SET r.type = "{esc_new}"
            RETURN COUNT(r) AS cnt
            """
            try:
                result = parse_graph_result(graph_query(r, db, cypher_update))
                if result:
                    normalized += result[0].get("cnt", 0)
            except redis.exceptions.ResponseError:
                pass

    # 2. Find potential duplicate entities by embedding similarity
    # (This is expensive — only do it on-demand)
    cypher = """
    MATCH (n:Entity)
    WHERE n.embedding IS NOT NULL
    RETURN n.name, n.embedding
    """
    rows = parse_graph_result(graph_query(r, db, cypher))

    # Build a simple map for similarity checking
    merge_candidates = []
    if len(rows) > 1:
        # Only check entities with similar names first (cheap filter)
        names = [r["n.name"] for r in rows]
        for i, name_a in enumerate(names):
            for j in range(i + 1, min(i + 50, len(names))):  # Check nearby names
                name_b = names[j]
                # Quick string similarity check
                if name_a in name_b or name_b in name_a:
                    if name_a != name_b and len(name_a) > 3 and len(name_b) > 3:
                        merge_candidates.append((name_a, name_b))

    print(f"  Schema: {normalized} relations normalized, {len(merge_candidates)} merge candidates found.")
    if merge_candidates:
        print(f"  Merge candidates (review manually):")
        for a, b in merge_candidates[:10]:
            print(f"    '{a}' ↔ '{b}'")

    return {"relations_normalized": normalized, "merge_candidates": len(merge_candidates)}


# --- Stats ---

def show_stats(r: redis.Redis, db: str, config: dict):
    """Show graph health statistics."""
    # Node and edge counts
    nodes = parse_graph_result(graph_query(r, db, "MATCH (n:Entity) RETURN COUNT(n) AS cnt"))
    edges = parse_graph_result(graph_query(r, db, "MATCH ()-[r:RELATES]->() RETURN COUNT(r) AS cnt"))

    node_count = nodes[0]["cnt"] if nodes else 0
    edge_count = edges[0]["cnt"] if edges else 0

    # Embedding coverage
    with_emb = parse_graph_result(graph_query(r, db,
        "MATCH (n:Entity) WHERE n.embedding IS NOT NULL RETURN COUNT(n) AS cnt"))
    emb_count = with_emb[0]["cnt"] if with_emb else 0

    # Weight distribution
    weight_dist = parse_graph_result(graph_query(r, db, """
    MATCH ()-[r:RELATES]->()
    RETURN
        MIN(r.weight) AS min_w,
        MAX(r.weight) AS max_w,
        AVG(r.weight) AS avg_w
    """))

    # Top connected nodes
    hubs = parse_graph_result(graph_query(r, db, """
    MATCH (n:Entity)
    RETURN n.name AS name,
           SIZE([(n)-[:RELATES]->() | 1]) + SIZE([()-[:RELATES]->(n) | 1]) AS degree
    ORDER BY degree DESC
    LIMIT 10
    """))

    # Source distribution
    sources = parse_graph_result(graph_query(r, db, """
    MATCH ()-[r:RELATES]->()
    WITH SPLIT(r.source, ':')[0] AS namespace, COUNT(r) AS cnt
    RETURN namespace, cnt
    ORDER BY cnt DESC
    """))

    threshold = config.get("consolidation", {}).get("prune_threshold", 0.1)
    weak = parse_graph_result(graph_query(r, db,
        f"MATCH ()-[r:RELATES]->() WHERE r.weight < {threshold} RETURN COUNT(r) AS cnt"))
    weak_count = weak[0]["cnt"] if weak else 0

    print(f"\n=== Hippo Graph Health ===")
    print(f"Nodes: {node_count:,}  |  Edges: {edge_count:,}  |  Embeddings: {emb_count:,}/{node_count:,}")

    if weight_dist:
        wd = weight_dist[0]
        print(f"Weight: min={float(wd['min_w']):.2f}  avg={float(wd['avg_w']):.2f}  max={float(wd['max_w']):.2f}")

    print(f"Weak edges (below {threshold}): {weak_count}")

    if sources:
        print(f"\nEdges by source namespace:")
        for s in sources:
            print(f"  {s['namespace']}: {s['cnt']}")

    if hubs:
        print(f"\nTop connected entities:")
        for h in hubs:
            print(f"  {h['name']}: {h['degree']} connections")

    # Last consolidation
    if CONSOLIDATION_LOG.exists():
        lines = CONSOLIDATION_LOG.read_text().strip().split("\n")
        for line in reversed(lines):
            if line.strip():
                try:
                    entry = json.loads(line)
                    print(f"\nLast consolidation: {entry.get('timestamp', 'unknown')} ({entry.get('operation', '')})")
                except json.JSONDecodeError:
                    pass
                break

    # Retrieval count
    if RETRIEVAL_LOG.exists():
        retrieval_count = sum(1 for l in RETRIEVAL_LOG.read_text().strip().split("\n") if l.strip())
        print(f"Total retrievals logged: {retrieval_count}")

    print()


# --- Main ---

def main():
    parser = argparse.ArgumentParser(description="Hippo consolidation — Memory Strengthening")
    parser.add_argument("--strengthen", action="store_true", help="Strengthen recently accessed edges")
    parser.add_argument("--decay", action="store_true", help="Apply temporal decay")
    parser.add_argument("--prune", action="store_true", help="Remove weak edges and orphans")
    parser.add_argument("--schema", action="store_true", help="Normalize relations, find duplicates")
    parser.add_argument("--stats", action="store_true", help="Show graph health statistics")
    args = parser.parse_args()

    if not CONFIG_FILE.exists():
        print("Error: Hippo not initialized.", file=sys.stderr)
        sys.exit(1)

    config = load_config()
    r = get_redis(config)
    db = config["backend"]["database"]

    try:
        r.ping()
    except redis.ConnectionError:
        print("Error: FalkorDB unreachable on port 6380.", file=sys.stderr)
        sys.exit(1)

    if args.stats:
        show_stats(r, db, config)
        return

    # If no specific mode, run full consolidation
    full = not (args.strengthen or args.decay or args.prune or args.schema)
    start_time = time.time()
    results = {}

    if full or args.strengthen:
        print("Strengthening...")
        results.update(strengthen(r, db, config))

    if full or args.decay:
        print("Decaying...")
        results.update(decay(r, db, config))

    if full or args.prune:
        print("Pruning...")
        results.update(prune(r, db, config))

    if full or args.schema:
        print("Schema normalization...")
        results.update(normalize_schema(r, db))

    duration_ms = int((time.time() - start_time) * 1000)
    operation = "full" if full else "+".join(
        k for k in ["strengthen", "decay", "prune", "schema"]
        if getattr(args, k, False)
    )

    # Log consolidation
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "operation": operation,
        "duration_ms": duration_ms,
        **results,
    }
    HIPPO_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONSOLIDATION_LOG, "a") as f:
        f.write(json.dumps(log_entry) + "\n")

    print(f"\nConsolidation complete ({operation}) in {duration_ms}ms")
    for k, v in results.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
