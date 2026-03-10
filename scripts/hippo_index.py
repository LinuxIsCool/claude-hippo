# /// script
# requires-python = ">=3.11"
# dependencies = ["redis", "httpx", "pyyaml"]
# ///
"""
Hippo indexing pipeline — Pattern Separation.

Reads markdown documents, extracts triples via TELUS Ollama,
embeds entities via TELUS AI, inserts into FalkorDB.

Usage:
    uv run hippo_index.py <path> [--type journal|venture|task|ground|inventory]
    uv run hippo_index.py --all
    uv run hippo_index.py --pending
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import redis
import yaml

# --- Configuration ---

HIPPO_DIR = Path.home() / ".claude" / "local" / "hippo"
CONFIG_FILE = HIPPO_DIR / "config.yml"
EPISODES_DIR = HIPPO_DIR / "episodes"
EXTRACTION_LOG = HIPPO_DIR / "extraction-log.jsonl"
PENDING_FILE = HIPPO_DIR / ".pending-index"
SECRETS_FILE = Path.home() / ".claude" / "local" / "secrets" / "telus-api.env"


def load_config() -> dict:
    with open(CONFIG_FILE) as f:
        return yaml.safe_load(f)


def load_secrets() -> dict:
    """Parse the env file into a dict."""
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


def graph_query(r: redis.Redis, db: str, cypher: str, params: dict | None = None) -> list:
    """Execute a FalkorDB graph query."""
    if params:
        # FalkorDB parameterized query format
        param_str = "CYPHER " + " ".join(f"{k}={json.dumps(v)}" for k, v in params.items()) + " "
        cypher = param_str + cypher
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


def insert_triple(r: redis.Redis, db: str, subject: str, relation: str, obj: str,
                  source: str, timestamp: str):
    """Insert a single triple into the graph."""
    # Escape quotes in strings
    s = subject.replace("'", "\\'").replace('"', '\\"')
    rel = relation.replace("'", "\\'").replace('"', '\\"')
    o = obj.replace("'", "\\'").replace('"', '\\"')

    cypher = f"""
    MERGE (s:Entity {{name: "{s}"}})
    ON CREATE SET s.created = "{timestamp}"
    MERGE (o:Entity {{name: "{o}"}})
    ON CREATE SET o.created = "{timestamp}"
    MERGE (s)-[r:RELATES {{type: "{rel}"}}]->(o)
    ON CREATE SET r.weight = 1.0, r.source = "{source}", r.last_accessed = "{timestamp}"
    ON MATCH SET r.weight = r.weight + 0.1, r.last_accessed = "{timestamp}"
    """
    try:
        graph_query(r, db, cypher)
    except redis.exceptions.ResponseError as e:
        print(f"  Warning: Failed to insert ({subject}, {relation}, {obj}): {e}", file=sys.stderr)


# --- TELUS AI ---

def extract_triples(text: str, content_type: str, secrets: dict) -> list[dict]:
    """Call TELUS Ollama to extract triples from text."""
    url = secrets.get("TELUS_OLLAMA_URL", "")
    key = secrets.get("TELUS_OLLAMA_KEY", "")

    if not url or not key:
        print("Error: TELUS_OLLAMA_URL or TELUS_OLLAMA_KEY not set", file=sys.stderr)
        return []

    type_hints = {
        "journal": "Focus on: decisions made, tools mentioned, people, ventures, events, reflections.",
        "venture": "Focus on: goals, milestones, stakeholders, technologies, status, deadlines.",
        "task": "Focus on: deliverables, blockers, assignees, milestones, completion criteria.",
        "ground": "Focus on: Gene Key identity, shadow patterns, gift emergences, frequency, connections.",
        "inventory": "Focus on: hardware, software, services, specs, metrics, status.",
    }
    hint = type_hints.get(content_type, "Extract all meaningful entities and relationships.")

    prompt = f"""Extract entities and relationships from this text as JSON triples.

Rules:
- Entities should be specific and normalized (proper nouns preserved, common nouns lowercase)
- Relations should be verb phrases (e.g., "decided-to-use", "is-a", "relates-to")
- Keep entities concise (1-4 words)
- SKIP placeholder values like "none", "not yet", "not yet observed", "unknown", "0", "true", "false", "null"
- SKIP template text in square brackets like "[Not yet assessed]"
- Only extract substantive, meaningful relationships
- {hint}

Output ONLY valid JSON in this exact format, nothing else:
{{"triples": [["subject", "relation", "object"], ...]}}

