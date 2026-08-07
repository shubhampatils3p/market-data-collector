#!/bin/bash

set -euo pipefail

# ==========================================================
# PostgreSQL Backup Cleanup Script
# ==========================================================

BACKUP_DIR="/home/ubuntu/market-data-backups"

# Number of days to retain backups
RETENTION_DAYS=30

echo ""
echo "=================================================="
echo "      PostgreSQL Backup Cleanup Started"
echo "=================================================="
echo "Time : $(date)"
echo ""

# ==========================================================
# Check Backup Directory
# ==========================================================

if [ ! -d "$BACKUP_DIR" ]; then
    echo "❌ ERROR: Backup directory not found!"
    exit 1
fi

# ==========================================================
# Disk Usage Before Cleanup
# ==========================================================

BEFORE=$(du -sb "$BACKUP_DIR" | cut -f1)

# ==========================================================
# Count Files Before Cleanup
# ==========================================================

FILES_BEFORE=$(find "$BACKUP_DIR" -type f | wc -l)

# ==========================================================
# Delete Old SQL Backups
# ==========================================================

find "$BACKUP_DIR" \
    -type f \
    -name "*.sql.gz" \
    -mtime +$RETENTION_DAYS \
    -delete

# ==========================================================
# Delete Old Checksum Files
# ==========================================================

find "$BACKUP_DIR" \
    -type f \
    -name "*.sha256" \
    -mtime +$RETENTION_DAYS \
    -delete

# ==========================================================
# Count Files After Cleanup
# ==========================================================

FILES_AFTER=$(find "$BACKUP_DIR" -type f | wc -l)

# ==========================================================
# Disk Usage After Cleanup
# ==========================================================

AFTER=$(du -sb "$BACKUP_DIR" | cut -f1)

FREED_BYTES=$((BEFORE - AFTER))

FREED_HUMAN=$(numfmt --to=iec "$FREED_BYTES")

DELETED=$((FILES_BEFORE - FILES_AFTER))

echo ""
echo "=================================================="
echo "✅ Cleanup Completed Successfully"
echo "=================================================="
echo "Retention : $RETENTION_DAYS days"
echo "Deleted Files : $DELETED"
echo "Space Freed : $FREED_HUMAN"
echo "Remaining Files : $FILES_AFTER"
echo "Location : $BACKUP_DIR"
echo "=================================================="

exit 0