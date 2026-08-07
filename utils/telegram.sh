#!/bin/bash

set -euo pipefail

# ==========================================================
# Telegram Helper
# ==========================================================
# This helper loads Telegram configuration from the project's
# .env file and provides reusable functions for sending
# text messages and file attachments.
# ==========================================================

PROJECT_DIR="/home/ubuntu/market-data-collector"
ENV_FILE="$PROJECT_DIR/.env"

# ==========================================================
# Load environment variables
# ==========================================================

if [[ -f "$ENV_FILE" ]]; then
    set -a
    source "$ENV_FILE"
    set +a
fi

# ==========================================================
# Telegram Functions
# ==========================================================

send_telegram_message() {
    local message="$1"

    if [[ -z "${TELEGRAM_BOT_TOKEN:-}" || -z "${TELEGRAM_CHAT_ID:-}" ]]; then
        echo "WARNING: Telegram credentials are not configured" >&2
        return 1
    fi

    curl --silent --show-error --fail \
        -X POST \
        "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d chat_id="${TELEGRAM_CHAT_ID}" \
        -d parse_mode="Markdown" \
        --data-urlencode text="$message" \
        >/dev/null
}

send_telegram_document() {
    local file_path="$1"
    local caption="${2:-Market Data Daily Report}"

    if [[ -z "${TELEGRAM_BOT_TOKEN:-}" || -z "${TELEGRAM_CHAT_ID:-}" ]]; then
        echo "WARNING: Telegram credentials are not configured" >&2
        return 1
    fi

    if [[ ! -f "$file_path" ]]; then
        echo "WARNING: Telegram attachment not found: $file_path" >&2
        return 1
    fi

    curl --silent --show-error --fail \
        -X POST \
        "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendDocument" \
        -F chat_id="${TELEGRAM_CHAT_ID}" \
        -F document="@$file_path" \
        -F caption="$caption" \
        >/dev/null
}