Text:
{text[:3000]}"""

    try:
        with httpx.Client(timeout=30) as client:
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
            content = resp.json()["choices"][0]["message"]["content"]

            # Parse JSON from response (handle markdown code blocks)
            content = content.strip()
            if content.startswith("```"):
                content = re.sub(r"^```\w*\n?", "", content)
                content = re.sub(r"\n?```$", "", content)

            # Repair common LLM JSON issues
            content = content.strip()
            # Fix trailing commas before ] or }
            content = re.sub(r",\s*([}\]])", r"\1", content)
            # Extract just the JSON object (LLM sometimes appends commentary)
            obj_match = re.search(r'\{.*\}', content, re.DOTALL)
            if obj_match:
                content = obj_match.group()
            # Try parsing with decoder that stops at end of first valid object
            decoder = json.JSONDecoder()
            try:
                data, _ = decoder.raw_decode(content)
            except json.JSONDecodeError:
                # Try to find just the triples array
                match = re.search(r'"triples"\s*:\s*(\[\s*\[.*?\]\s*\])', content, re.DOTALL)
                if match:
                    arr, _ = decoder.raw_decode(match.group(1))
                    data = {"triples": arr}
                else:
                    raise
            triples = data.get("triples", [])
            return [{"subject": t[0], "relation": t[1], "object": t[2]} for t in triples if len(t) >= 3]

    except (httpx.HTTPError, json.JSONDecodeError, KeyError, IndexError) as e:
        print(f"  Warning: Triple extraction failed: {e}", file=sys.stderr)
        return []


def embed_text(text: str, secrets: dict, input_type: str = "passage") -> list[float] | None:
    """Get embedding from TELUS AI."""
    result = embed_batch([text], secrets, input_type)
    return result[0] if result else None


def embed_batch(texts: list[str], secrets: dict, input_type: str = "passage") -> list[list[float] | None]:
    """Batch embed texts via TELUS AI. Returns list of embeddings (None for failures)."""
    url = secrets.get("TELUS_EMBED_URL", "")
    key = secrets.get("TELUS_EMBED_KEY", "")

    if not url or not key:
        return [None] * len(texts)

    results = [None] * len(texts)
    # API typically supports batches of ~96 inputs
    batch_size = 64

    for start in range(0, len(texts), batch_size):
        batch = texts[start:start + batch_size]
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.post(
                    url,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={
                        "input": batch,
                        "model": "nvidia/nv-embedqa-e5-v5",
                        "input_type": input_type,
                    },
                )
                resp.raise_for_status()
                data = resp.json()["data"]
                for item in data:
                    idx = item["index"]
                    results[start + idx] = item["embedding"]
        except (httpx.HTTPError, KeyError, IndexError) as e:
            print(f"  Warning: Batch failed (offset {start}), retrying individually: {e}", file=sys.stderr)
            # Retry each item individually
            for i, text in enumerate(batch):
                if not text or not text.strip():
                    continue
                try:
                    with httpx.Client(timeout=15) as client2:
                        resp2 = client2.post(
                            url,
                            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                            json={
                                "input": [text],
                                "model": "nvidia/nv-embedqa-e5-v5",
                                "input_type": input_type,
                            },
                        )
                        resp2.raise_for_status()
                        results[start + i] = resp2.json()["data"][0]["embedding"]
                except Exception:
                    pass  # Skip individual failures silently

    return results


def store_entity_embeddings(r: redis.Redis, db: str, entities: list[str],
                           embeddings: list[list[float] | None]):
    """Store embeddings on entity nodes in FalkorDB."""
    for entity, emb in zip(entities, embeddings):
        if emb is None:
            continue
        esc = entity.replace('"', '\\"')
        # Store as JSON string property (FalkorDB doesn't support native vector type)
        emb_json = json.dumps(emb)
        cypher = f'MATCH (n:Entity {{name: "{esc}"}}) SET n.embedding = \'{emb_json}\''
        try:
            graph_query(r, db, cypher)
        except redis.exceptions.ResponseError as e:
            print(f"  Warning: Failed to store embedding for '{entity}': {e}", file=sys.stderr)


# --- Content type detection ---

def detect_content_type(filepath: str) -> str:
    """Detect content type from file path."""
    path = str(filepath)
    if "/journal/" in path:
        return "journal"
    elif "/ventures/" in path:
        return "venture"
    elif "/backlog/" in path:
        return "task"
    elif "/inventory/" in path:
        return "inventory"
    elif "/ground/keys/" in path:
        return "ground"
    return "external"


def make_source_id(filepath: str, content_type: str) -> str:
    """Create a namespace:id source identifier."""
    p = Path(filepath)
    if content_type == "journal":
        # journal:2026/03/09/17-11-slug
        parts = p.parts
        try:
            idx = parts.index("journal")
            return "journal:" + "/".join(parts[idx + 2:]).replace(".md", "")
        except ValueError:
            return f"journal:{p.stem}"
    elif content_type == "venture":
        return f"venture:{p.stem}"
    elif content_type == "task":
        return f"task:{p.stem}"
    elif content_type == "inventory":
        return f"inventory:{p.stem}"
    elif content_type == "ground":
        return f"ground:{p.stem}"
    return f"external:{p.name}"


# --- Episode tracking ---

def file_hash(filepath: str) -> str:
    return hashlib.sha256(Path(filepath).read_bytes()).hexdigest()[:16]


def is_indexed(filepath: str, content_type: str) -> bool:
    """Check if file has been indexed and hasn't changed."""
    marker = EPISODES_DIR / content_type / (Path(filepath).name + ".indexed")
    if not marker.exists():
        return False
    try:
        data = json.loads(marker.read_text())
        return data.get("hash") == file_hash(filepath)
    except (json.JSONDecodeError, OSError):
        return False


