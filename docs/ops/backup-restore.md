# Backup & Restore

## PostgreSQL Database

### Manual Backup

```bash
# Backup all data
pg_dump "$DATABASE_URL" > backup_$(date +%Y%m%d_%H%M%S).sql

# Backup with custom format (faster restore + compression)
pg_dump -Fc "$DATABASE_URL" > backup_$(date +%Y%m%d_%H%M%S).dump
```

### Manual Restore

```bash
# Restore from SQL dump
psql "$DATABASE_URL" < backup_20250101_120000.sql

# Restore from custom format
pg_restore -d "$DATABASE_URL" backup_20250101_120000.dump
```

### Docker-based Backup

```bash
# Backup from running container
docker compose exec postgres \
  pg_dump -U deepagents deepagents > backup.sql

# Restore to running container
cat backup.sql | docker compose exec -T postgres \
  psql -U deepagents deepagents
```

## Automated Backups

The `BackupStrategy` in `src/backends/database.py` supports:

- **Schedule:** cron expression (e.g. `0 3 * * *` for daily at 3am)
- **Retention:** number of days to keep backups
- **Tables:** specific tables to include (empty = all)

## Redis (Session Data)

Redis is used as an optional session backend. Data is ephemeral by default.
For persistence:

1. Enable AOF in `redis.conf`: `appendonly yes`
2. Use Redis CLI to save: `redis-cli SAVE`
3. Copy the dump file: `cp /data/dump.rdb /backup/`

## Docker Volumes

```bash
# Backup a named volume
docker run --rm -v agent_postgres_data:/source -v $(pwd):/backup \
  alpine tar czf /backup/postgres_volume_backup.tar.gz -C /source .

# Restore a named volume
docker run --rm -v agent_postgres_data:/target -v $(pwd):/backup \
  alpine tar xzf /backup/postgres_volume_backup.tar.gz -C /target
```