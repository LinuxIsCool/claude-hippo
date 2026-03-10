---
name: hippo-backends
description: >
  FalkorDB setup, management, health checks, and troubleshooting.
  Trigger: FalkorDB, graph database, docker, setup, health, service, infrastructure.
allowed-tools: Read, Write, Bash, Skill
---

# Backends — FalkorDB Infrastructure

## FalkorDB Setup

FalkorDB runs as a Docker container managed by a systemd user service. It provides
the graph storage layer for all of Hippo's operations — indexing writes to it,
retrieval reads from it, consolidation maintains it.

### Docker Compose

Location: `~/.config/hippo/compose.yaml`

```yaml
services:
  hippo-graph:
    image: falkordb/falkordb:latest
    container_name: hippo-graph
    ports:
      - "6380:6379"
    volumes:
      - hippo-data:/data
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 2G

volumes:
  hippo-data:
```

Port 6380 avoids conflict with any system Redis on 6379.

### Systemd Service

Location: `~/.config/systemd/user/hippo-graph.service`

```ini
[Unit]
Description=Hippo Knowledge Graph (FalkorDB)
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/docker compose -f %h/.config/hippo/compose.yaml up -d
ExecStop=/usr/bin/docker compose -f %h/.config/hippo/compose.yaml down

[Install]
WantedBy=default.target
```

## Service Management

```bash
systemctl --user start hippo-graph
systemctl --user stop hippo-graph
systemctl --user status hippo-graph
systemctl --user restart hippo-graph
journalctl --user -u hippo-graph        # View logs
systemctl --user enable hippo-graph     # Start on login
```

## Health Checks

### Basic Connectivity
```bash
redis-cli -p 6380 PING
# Expected: PONG
```

### Graph Statistics
```bash
# Node count
redis-cli -p 6380 GRAPH.QUERY hippo "MATCH (n) RETURN COUNT(n)"

# Edge count
redis-cli -p 6380 GRAPH.QUERY hippo "MATCH ()-[r]->() RETURN COUNT(r)"

# Entity types
redis-cli -p 6380 GRAPH.QUERY hippo "MATCH (n:Entity) RETURN n.type, COUNT(n) ORDER BY COUNT(n) DESC"

# Relation types
redis-cli -p 6380 GRAPH.QUERY hippo "MATCH ()-[r:RELATES]->() RETURN r.type, COUNT(r) ORDER BY COUNT(r) DESC"
```

### Resource Usage
```bash
redis-cli -p 6380 INFO memory           # Memory consumption
docker stats hippo-graph --no-stream     # CPU, memory, network I/O
```

### Full Health Report

Run all checks and format as a summary table. Used by `/status` integration:
- Connection: up/down
- Node count, edge count
- Memory usage (MB)
- Container uptime
- Last consolidation timestamp (from consolidation-log.jsonl)

## Backup & Restore

```bash
# Backup
mkdir -p ~/.claude/local/hippo/backups
docker cp hippo-graph:/data/appendonly.aof \
  ~/.claude/local/hippo/backups/appendonly-$(date +%Y%m%d).aof

# Restore (stop service first, copy backup in, restart)
docker cp ~/.claude/local/hippo/backups/appendonly-YYYYMMDD.aof hippo-graph:/data/appendonly.aof
```

Weekly backup via cron or systemd timer. Keep last 4 backups, rotate older ones.

## Graph Initialization

On first run, create the graph and indexes:

```bash
redis-cli -p 6380 GRAPH.QUERY hippo "CREATE INDEX FOR (e:Entity) ON (e.name)"
redis-cli -p 6380 GRAPH.QUERY hippo "CREATE INDEX FOR (e:Entity) ON (e.type)"
```

Vector index for embedding similarity (when FalkorDB supports it natively):
```bash
redis-cli -p 6380 GRAPH.QUERY hippo \
  "CREATE VECTOR INDEX FOR (e:Entity) ON (e.embedding) OPTIONS {dimension: 1024, similarity: 'cosine'}"
```

## Migration Path

If scale exceeds FalkorDB limits, export via Cypher, transform to Neo4j format, load,
and update `~/.claude/local/hippo/config.yml`. Subskills use config-driven connection.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Container won't start | Port 6380 in use | `lsof -i :6380`, kill conflicting process |
| GRAPH.QUERY timeout | Large result set | Add LIMIT clause, check query complexity |
| High memory usage | Graph too large | Run consolidation prune, increase memory limit |
| Connection refused | Service not running | `systemctl --user start hippo-graph` |
| Data loss after restart | Volume not mounted | Verify `hippo-data` volume in `docker volume ls` |
| Slow queries | Missing index | Run graph initialization commands above |
