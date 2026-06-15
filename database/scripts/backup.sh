#!/bin/bash
# database/scripts/backup.sh
# Creates a timestamped PostgreSQL dump and optionally uploads to S3
# Usage: bash database/scripts/backup.sh [--upload]

set -euo pipefail

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_DIR="./backups"
BACKUP_FILE="$BACKUP_DIR/metapilot_$TIMESTAMP.dump"

mkdir -p "$BACKUP_DIR"

echo "→ Backing up database..."
pg_dump "$DATABASE_URL" \
  --format=custom \
  --no-password \
  --verbose \
  --file="$BACKUP_FILE"

echo "✅ Backup saved: $BACKUP_FILE"

# Upload to S3 if --upload flag provided and AWS configured
if [[ "${1:-}" == "--upload" ]]; then
  if [[ -z "${AWS_S3_BACKUP_BUCKET:-}" ]]; then
    echo "⚠️  AWS_S3_BACKUP_BUCKET not set. Skipping upload."
  else
    aws s3 cp "$BACKUP_FILE" "s3://$AWS_S3_BACKUP_BUCKET/backups/$(basename $BACKUP_FILE)"
    echo "✅ Uploaded to s3://$AWS_S3_BACKUP_BUCKET/backups/"
  fi
fi
