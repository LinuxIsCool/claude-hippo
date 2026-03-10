# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""Hippo session memory — check graph health and report status on session start."""

import yaml
import subprocess
import json
from pathlib import Path

HIPPO_DIR = Path.home() / ".claude" / "local" / "hippo"
CONFIG_FILE = HIPPO_DIR / "config.yml"
EXTRACTION_LOG = HIPPO_DIR / "extraction-log.jsonl"
CONSOLIDATION_LOG = HIPPO_DIR / "consolidation-log.jsonl"
PENDING_FILE = HIPPO_DIR / ".pending-index"


def docker_redis(*args: str) -> str | None:
    """Run a redis-cli command inside the hippo-graph container."""
    try:
        result = subprocess.run(
            ["docker", "exec", "hippo-graph", "redis-cli"] + list(args),
            capture_output=True, text=True, timeout=3
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def get_graph_stats() -> tuple[int, int] | None:
    """Get node and edge counts from FalkorDB."""
    pong = docker_redis("PING")
    if pong != "PONG":
        return None

    nodes_out = docker_redis("GRAPH.QUERY", "hippo", "MATCH (n) RETURN COUNT(n)")
    edges_out = docker_redis("GRAPH.QUERY", "hippo", "MATCH ()-[r]->() RETURN COUNT(r)")

    try:
        nodes = 0
        edges = 0
        if nodes_out:
            for line in nodes_out.split('\n'):
                if line.strip().isdigit():
                    nodes = int(line.strip())
                    break
        if edges_out:
            for line in edges_out.split('\n'):
                if line.strip().isdigit():
                    edges = int(line.strip())
                    break
        return (nodes, edges)
    except (ValueError, IndexError):
        return (0, 0)


def last_log_entry(log_file: Path) -> str | None:
    """Get the last line of a JSONL log file."""
    if not log_file.exists():
        return None
    try:
        lines = log_file.read_text().strip().split('\n')
        if lines and lines[-1]:
            entry = json.loads(lines[-1])
            return entry.get("timestamp", "unknown")
    except (json.JSONDecodeError, OSError):
        pass
    return None


def pending_count() -> int:
    """Count files in the pending index queue."""
    if not PENDING_FILE.exists():
        return 0
    try:
        lines = [l for l in PENDING_FILE.read_text().strip().split('\n') if l.strip()]
        return len(lines)
    except OSError:
        return 0


def main():
    if not HIPPO_DIR.exists():
        return  # Hippo not initialized

    parts = ["[hippo]"]

    stats = get_graph_stats()
    if stats is None:
        parts.append("FalkorDB unreachable (port 6380).")
        parts.append("Run: systemctl --user start hippo-graph")
    else:
        nodes, edges = stats
        parts.append(f"Graph: {nodes:,} nodes, {edges:,} edges.")

    last_indexed = last_log_entry(EXTRACTION_LOG)
    if last_indexed:
        parts.append(f"Last indexed: {last_indexed}.")

    last_consolidated = last_log_entry(CONSOLIDATION_LOG)
    if last_consolidated:
        parts.append(f"Last consolidated: {last_consolidated}.")

    pending = pending_count()
    if pending > 0:
        parts.append(f"Pending: {pending} files.")

    print(" ".join(parts))


if __name__ == "__main__":
    main()