def mark_indexed(filepath: str, content_type: str, triples_count: int, entity_count: int):
    """Mark a file as indexed."""
    marker_dir = EPISODES_DIR / content_type
    marker_dir.mkdir(parents=True, exist_ok=True)
    marker = marker_dir / (Path(filepath).name + ".indexed")
    marker.write_text(json.dumps({
        "hash": file_hash(filepath),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "triples_count": triples_count,
        "entity_count": entity_count,
    }))


# --- Main indexing ---

def index_file(filepath: str, content_type: str | None, config: dict, secrets: dict,
               r: redis.Redis, force: bool = False) -> tuple[int, int]:
    """Index a single file. Returns (triples_count, entity_count)."""
    path = Path(filepath)
    if not path.exists():
        print(f"  Skip: {filepath} (not found)")
        return (0, 0)
    if not path.suffix == ".md":
        return (0, 0)

    ct = content_type or detect_content_type(filepath)

    if not force and is_indexed(filepath, ct):
        return (0, 0)

    text = path.read_text()
    if not text.strip():
        return (0, 0)

    # Strip YAML frontmatter for extraction (keep content)
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            body = parts[2].strip()

    if len(body) < 20:
        return (0, 0)

    source_id = make_source_id(filepath, ct)
    timestamp = datetime.now(timezone.utc).isoformat()

    print(f"  Indexing: {source_id}")

    # Extract triples
    triples = extract_triples(body, ct, secrets)
    if not triples:
        print(f"    No triples extracted")
        return (0, 0)

    # Collect unique entities
    entities = set()
    for t in triples:
        entities.add(t["subject"].lower().strip())
        entities.add(t["object"].lower().strip())

    # Insert triples
    db = config["backend"]["database"]
    for t in triples:
        insert_triple(
            r, db,
            subject=t["subject"].lower().strip(),
            relation=t["relation"].lower().strip(),
            obj=t["object"].lower().strip(),
            source=source_id,
            timestamp=timestamp,
        )

    triples_count = len(triples)
    entity_count = len(entities)
    print(f"    {triples_count} triples, {entity_count} entities")

    # Embed entities that don't already have embeddings
    entity_list = sorted(entities)
    # Check which entities need embeddings
    needs_embedding = []
    for ent in entity_list:
        esc = ent.replace('"', '\\"')
        try:
            result = graph_query(r, db, f'MATCH (n:Entity {{name: "{esc}"}}) WHERE n.embedding IS NOT NULL RETURN n.name')
            if not result or not result[1]:
                needs_embedding.append(ent)
        except redis.exceptions.ResponseError:
            needs_embedding.append(ent)

    if needs_embedding:
        embs = embed_batch(needs_embedding, secrets, input_type="passage")
        store_entity_embeddings(r, db, needs_embedding, embs)
        embedded_count = sum(1 for e in embs if e is not None)
        print(f"    {embedded_count}/{len(needs_embedding)} entities embedded")

    # Mark indexed
    mark_indexed(filepath, ct, triples_count, entity_count)

    # Log
    log_entry = {
        "timestamp": timestamp,
        "source": source_id,
        "file": str(filepath),
        "content_type": ct,
        "triples_count": triples_count,
        "entity_count": entity_count,
    }
    with open(EXTRACTION_LOG, "a") as f:
        f.write(json.dumps(log_entry) + "\n")

    return (triples_count, entity_count)


def index_directory(dirpath: str, pattern: str, content_type: str,
                    config: dict, secrets: dict, r: redis.Redis,
                    force: bool = False) -> tuple[int, int, int]:
    """Index all matching files in a directory. Returns (files, triples, entities)."""
    root = Path(dirpath).expanduser()
    if not root.exists():
        print(f"  Skip: {dirpath} (not found)")
        return (0, 0, 0)

    files = sorted(root.glob(pattern))
    total_triples = 0
    total_entities = 0
    total_files = 0

    for f in files:
        t, e = index_file(str(f), content_type, config, secrets, r, force)
        if t > 0:
            total_triples += t
            total_entities += e
            total_files += 1
            # Brief pause between files to be polite to the API
            time.sleep(0.5)

    return (total_files, total_triples, total_entities)


