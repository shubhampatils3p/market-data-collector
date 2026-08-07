#!/bin/bash

set -euo pipefail

# ==========================================================
# Market Data Collector Health Check
# ==========================================================
# This script performs a production-grade health validation
# for the Market Data Collector stack on Ubuntu 24.04.
# It verifies the collector service, PostgreSQL container,
# database connectivity, backup integrity, application logs,
# resource usage, journal storage, and systemd timers.
# ==========================================================

# ==========================================================
# Configuration
# ==========================================================
# Project root directory for the application.
PROJECT_DIR="/home/ubuntu/market-data-collector"

# Application and log paths.
LOG_DIR="$PROJECT_DIR/logs"
REPORT_DIR="$PROJECT_DIR/monitoring/health_reports"

# Backup storage path.
BACKUP_DIR="/home/ubuntu/market-data-backups"

# Systemd and container identifiers.
COLLECTOR_SERVICE="market-data-collector.service"
POSTGRES_CONTAINER="postgres_market_data"
START_TIMER="market-data-start.timer"
STOP_TIMER="market-data-stop.timer"
BACKUP_TIMER="backup.timer"
LOG_TIMER="log-cleanup.timer"

# Report naming convention.
REPORT_DATE=$(date +"%Y-%m-%d")
REPORT_TIME=$(date +"%Y-%m-%d %H:%M:%S %Z")
REPORT_FILE="$REPORT_DIR/${REPORT_DATE}_health_report.txt"
HEALTH_SUMMARY_FILE="$PROJECT_DIR/monitoring/tmp_health_summary.txt"

# Global status used to determine the final exit code.
OVERALL_STATUS="PASS"

# Load Telegram helper after the project path is defined.
source "$PROJECT_DIR/utils/telegram.sh"

# Summary status values used by the combined Telegram report.
COLLECTOR_STATUS="PASS"
DATABASE_STATUS="PASS"
BACKUP_STATUS="PASS"
LOG_STATUS="PASS"
DISK_STATUS="PASS"
MEMORY_STATUS="PASS"
CPU_STATUS="PASS"
TIMERS_STATUS="PASS"

# ==========================================================
# Helper Functions
# ==========================================================
# These functions standardize how checks are reported and
# how the script transitions from PASS to WARNING or FAIL.
# ==========================================================

set_warning() {
    if [[ "$OVERALL_STATUS" != "FAIL" ]]; then
        OVERALL_STATUS="WARNING"
    fi
}

set_failure() {
    OVERALL_STATUS="FAIL"
}

pass_check() {
    local check_name="$1"
    printf "%-32s : PASS\n" "$check_name"
}

warn_check() {
    local check_name="$1"
    local reason="$2"
    printf "%-32s : WARNING (%s)\n" "$check_name" "$reason"
    set_warning
}

fail_check() {
    local check_name="$1"
    local reason="$2"
    printf "%-32s : FAIL (%s)\n" "$check_name" "$reason"
    set_failure
}

print_section() {
    echo ""
    echo "--------------------------------------------------"
    echo "$1"
    echo "--------------------------------------------------"
}

check_timer_status() {
    local timer_name="$1"

    if systemctl is-enabled "$timer_name" >/dev/null 2>&1 && \
       systemctl is-active "$timer_name" >/dev/null 2>&1; then
        pass_check "$timer_name"
    else
        fail_check "$timer_name" "Timer is disabled or inactive"
    fi
}

# ==========================================================
# Report Directory and Output Setup
# ==========================================================
# The report directory is created before writing the report.
# Output is simultaneously written to stdout and the report file.
# ==========================================================

mkdir -p "$REPORT_DIR"
exec > >(tee "$REPORT_FILE")

# ==========================================================
# Report Header
# ==========================================================
# The header provides a clear summary of the system state.
# ==========================================================

echo "=================================================="
echo " Market Data Collector Health Report"
echo "=================================================="
echo "Date : $REPORT_DATE"
echo "Time : $REPORT_TIME"

# ==========================================================
# Collector Service Validation
# ==========================================================
# The collector is expected to be active only during market hours.
# Outside market hours it should be stopped, and weekends are handled
# as non-market days by expecting the service to be stopped.
# ==========================================================

print_section "Collector Service"

