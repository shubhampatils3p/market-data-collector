#!/bin/bash

set -euo pipefail

# ==========================================================
# Application Log Cleanup Script
# ==========================================================

LOG_DIR="/home/ubuntu/market-data-collector/logs"

# Number of days to retain logs
RETENTION_DAYS=30

echo ""
echo "=================================================="
echo "        Application Log Cleanup Started"
echo "=================================================="
echo "Time : $(date)"
echo ""

# ==========================================================
# Check Log Directory
# ==========================================================

if [ ! -d "$LOG_DIR" ]; then
    echo "❌ ERROR: Log directory not found!"
    exit 1
fi

# ==========================================================
# Disk Usage Before Cleanup
# ==========================================================

BEFORE=$(du -sb "$LOG_DIR" | cut -f1)

# ==========================================================
# Count Directories Before Cleanup
# ==========================================================

DIRS_BEFORE=$(find "$LOG_DIR" -mindepth 1 -maxdepth 1 -type d | wc -l)

# ==========================================================
# Delete Old Log Folders
# ==========================================================

find "$LOG_DIR" \
    -mindepth 1 \
    -maxdepth 1 \
    -type d \
    -mtime +$RETENTION_DAYS \
    -print \
    -exec rm -rf {} +

# ==========================================================
# Count Directories After Cleanup
# ==========================================================

DIRS_AFTER=$(find "$LOG_DIR" -mindepth 1 -maxdepth 1 -type d | wc -l)

# ==========================================================
# Disk Usage After Cleanup
# ==========================================================

AFTER=$(du -sb "$LOG_DIR" | cut -f1)

FREED_BYTES=$((BEFORE - AFTER))

FREED_HUMAN=$(numfmt --to=iec "$FREED_BYTES")

DELETED=$((DIRS_BEFORE - DIRS_AFTER))

echo ""
echo "=================================================="
echo "✅ Log Cleanup Completed Successfully"
echo "=================================================="
echo "Retention        : $RETENTION_DAYS days"
echo "Deleted Folders  : $DELETED"
echo "Space Freed      : $FREED_HUMAN"
echo "Remaining Folders: $DIRS_AFTER"
echo "Location         : $LOG_DIR"
echo "=================================================="

exit 0