def index_all(config: dict, secrets: dict, r: redis.Redis, force: bool = False):
    """Index all configured sources."""
    sources = config.get("sources", {})
    patterns = config.get("index_patterns", {})

    grand_files = 0
    grand_triples = 0
    grand_entities = 0

    for source_name, source_path in sources.items():
        pattern = patterns.get(source_name, "**/*.md")
        ct = source_name
        if ct == "knowledge":
            ct = "external"

        print(f"\n[{source_name}] {source_path} ({pattern})")
        files, triples, entities = index_directory(
            source_path, pattern, ct, config, secrets, r, force
        )
        grand_files += files
        grand_triples += triples
        grand_entities += entities
        print(f"  → {files} files, {triples} triples, {entities} entities")

    print(f"\n=== Total: {grand_files} files, {grand_triples} triples, {grand_entities} entities ===")


def index_pending(config: dict, secrets: dict, r: redis.Redis):
    """Process the pending index queue."""
    if not PENDING_FILE.exists():
        print("No pending files.")
        return

    lines = [l.strip() for l in PENDING_FILE.read_text().splitlines() if l.strip()]
    if not lines:
        print("No pending files.")
        return

    print(f"Processing {len(lines)} pending files...")
    total_triples = 0
    total_entities = 0

    for line in lines:
        if ":" in line:
            ct, filepath = line.split(":", 1)
        else:
            filepath = line
            ct = None
        t, e = index_file(filepath, ct, config, secrets, r)
        total_triples += t
        total_entities += e
        time.sleep(0.5)

    # Clear the queue
    PENDING_FILE.write_text("")
    print(f"Done: {total_triples} triples, {total_entities} entities from {len(lines)} files")


def embed_missing_entities(config: dict, secrets: dict, r: redis.Redis):
    """Embed all entities that don't have embeddings yet."""
    db = config["backend"]["database"]

    # Find entities without embeddings
    cypher = 'MATCH (n:Entity) WHERE n.embedding IS NULL RETURN n.name'
    rows = parse_graph_result(graph_query(r, db, cypher))
    names = [row["n.name"] for row in rows]

    if not names:
        print("All entities already have embeddings.")
        return

    print(f"Embedding {len(names)} entities...")
    embs = embed_batch(names, secrets, input_type="passage")
    store_entity_embeddings(r, db, names, embs)
    embedded = sum(1 for e in embs if e is not None)
    print(f"Done: {embedded}/{len(names)} entities embedded.")


def main():
    parser = argparse.ArgumentParser(description="Hippo indexing pipeline")
    parser.add_argument("path", nargs="?", help="File or directory to index")
    parser.add_argument("--type", choices=["journal", "venture", "task", "ground", "inventory", "external"],
                        help="Content type override")
    parser.add_argument("--all", action="store_true", help="Index all configured sources")
    parser.add_argument("--pending", action="store_true", help="Process pending index queue")
    parser.add_argument("--force", action="store_true", help="Reindex even if unchanged")
    parser.add_argument("--embed-missing", action="store_true",
                        help="Embed all entities that don't have embeddings yet")
    args = parser.parse_args()

    if not CONFIG_FILE.exists():
        print("Error: Hippo not initialized. Run plugin setup first.", file=sys.stderr)
        sys.exit(1)

    config = load_config()
    secrets = load_secrets()
    r = get_redis(config)

    # Verify FalkorDB connectivity
    try:
        r.ping()
    except redis.ConnectionError:
        print("Error: FalkorDB unreachable on port 6380.", file=sys.stderr)
        print("Run: systemctl --user start hippo-graph", file=sys.stderr)
        sys.exit(1)

    if args.embed_missing:
        embed_missing_entities(config, secrets, r)
    elif args.all:
        index_all(config, secrets, r, args.force)
    elif args.pending:
        index_pending(config, secrets, r)
    elif args.path:
        path = Path(args.path).expanduser()
        if path.is_dir():
            pattern = "**/*.md"
            ct = args.type or detect_content_type(str(path))
            files, triples, entities = index_directory(str(path), pattern, ct, config, secrets, r, args.force)
            print(f"\nTotal: {files} files, {triples} triples, {entities} entities")
        else:
            t, e = index_file(str(path), args.type, config, secrets, r, args.force)
            print(f"Indexed: {t} triples, {e} entities")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
