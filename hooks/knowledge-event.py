# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Hippo knowledge event detector — queues files for indexing when plugins write data."""

import sys
import json
import re
from pathlib import Path

HIPPO_DIR = Path.home() / ".claude" / "local" / "hippo"
PENDING_FILE = HIPPO_DIR / ".pending-index"

# Source patterns to watch
SOURCE_PATTERNS = [
    (re.compile(r"\.claude/local/journal/.*\.md$"), "journal"),
    (re.compile(r"\.claude/local/ventures/.*\.md$"), "venture"),
    (re.compile(r"\.claude/local/backlog/task-.*\.md$"), "backlog"),
    (re.compile(r"\.claude/local/inventory/.*\.md$"), "inventory"),
    (re.compile(r"\.claude/local/ground/keys/.*\.md$"), "ground"),
]


def main():
    # PostToolUse hooks receive tool info via stdin
    try:
        input_data = sys.stdin.read()
        if not input_data.strip():
            return
        hook_data = json.loads(input_data)
    except (json.JSONDecodeError, OSError):
        return

    # Extract file path from tool input
    tool_input = hook_data.get("tool_input", {})
    file_path = tool_input.get("file_path", "") or tool_input.get("path", "")

    if not file_path:
        return

    # Check if path matches any source pattern
    for pattern, source_type in SOURCE_PATTERNS:
        if pattern.search(file_path):
            # Queue for indexing
            HIPPO_DIR.mkdir(parents=True, exist_ok=True)
            with open(PENDING_FILE, "a") as f:
                f.write(f"{source_type}:{file_path}\n")
            return  # Found a match, done


if __name__ == "__main__":
    main()