CURRENT_DAY=$(date +%a)
CURRENT_TIME=$(date +%H:%M)
MARKET_START="09:10"
MARKET_END="15:50"
COLLECTOR_STATE=$(systemctl is-active "$COLLECTOR_SERVICE" 2>/dev/null || true)

CURRENT_MINUTES=$((10#$(date +%H) * 60 + 10#$(date +%M)))
MARKET_START_MINUTES=$((9 * 60 + 10))
MARKET_END_MINUTES=$((15 * 60 + 50))

if [[ "$CURRENT_DAY" == "Sat" || "$CURRENT_DAY" == "Sun" ]]; then
    if [[ "$COLLECTOR_STATE" == "active" ]]; then
        warn_check "Collector Service" "Running outside market hours"
        COLLECTOR_STATUS="WARNING"
    else
        pass_check "Collector Service (Expected Stopped)"
        COLLECTOR_STATUS="PASS"
    fi

elif (( CURRENT_MINUTES >= MARKET_START_MINUTES && CURRENT_MINUTES <= MARKET_END_MINUTES )); then
    if [[ "$COLLECTOR_STATE" == "active" ]]; then
        pass_check "Collector Service"
        COLLECTOR_STATUS="PASS"
    else
        fail_check "Collector Service" "Expected active during market hours"
        COLLECTOR_STATUS="FAIL"
    fi
else
    if [[ "$COLLECTOR_STATE" == "inactive" ]]; then
        pass_check "Collector Service (Expected Stopped)"
        COLLECTOR_STATUS="PASS"
    else
        warn_check "Collector Service" "Running outside market hours"
        COLLECTOR_STATUS="WARNING"
    fi
fi

# ==========================================================
# PostgreSQL Container Validation
# ==========================================================
# This checks whether the PostgreSQL container exists, is running,
# and has a healthy status from Docker health checks.
# ==========================================================

print_section "PostgreSQL"

if docker inspect "$POSTGRES_CONTAINER" >/dev/null 2>&1; then
    CONTAINER_RUNNING=$(docker inspect -f '{{.State.Running}}' "$POSTGRES_CONTAINER" 2>/dev/null || echo "false")
    CONTAINER_HEALTH=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$POSTGRES_CONTAINER" 2>/dev/null || echo "missing")

    if [[ "$CONTAINER_RUNNING" == "true" && "$CONTAINER_HEALTH" == "healthy" ]]; then
        pass_check "Docker Container"
    else
        fail_check "Docker Container" "Container is not running or health is not healthy"
        DATABASE_STATUS="FAIL"
    fi
else
    fail_check "Docker Container" "Container not found"
    DATABASE_STATUS="FAIL"
fi

# ==========================================================
# PostgreSQL Connection Validation
# ==========================================================
# The database is verified through the pg_isready probe.
# ==========================================================

if docker exec "$POSTGRES_CONTAINER" pg_isready >/dev/null 2>&1; then
    pass_check "Database Connection"
else
    fail_check "Database Connection" "pg_isready failed"
    DATABASE_STATUS="FAIL"
fi

if [[ "$DATABASE_STATUS" != "FAIL" ]]; then
    DATABASE_STATUS="PASS"
fi

# ==========================================================
# Backup Validation
# ==========================================================
# The backup folder must exist and a backup matching today's date
# must be present with a checksum file and a valid file size.
# ==========================================================

print_section "Backup"

if [[ -d "$BACKUP_DIR" ]]; then
    pass_check "Backup Folder"
else
    fail_check "Backup Folder" "Missing"
    BACKUP_STATUS="FAIL"
fi

TODAY_BACKUP=$(find "$BACKUP_DIR" -maxdepth 1 -type f -name "market_data_${REPORT_DATE}_*.sql.gz" 2>/dev/null | sort | head -n 1 || true)

if [[ -n "$TODAY_BACKUP" ]]; then
    BACKUP_FILE_NAME=$(basename "$TODAY_BACKUP")
    CHECKSUM_FILE="${TODAY_BACKUP}.sha256"
    BACKUP_SIZE=$(stat -c%s "$TODAY_BACKUP" 2>/dev/null || echo "unknown")
    BACKUP_MODIFIED=$(stat -c '%y' "$TODAY_BACKUP" 2>/dev/null || echo "unknown")

    if [[ -f "$CHECKSUM_FILE" ]]; then
        pass_check "Today's Backup"
    else
        fail_check "Today's Backup" "Checksum file missing"
        BACKUP_STATUS="FAIL"
    fi

    echo "Backup File                 : $BACKUP_FILE_NAME"
    echo "Backup Size                 : ${BACKUP_SIZE} bytes"
    echo "Backup Modified             : $BACKUP_MODIFIED"
else
    fail_check "Today's Backup" "Backup not found"
    BACKUP_STATUS="FAIL"
fi

if [[ "$BACKUP_STATUS" != "FAIL" ]]; then
    BACKUP_STATUS="PASS"
fi

# ==========================================================
# Application Log Validation
# ==========================================================
# The daily log directory and the app.log file are validated.
# The size and modification time of the log are reported.
# ==========================================================

print_section "Application Logs"

TODAY_LOG_DIR="$LOG_DIR/$REPORT_DATE"
TODAY_LOG_FILE="$TODAY_LOG_DIR/app.log"

if [[ -d "$TODAY_LOG_DIR" ]]; then
    pass_check "Today's Log Folder"
else
    fail_check "Today's Log Folder" "Missing"
    LOG_STATUS="FAIL"
fi

if [[ -f "$TODAY_LOG_FILE" ]]; then
    LOG_SIZE=$(du -h "$TODAY_LOG_FILE" | cut -f1)
    LOG_MODIFIED=$(stat -c '%y' "$TODAY_LOG_FILE" 2>/dev/null || echo "unknown")
    pass_check "Today's Log"
    echo "Log Size                    : $LOG_SIZE"
    echo "Last Modified               : $LOG_MODIFIED"
else
    fail_check "Today's Log" "Missing"
    LOG_STATUS="FAIL"
fi

if [[ "$LOG_STATUS" != "FAIL" ]]; then
    LOG_STATUS="PASS"
fi

# ==========================================================
# Disk Usage Validation
# ==========================================================
# Root filesystem usage is checked and mapped to PASS/WARNING/FAIL.
# ==========================================================

print_section "Disk Usage"

DISK_USAGE=$(df / | awk 'NR==2 {gsub("%", "", $5); print $5}')

if [[ "$DISK_USAGE" =~ ^[0-9]+$ ]]; then
    if (( DISK_USAGE < 80 )); then
        pass_check "Disk Usage"
        echo "Disk Used                   : ${DISK_USAGE}%"
        DISK_STATUS="PASS"
    elif (( DISK_USAGE < 90 )); then
        warn_check "Disk Usage" "${DISK_USAGE}% Used"
        echo "Disk Used                   : ${DISK_USAGE}%"
        DISK_STATUS="WARNING"
    else
        fail_check "Disk Usage" "${DISK_USAGE}% Used"
        echo "Disk Used                   : ${DISK_USAGE}%"
        DISK_STATUS="FAIL"
    fi
else
    fail_check "Disk Usage" "Unable to determine usage"
    DISK_STATUS="FAIL"
fi

# ==========================================================
# Memory Usage Validation
# ==========================================================
# Memory usage is calculated from the free command output.
# ==========================================================

print_section "Memory"

MEMORY_TOTAL=$(free | awk '/^Mem:/ {print $2}')
MEMORY_USED=$(free | awk '/^Mem:/ {print $3}')
MEMORY_PERCENT=$(awk -v used="$MEMORY_USED" -v total="$MEMORY_TOTAL" 'BEGIN { if (total > 0) { printf "%.0f", (used / total) * 100 } else { print 0 } }')

if [[ "$MEMORY_PERCENT" =~ ^[0-9]+$ ]]; then
    if (( MEMORY_PERCENT < 80 )); then
        pass_check "Memory Usage"
        echo "Memory Used                 : ${MEMORY_PERCENT}%"
        MEMORY_STATUS="PASS"
    elif (( MEMORY_PERCENT < 90 )); then
        warn_check "Memory Usage" "${MEMORY_PERCENT}% Used"
        echo "Memory Used                 : ${MEMORY_PERCENT}%"
        MEMORY_STATUS="WARNING"
    else
        fail_check "Memory Usage" "${MEMORY_PERCENT}% Used"
        echo "Memory Used                 : ${MEMORY_PERCENT}%"
        MEMORY_STATUS="FAIL"
    fi
else
    fail_check "Memory Usage" "Unable to determine usage"
    MEMORY_STATUS="FAIL"
fi

# ==========================================================
# CPU Load Validation
# ==========================================================
# CPU load is compared against the number of CPU cores.
# A warning is raised when the load is above 1.5x the core count.
# ==========================================================

print_section "CPU"

CPU_CORES=$(nproc 2>/dev/null || echo 1)
CPU_LOAD=$(uptime | awk -F'load average:' '{print $2}' | awk -F',' '{print $1}' | xargs)
LOAD_THRESHOLD=$(awk -v cores="$CPU_CORES" 'BEGIN { printf "%.2f", cores * 1.5 }')

if [[ "$CPU_LOAD" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    if awk -v current_load="$CPU_LOAD" -v threshold="$LOAD_THRESHOLD" 'BEGIN { exit !(current_load > threshold) }'; then
        warn_check "CPU" "Load ${CPU_LOAD} exceeds threshold ${LOAD_THRESHOLD}"
        CPU_STATUS="WARNING"
    else
        pass_check "CPU"
        CPU_STATUS="PASS"
    fi
    echo "CPU Cores                   : $CPU_CORES"
    echo "Current Load                : $CPU_LOAD"
    echo "Load Threshold              : $LOAD_THRESHOLD"
else
    warn_check "CPU" "Unable to determine current load"
    CPU_STATUS="WARNING"
fi

# ==========================================================
# Journal Validation
# ==========================================================
# The journal disk usage is reported directly from journalctl.
# ==========================================================

print_section "Journal"

JOURNAL_OUTPUT=$(journalctl --disk-usage 2>/dev/null || true)

if [[ -n "$JOURNAL_OUTPUT" ]]; then
    pass_check "Journal"
    echo "$JOURNAL_OUTPUT"
else
    fail_check "Journal" "Unable to determine journal usage"
fi

# ==========================================================
# Timer Validation
# ==========================================================
# All required systemd timers must be enabled and active.
# ==========================================================

print_section "Systemd Timers"

check_timer_status "$START_TIMER"
check_timer_status "$STOP_TIMER"
check_timer_status "$BACKUP_TIMER"
check_timer_status "$LOG_TIMER"

TIMERS_STATUS="PASS"

for timer in \
"$START_TIMER" \
"$STOP_TIMER" \
"$BACKUP_TIMER" \
"$LOG_TIMER"
do
    if ! systemctl is-enabled "$timer" >/dev/null 2>&1 || \
       ! systemctl is-active "$timer" >/dev/null 2>&1
    then
        TIMERS_STATUS="FAIL"
        break
    fi
done

# ==========================================================
# Health Summary File
# ==========================================================
# A compact summary is written for downstream reporting.
# ==========================================================

{
    echo "Collector=$COLLECTOR_STATUS"
    echo "Database=$DATABASE_STATUS"
    echo "Backup=$BACKUP_STATUS"
    echo "Logs=$LOG_STATUS"
    echo "Disk=${DISK_USAGE}%"
    echo "Memory=${MEMORY_PERCENT}%"
    echo "CPU=$CPU_STATUS"
    echo "Timers=$TIMERS_STATUS"
    echo "Overall=$OVERALL_STATUS"
} > "$HEALTH_SUMMARY_FILE"

# ==========================================================
# Final Report Summary
# ==========================================================
# The overall status is rendered clearly for both console output
# and the saved report file.
# ==========================================================

echo ""
echo "=================================================="

case "$OVERALL_STATUS" in
    PASS)
        echo "OVERALL STATUS : ✅ SYSTEM HEALTHY"
        ;;
    WARNING)
        echo "OVERALL STATUS : ⚠️ SYSTEM HEALTHY (Warnings Present)"
        ;;
    FAIL)
        echo "OVERALL STATUS : ❌ ATTENTION REQUIRED"
        ;;
    *)
        echo "OVERALL STATUS : ❌ ATTENTION REQUIRED"
        OVERALL_STATUS="FAIL"
        ;;
esac

echo "=================================================="

echo ""
echo "Health report saved to"
echo "$REPORT_FILE"
echo ""

# ==========================================================
# Exit Code
# ==========================================================
# The script exits successfully for PASS and WARNING states,
# and fails for any critical health issue.
# ==========================================================

if [[ "$OVERALL_STATUS" == "FAIL" ]]; then
    exit 1
fi

exit 0