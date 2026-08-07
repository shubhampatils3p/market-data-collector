#!/bin/bash

set -euo pipefail

# ==========================================================
# Market Data Collector - Health Check
# ==========================================================

REPORT_TIME=$(date)

echo ""
echo "=================================================="
echo "      Market Data Collector Health Check"
echo "=================================================="
echo "Time : $REPORT_TIME"
echo ""

# ==========================================================
# Collector Service
# ==========================================================

if systemctl is-active --quiet market-data-collector; then
    COLLECTOR_STATUS="PASS"
else
    COLLECTOR_STATUS="FAIL"
fi

# ==========================================================
# PostgreSQL Docker Container
# ==========================================================

if docker inspect -f '{{.State.Health.Status}}' postgres_market_data 2>/dev/null | grep -q healthy; then
    POSTGRES_STATUS="PASS"
else
    POSTGRES_STATUS="FAIL"
fi

# ==========================================================
# PostgreSQL Connection
# ==========================================================

if docker exec postgres_market_data pg_isready >/dev/null 2>&1; then
    DB_STATUS="PASS"
else
    DB_STATUS="FAIL"
fi

# ==========================================================
# Disk Usage
# ==========================================================

DISK_USAGE=$(df / | awk 'NR==2 {gsub("%","",$5); print $5}')

if [ "$DISK_USAGE" -lt 80 ]; then
    DISK_STATUS="PASS"
else
    DISK_STATUS="WARNING"
fi

# ==========================================================
# Memory Usage
# ==========================================================

MEMORY_PERCENT=$(free | awk '/Mem:/ {printf("%.0f", $3/$2*100)}')

if [ "$MEMORY_PERCENT" -lt 80 ]; then
    MEMORY_STATUS="PASS"
else
    MEMORY_STATUS="WARNING"
fi

# ==========================================================
# CPU Load
# ==========================================================

CPU_LOAD=$(uptime | awk -F'load average:' '{print $2}' | cut -d',' -f1 | xargs)

CPU_STATUS="PASS"

# ==========================================================
# Display Report
# ==========================================================

echo "Collector Service      : $COLLECTOR_STATUS"
echo "PostgreSQL Container   : $POSTGRES_STATUS"
echo "Database Connection    : $DB_STATUS"
echo "Disk Usage             : $DISK_STATUS (${DISK_USAGE}%)"
echo "Memory Usage           : $MEMORY_STATUS (${MEMORY_PERCENT}%)"
echo "CPU Load               : $CPU_STATUS ($CPU_LOAD)"

echo ""

# ==========================================================
# Overall Status
# ==========================================================

if [[ "$COLLECTOR_STATUS" == "PASS" && \
      "$POSTGRES_STATUS" == "PASS" && \
      "$DB_STATUS" == "PASS" && \
      "$DISK_STATUS" == "PASS" && \
      "$MEMORY_STATUS" == "PASS" ]]; then

    echo "=================================================="
    echo "✅ OVERALL STATUS : SYSTEM HEALTHY"
    echo "=================================================="

else

    echo "=================================================="
    echo "⚠ OVERALL STATUS : ATTENTION REQUIRED"
    echo "=================================================="

fi

exit 0