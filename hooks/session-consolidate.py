# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""Hippo session end — process pending index queue and report status."""

import json
import subprocess
from pathlib import Path
from datetime import datetime

HIPPO_DIR = Path.home() / ".claude" / "local" / "hippo"
PENDING_FILE = HIPPO_DIR / ".pending-index"
CONSOLIDATION_LOG = HIPPO_DIR / "consolidation-log.jsonl"
SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"


def main():
    if not HIPPO_DIR.exists():
        return

    parts = ["[hippo]"]

    # Count pending files
    pending = 0
    if PENDING_FILE.exists():
        try:
            lines = [l for l in PENDING_FILE.read_text().strip().split('\n') if l.strip()]
            pending = len(lines)
        except OSError:
            pass

    if pending > 0:
        parts.append(f"{pending} files queued for indexing.")

    # Log session end
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "operation": "session_end",
        "pending_files": pending,
    }

    HIPPO_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONSOLIDATION_LOG, "a") as f:
        f.write(json.dumps(log_entry) + "\n")

    if pending > 0:
        print(" ".join(parts))


if __name__ == "__main__":
    main()
