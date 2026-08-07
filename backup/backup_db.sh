#!/bin/bash

set -euo pipefail

# ==========================================================
# PostgreSQL Daily Backup Script
# ==========================================================

PROJECT_DIR="/home/ubuntu/market-data-collector"
BACKUP_DIR="/home/ubuntu/market-data-backups"
ENV_FILE="$PROJECT_DIR/.env"

# ==========================================================
# Load Environment Variables
# ==========================================================

if [ ! -f "$ENV_FILE" ]; then
    echo "❌ ERROR: .env file not found!"
    exit 1
fi

set -a
source "$ENV_FILE"
set +a

# ==========================================================
# Validate Required Variables
# ==========================================================

REQUIRED_VARS=(
    DB_HOST
    DB_PORT
    DB_NAME
    DB_USER
    DB_PASSWORD
)

for VAR in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!VAR:-}" ]; then
        echo "❌ ERROR: $VAR is not set."
        exit 1
    fi
done

# ==========================================================
# Check pg_dump availability
# ==========================================================

if ! command -v pg_dump >/dev/null 2>&1; then
    echo "❌ ERROR: pg_dump is not installed."
    exit 1
fi

# ==========================================================
# Create Backup Directory
# ==========================================================

mkdir -p "$BACKUP_DIR"

# ==========================================================
# Backup File Name
# ==========================================================

TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")

BACKUP_FILE="$BACKUP_DIR/${DB_NAME}_${TIMESTAMP}.sql"
COMPRESSED_FILE="${BACKUP_FILE}.gz"

# ==========================================================
# Start Timer
# ==========================================================

START_TIME=$(date +%s)

echo ""
echo "=================================================="
echo "        PostgreSQL Backup Started"
echo "=================================================="
echo "Database : $DB_NAME"
echo "Time     : $(date)"
echo ""

# ==========================================================
# Export Password
# ==========================================================

export PGPASSWORD="$DB_PASSWORD"

# Always remove password from environment
trap 'unset PGPASSWORD' EXIT

# ==========================================================
# Run pg_dump
# ==========================================================

pg_dump \
    -h "$DB_HOST" \
    -p "$DB_PORT" \
    -U "$DB_USER" \
    -d "$DB_NAME" \
    -F p \
    -f "$BACKUP_FILE"

# ==========================================================
# Compress Backup
# ==========================================================

gzip "$BACKUP_FILE"

# ==========================================================
# Verify Backup
# ==========================================================

if [ ! -s "$COMPRESSED_FILE" ]; then
    echo "❌ ERROR: Backup file is missing or empty!"
    exit 1
fi

# Verify gzip archive integrity
if ! gzip -t "$COMPRESSED_FILE"; then
    echo "❌ ERROR: Backup integrity check failed!"
    exit 1
fi

# ==========================================================
# Generate SHA256 Checksum
# ==========================================================

sha256sum "$COMPRESSED_FILE" > "${COMPRESSED_FILE}.sha256"

# ==========================================================
# Calculate Duration
# ==========================================================

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

FILE_SIZE=$(du -h "$COMPRESSED_FILE" | cut -f1)

echo ""
echo "=================================================="
echo "✅ Backup Completed Successfully"
echo "=================================================="
echo "Database : $DB_NAME"
echo "File     : $(basename "$COMPRESSED_FILE")"
echo "Size     : $FILE_SIZE"
echo "Duration : ${DURATION} sec"
echo "Checksum : $(basename "${COMPRESSED_FILE}.sha256")"
echo "Location : $BACKUP_DIR"
echo "=================================================="

exit 0