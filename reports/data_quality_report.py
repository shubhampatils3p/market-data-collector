#!/usr/bin/env python3
"""
==========================================================
Market Data Quality Report
==========================================================

Generates a production quality report for today's option
market data stored in PostgreSQL.

Checks include

• Expected Candles
• Expected Rows
• Missing Candles
• Missing Rows
• Duplicate Rows
• Missing Strikes
• Timestamp Gaps
• NULL Values
• Zero OI
• Zero Volume
• Market Hours Validation
• Price Source Validation

Author : ChatGPT
==========================================================
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from collections import Counter, defaultdict

import psycopg2
import pytz
from psycopg2.extras import DictCursor
from dotenv import load_dotenv

# ==========================================================
# Load Environment
# ==========================================================

PROJECT_DIR = "/home/ubuntu/market-data-collector"

load_dotenv(os.path.join(PROJECT_DIR, ".env"))

IST = pytz.timezone("Asia/Kolkata")

DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

# ==========================================================
# Configuration
# ==========================================================

INDICES = [
    "NIFTY",
    "BANKNIFTY",
    "FINNIFTY",
    "SENSEX",
]

MARKET_START = "09:15"
MARKET_END = "15:29"

EXPECTED_CANDLES = 375
EXPECTED_STRIKES = 11

EXPECTED_ROWS_PER_INDEX = (
    EXPECTED_CANDLES *
    EXPECTED_STRIKES
)


# ==========================================================
# Database
# ==========================================================

def get_connection():

    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        cursor_factory=DictCursor
    )


# ==========================================================
# Helpers
# ==========================================================

def status(pass_condition, warning=False):

    if pass_condition:
        return "PASS"

    if warning:
        return "WARNING"

    return "FAIL"


def safe_int(value):

    if value is None:
        return 0

    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def safe_float(value):

    if value is None:
        return 0.0

    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def print_separator():

    print("=" * 60)


# ==========================================================
# Load Today's Data
# ==========================================================

def load_today_data(conn):

    trading_day = datetime.now(IST).strftime("%Y-%m-%d")

    sql = """
    SELECT *
    FROM option_market_data
    WHERE DATE("Timestamp") = %s
    ORDER BY
        "Index_Name",
        "Timestamp",
        "Target_Strike"
    """

    cur = conn.cursor()

    cur.execute(sql, (trading_day,))

    rows = cur.fetchall()

    cur.close()

    return rows


# ==========================================================
# Group Data
# ==========================================================

def group_by_index(rows):

    grouped = defaultdict(list)

    for row in rows:

        index_name = row.get("Index_Name") or "UNKNOWN"
        grouped[index_name].append(row)

    return grouped

# ==========================================================
# Validation Functions
# ==========================================================

def get_expected_minutes():
    """
    Returns every expected market minute
    09:15 → 15:29
    """

    today_ist = datetime.now(IST).date()
    current = datetime.combine(today_ist, datetime.strptime("09:15", "%H:%M").time())
    end = datetime.combine(today_ist, datetime.strptime("15:29", "%H:%M").time())

    minutes = []

    while current <= end:
        minutes.append(current.strftime("%H:%M"))
        current += timedelta(minutes=1)

    return set(minutes)


EXPECTED_MINUTES = get_expected_minutes()


# ==========================================================
# Timestamp Validation
# ==========================================================

def validate_timestamps(rows):

    minute_map = defaultdict(list)
    invalid_timestamps = 0

    for row in rows:

        timestamp_value = row.get("Timestamp")

        if isinstance(timestamp_value, datetime):
            minute = timestamp_value.strftime("%H:%M")
            minute_map[minute].append(row)
        else:
            invalid_timestamps += 1

    received_minutes = set(minute_map.keys())

    missing_minutes = sorted(
        EXPECTED_MINUTES - received_minutes
    )

    extra_minutes = sorted(
        received_minutes - EXPECTED_MINUTES
    )

    return {

        "expected": EXPECTED_CANDLES,

        "actual": len(received_minutes),

        "missing": len(missing_minutes) + invalid_timestamps,

        "missing_list": missing_minutes,

        "extra": extra_minutes

    }


# ==========================================================
# Strike Validation
# ==========================================================

def validate_strikes(rows):

    grouped = defaultdict(list)

    for row in rows:

        timestamp_value = row.get("Timestamp")

        if isinstance(timestamp_value, datetime):
            minute = timestamp_value.strftime("%H:%M")
        else:
            continue

        grouped[minute].append(row)

    missing = 0
    invalid_minutes = []

    for minute, values in grouped.items():

        strikes = {
            x.get("Target_Strike")
            for x in values
            if x.get("Target_Strike") is not None
        }

        received = len(strikes)

        if received != EXPECTED_STRIKES:

            missing_count = max(0, EXPECTED_STRIKES - received)

            missing += missing_count

            invalid_minutes.append({
                "minute": minute,
                "expected": EXPECTED_STRIKES,
                "received": received
            })

    return {
        "missing": missing,
        "invalid_minutes": invalid_minutes
    }

# ==========================================================
# Duplicate Validation
# ==========================================================

def validate_duplicates(rows):

    hashes = []
    missing_hashes = 0
    timestamp_strike_keys = []

    for row in rows:

        row_hash = row.get("Row_Hash")
        timestamp_value = row.get("Timestamp")
        strike_value = row.get("Target_Strike")
        index_name = row.get("Index_Name")

        if row_hash in (None, ""):
            missing_hashes += 1
            hashes.append("<missing>")
        else:
            hashes.append(row_hash)

        if isinstance(timestamp_value, datetime) and strike_value is not None and index_name is not None:
            timestamp_strike_keys.append((timestamp_value, strike_value, index_name))
        else:
            timestamp_strike_keys.append((None, None, index_name))

    counter = Counter(hashes)
    duplicate_hashes = sum(

        count - 1

        for count in counter.values()

        if count > 1

    )

    timestamp_strike_counter = Counter(timestamp_strike_keys)
    duplicate_timestamp_strike = sum(

        count - 1

        for count in timestamp_strike_counter.values()

        if count > 1

    )

    return {

        "duplicate_row_hash": duplicate_hashes + missing_hashes,

        "duplicate_timestamp_strike": duplicate_timestamp_strike

    }


# ==========================================================
# NULL Validation
# ==========================================================

def validate_nulls(rows):

    count = 0

    for row in rows:

        for value in row.values():

            if value is None or value == "":

                count += 1

    return count


# ==========================================================
# Zero OI Validation
# ==========================================================

def validate_zero_oi(rows):

    count = 0

    for row in rows:

        if safe_int(row.get("CE_Open_Interest")) == 0:
            count += 1

        if safe_int(row.get("PE_Open_Interest")) == 0:
            count += 1

    return count


# ==========================================================
# Zero Volume Validation
# ==========================================================

def validate_zero_volume(rows):

    count = 0

    for row in rows:

        if safe_int(row.get("CE_Cumulative_Vol")) == 0:
            count += 1

        if safe_int(row.get("PE_Cumulative_Vol")) == 0:
            count += 1

    return count


# ==========================================================
# Price Source Validation
# ==========================================================

def validate_price_source(rows):

    sources = Counter()

    for row in rows:

        ce = row.get("CE_Price_Source")
        pe = row.get("PE_Price_Source")

        if ce:
            sources[ce] += 1

        if pe:
            sources[pe] += 1

    return dict(sources)

# ==========================================================
# Index Analysis
# ==========================================================

def analyze_index(index_name, rows):

    timestamp_result = validate_timestamps(rows)

    strike_result = validate_strikes(rows)

    duplicate_result = validate_duplicates(rows)

    duplicate_row_hash = duplicate_result["duplicate_row_hash"]
    duplicate_timestamp_strike = duplicate_result["duplicate_timestamp_strike"]

    null_values = validate_nulls(rows)

    zero_oi = validate_zero_oi(rows)
    zero_ce_oi = safe_int(sum(1 for row in rows if safe_int(row.get("CE_Open_Interest")) == 0))
    zero_pe_oi = safe_int(sum(1 for row in rows if safe_int(row.get("PE_Open_Interest")) == 0))

    zero_volume = validate_zero_volume(rows)
    zero_ce_volume = safe_int(sum(1 for row in rows if safe_int(row.get("CE_Cumulative_Vol")) == 0))
    zero_pe_volume = safe_int(sum(1 for row in rows if safe_int(row.get("PE_Cumulative_Vol")) == 0))

    price_sources = validate_price_source(rows)

    invalid_price_source = 0

    actual_rows = len(rows)

    expected_rows = EXPECTED_ROWS_PER_INDEX

    missing_rows = max(
        0,
        expected_rows - actual_rows
    )

    outside_market = 0

    for row in rows:

        timestamp_value = row.get("Timestamp")

        if isinstance(timestamp_value, datetime):
            current_time = timestamp_value.strftime("%H:%M")
        else:
            current_time = None

        if current_time is None or current_time not in EXPECTED_MINUTES:

            outside_market += 1

    overall = "PASS"

    if (
        timestamp_result["missing"] > 0
        or missing_rows > 0
        or duplicate_row_hash > 0
        or duplicate_timestamp_strike > 0
        or strike_result["missing"] > 0
        or null_values > 0
    ):
        overall = "FAIL"
    elif (
        zero_oi > 0
        or zero_volume > 0
        or outside_market > 0
    ):
        overall = "WARNING"

    return {

        "index": index_name,

        "expected_candles":
            EXPECTED_CANDLES,

        "actual_candles":
            timestamp_result["actual"],

        "missing_candles":
            timestamp_result["missing"],

        "expected_rows":
            expected_rows,

        "actual_rows":
            actual_rows,

        "missing_rows":
            missing_rows,

        "duplicate_rows":
            duplicate_row_hash,

        "duplicate_timestamp_strike":
            duplicate_timestamp_strike,

        "missing_strikes":
            strike_result["missing"],

        "missing_strike_details":
            strike_result["invalid_minutes"],

        "missing_minutes":
            timestamp_result["missing_list"],

        "null_values":
            null_values,

        "zero_oi":
            zero_oi,

        "zero_ce_oi":
            zero_ce_oi,

        "zero_pe_oi":
            zero_pe_oi,

        "zero_volume":
            zero_volume,

        "zero_ce_volume":
            zero_ce_volume,

        "zero_pe_volume":
            zero_pe_volume,

        "outside_market":
            outside_market,

        "price_sources":
            price_sources,

        "overall":
            overall

    }


# ==========================================================
# Analyze Complete Database
# ==========================================================

def analyze_database(grouped_rows):

    results = []

    for index_name in INDICES:

        rows = grouped_rows.get(index_name, [])

        result = analyze_index(
            index_name,
            rows
        )

        results.append(result)

    return results


# ==========================================================
# Summary
# ==========================================================

def build_summary(results):

    summary = {

        "indices_checked": len(results),

        "expected_rows": 0,

        "actual_rows": 0,

        "missing_rows": 0,

        "duplicate_rows": 0,

        "duplicate_timestamp_strike": 0,

        "null_values": 0,

        "missing_candles": 0,

        "zero_ce_oi": 0,

        "zero_pe_oi": 0,

        "zero_ce_volume": 0,

        "zero_pe_volume": 0,

        "price_sources": Counter(),

        "outside_market": 0,

        "missing_strikes": 0,

        "overall": "PASS"

    }

    for item in results:

        summary["expected_rows"] += item["expected_rows"]

        summary["actual_rows"] += item["actual_rows"]

        summary["missing_rows"] += item["missing_rows"]

        summary["duplicate_rows"] += item["duplicate_rows"]

        summary["duplicate_timestamp_strike"] += item["duplicate_timestamp_strike"]

        summary["null_values"] += item["null_values"]

        summary["missing_candles"] += item["missing_candles"]

        summary["zero_ce_oi"] += item["zero_ce_oi"]

        summary["zero_pe_oi"] += item["zero_pe_oi"]

        summary["zero_ce_volume"] += item["zero_ce_volume"]

        summary["zero_pe_volume"] += item["zero_pe_volume"]

        summary["price_sources"].update(item["price_sources"])

        summary["outside_market"] += item["outside_market"]

        summary["missing_strikes"] += item["missing_strikes"]

        if item["overall"] == "WARNING":

            summary["overall"] = "WARNING"

        if item["overall"] == "FAIL":

            summary["overall"] = "FAIL"

    return summary

# ==========================================================
# Report Printing
# ==========================================================

def print_index_report(result):

    print_separator()

    print(result["index"])

    print()

    print(f"Expected Candles          : {result['expected_candles']}")
    print(f"Actual Candles            : {result['actual_candles']}")
    print(f"Missing Candles           : {result['missing_candles']}")

    print()

    print(f"Expected Rows             : {result['expected_rows']}")
    print(f"Actual Rows               : {result['actual_rows']}")
    print(f"Missing Rows              : {result['missing_rows']}")

    print()

    print(f"Duplicate Row_Hash        : {result['duplicate_rows']}")
    print(f"Duplicate Timestamp+Strike: {result['duplicate_timestamp_strike']}")
    print(f"NULL Values               : {result['null_values']}")

    print()

    print(f"Missing Strikes           : {result['missing_strikes']}")
    if result["missing_strike_details"]:
        for detail in result["missing_strike_details"]:
            print(f"  {detail['minute']}")
            print(f"    Expected : {detail['expected']}")
            print(f"    Received : {detail['received']}")
            print(f"    Missing Count : {detail['expected'] - detail['received']}")
    print(f"Zero OI                   : {result['zero_oi']}")
    print(f"Zero Volume               : {result['zero_volume']}")

    print()

    print("Price Sources")

    for name, count in sorted(result["price_sources"].items()):
        print(f"  {name:<20} {count}")
    print(f"Rows Outside Market Hours : {result['outside_market']}")

    print()

    if result["missing_minutes"]:

        print("Missing Minutes")

        for minute in result["missing_minutes"]:

            print(f"  - {minute}")

        print()

    print(f"Overall Status            : {result['overall']}")

    print_separator()

    print()


# ==========================================================
# Summary Printing
# ==========================================================

def print_summary(summary):

    print_separator()

    print("SUMMARY")

    print()

    print(f"Indices Checked : {summary['indices_checked']}")

    print()

    print(f"Expected Rows   : {summary['expected_rows']}")
    print(f"Actual Rows     : {summary['actual_rows']}")
    print(f"Missing Rows    : {summary['missing_rows']}")

    print()

    print(f"Duplicate Row_Hash        : {summary['duplicate_rows']}")
    print(f"Duplicate Timestamp+Strike: {summary['duplicate_timestamp_strike']}")
    print(f"NULL Values              : {summary['null_values']}")

    print()

    print(f"Missing Candles          : {summary['missing_candles']}")
    print(f"Zero CE OI               : {summary['zero_ce_oi']}")
    print(f"Zero PE OI               : {summary['zero_pe_oi']}")
    print(f"Zero CE Volume           : {summary['zero_ce_volume']}")
    print(f"Zero PE Volume           : {summary['zero_pe_volume']}")
    print("Price Sources")
    for name, count in sorted(summary["price_sources"].items()):
        print(f"  {name:<20} {count}")
    print(f"Rows Outside Market Hours: {summary['outside_market']}")
    print(f"Missing Strikes          : {summary['missing_strikes']}")

    print()

    print(f"Overall Status  : {summary['overall']}")

    print_separator()


# ==========================================================
# Main
# ==========================================================

def main():

    conn = None

    try:

        conn = get_connection()

        rows = load_today_data(conn)

        grouped = group_by_index(rows)

        results = analyze_database(grouped)

        summary = build_summary(results)

        for result in results:

            print_index_report(result)

        print_summary(summary)

    except KeyboardInterrupt:

        print("\nInterrupted.")

        sys.exit(1)

    except Exception as exc:

        print(f"\nERROR : {exc}")

        sys.exit(1)

    finally:

        if conn is not None:

            conn.close()


# ==========================================================
# Entry
# ==========================================================

if __name__ == "__main__":

    main()