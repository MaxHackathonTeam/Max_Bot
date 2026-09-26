#!/usr/bin/env sh
set -eu
: "${BACKUP_DIR:=./backups}"
: "${DATABASE_URL:=postgresql://afisha:afisha@localhost:5432/afisha}"
mkdir -p "$BACKUP_DIR"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
dump_url=$(printf '%s' "$DATABASE_URL" | sed 's/+asyncpg//')
pg_dump --format=custom --no-owner "$dump_url" > "$BACKUP_DIR/afisha-$stamp.dump"
find "$BACKUP_DIR" -type f -name 'afisha-*.dump' -mtime +7 -delete
echo "backup: $BACKUP_DIR/afisha-$stamp.dump"
