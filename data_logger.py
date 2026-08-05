import os
import sys
import time
import json
import math
import hashlib
import urllib.request
from datetime import datetime, timedelta
import threading
import pytz
import pandas as pd
import numpy as np
import pyotp
from scipy.stats import norm
from dotenv import load_dotenv
from SmartApi import SmartConnect
from google.oauth2.service_account import Credentials
import gspread
from database.postgres_writer import PostgresWriter

# 🌍 SYSTEM HARDWARE CLOCK SYNCHRONIZATION
IST = pytz.timezone('Asia/Kolkata')
load_dotenv()

DATA_STORE = os.getenv("DATA_STORE", "db").strip().lower()
DATA_STORE_TARGETS = [target.strip() for target in DATA_STORE.split(",") if target.strip()]
STORE_IN_DB = any(target in ("db", "database") for target in DATA_STORE_TARGETS)
STORE_IN_GOOGLESHEET = any(target in ("googlesheet", "google", "sheet", "gs") for target in DATA_STORE_TARGETS)

if not (STORE_IN_DB or STORE_IN_GOOGLESHEET):
    print("⚠️ DATA_STORE invalid or empty; defaulting to db")
    STORE_IN_DB = True
    STORE_IN_GOOGLESHEET = False

# ==============================================================================
# 🎯 TARGET MARKET REFERENCE REGISTRY (OFFICIAL API DOCUMENTATION PARITY)
# ==============================================================================
TARGET_INDICES = {
    "NIFTY": {
        "scrip_name": "NIFTY 50",        # Name for live ltpData() index spot lookup
        "underlying_name": "NIFTY",      # 💎 FIXED: Matched exact option name string in Master JSON
        "hist_symbol": "Nifty 50",       
        "token": "26000",                # Live market streaming token
        "hist_token": "99926000",        # Official historical candle token ID
        "exchange": "NSE",
        "hist_exchange": "NSE",          
        "strike_step": 50,
        "sheet_tab": "Nifty_Data"
    },
    "BANKNIFTY": {
        "scrip_name": "NIFTY BANK",      
        "underlying_name": "BANKNIFTY",  
        "hist_symbol": "Nifty Bank",     
        "token": "26009",                
        "hist_token": "99926009",        
        "exchange": "NSE",
        "hist_exchange": "NSE",          
        "strike_step": 100,
        "sheet_tab": "BankNifty_Data"
    },
    "FINNIFTY": {
        "scrip_name": "NIFTY FIN SERVICE",
        "underlying_name": "FINNIFTY",   # 💎 FIXED: Correct derivative identifier
        "hist_symbol": "Nifty Fin Service",
        "token": "26037",                
        "hist_token": "99926037",        
        "exchange": "NSE",
        "hist_exchange": "NSE",          
        "strike_step": 50,
        "sheet_tab": "FinNifty_Data"
    },
    "SENSEX": {
        "scrip_name": "SENSEX",          
        "underlying_name": "SENSEX",     
        "hist_symbol": "SENSEX",         
        "token": "1",                    
        "hist_token": "99919000",        
        "exchange": "BSE",               
        "hist_exchange": "BSE",          
        "strike_step": 100,
        "sheet_tab": "Sensex_Data"
    }
}

# ==============================================================================
# 🧮 MODULE 1: ANALYTICAL BLACK-SCHOLES QUANT ENGINE
# ==============================================================================
def calculate_bs_metrics(S0, X, days_to_expiry, premium, option_type="CE", r=10.0):
    try:
        if days_to_expiry <= 0 or premium <= 0:
            return None, None, None, None, None

        # 🛡️ ARBITRAGE GUARD: a real option premium can never trade meaningfully
        # below intrinsic value. If it does, the input price is bad (stale/synthetic
        # data, not a genuine quote) and any IV/Greeks derived from it would be
        # nonsense (e.g. IV pinned to the 1% floor, Delta pinned to 1.0). Refuse to
        # compute rather than emit fabricated-looking numbers.
        intrinsic = max(S0 - X, 0.0) if option_type == "CE" else max(X - S0, 0.0)
        if premium < intrinsic - 0.5:
            return None, None, None, None, None

        S0, X, T = float(S0), float(X), float(days_to_expiry) / 365.0
        r_annual = float(r) / 100.0
        
        sigma = 0.30  
        for _ in range(12):
            d1 = (math.log(S0 / X) + (r_annual + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
            d2 = d1 - sigma * math.sqrt(T)
            
            if option_type == "CE":
                price = S0 * norm.cdf(d1) - X * math.exp(-r_annual * T) * norm.cdf(d2)
            else:
                price = X * math.exp(-r_annual * T) * norm.cdf(-d2) - S0 * norm.cdf(-d1)
                
            vega = S0 * math.sqrt(T) * (1.0 / math.sqrt(2.0 * math.pi)) * math.exp(-(d1 ** 2) / 2.0)
            if vega < 1e-6:
                break
                
            diff = price - premium
            if abs(diff) < 1e-4:
                break
            sigma = sigma - diff / vega

        sigma = max(0.01, min(1.5, sigma))  
        
        d1 = (math.log(S0 / X) + (r_annual + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        pdf_d1 = (1.0 / math.sqrt(2.0 * math.pi)) * math.exp(-(d1 ** 2) / 2.0)
        
        if option_type == "CE":
            delta = norm.cdf(d1)
            theta = -(S0 * pdf_d1 * sigma) / (2 * math.sqrt(T)) - r_annual * X * math.exp(-r_annual * T) * norm.cdf(d2)
        else:
            delta = norm.cdf(d1) - 1.0
            theta = -(S0 * pdf_d1 * sigma) / (2 * math.sqrt(T)) + r_annual * X * math.exp(-r_annual * T) * norm.cdf(-d2)
            
        gamma = pdf_d1 / (S0 * sigma * math.sqrt(T))
        vega_point = (S0 * math.sqrt(T) * pdf_d1) / 100.0  
        theta_day = theta / 365.0  
        
        return round(sigma * 100.0, 2), round(delta, 4), round(gamma, 6), round(theta_day, 4), round(vega_point, 4)
    except Exception:
        # Do not fabricate a plausible-looking Greeks row (the old fallback of
        # 15.0/0.0/0.0/0.0/0.0 looked like real output but wasn't). Blank cells
        # make a computation failure visible instead of hiding it as fake data.
        return None, None, None, None, None

# ==============================================================================
# ☁️ MODULE 2: SAFE MULTI-TAB CLOUD STORAGE MANAGEMENT
# ==============================================================================
class GoogleSheetStreamer:
    def __init__(self, json_key_path, sheet_name):
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_file(json_key_path, scopes=scopes)
        self.client = gspread.authorize(creds)
        self.sheet_name = sheet_name
        self.worksheets = {}
        self.initialize_all_tabs()

    def initialize_all_tabs(self):
        try:
            sh = self.client.open(self.sheet_name)
        except gspread.exceptions.SpreadsheetNotFound:
            sh = self.client.create(self.sheet_name)
            
        headers = [
            "Timestamp", "Index_Open", "Index_High", "Index_Low", "Index_Close", "Target_Strike",
            "CE_Symbol", "CE_Open", "CE_High", "CE_Low", "CE_Close", "CE_Volume_Delta", "CE_Cumulative_Vol", "CE_Open_Interest", "CE_OI_Change", "CE_Delta", "CE_Gamma", "CE_Theta", "CE_Vega",
            "PE_Symbol", "PE_Open", "PE_High", "PE_Low", "PE_Close", "PE_Volume_Delta", "PE_Cumulative_Vol", "PE_Open_Interest", "PE_OI_Change", "PE_Delta", "PE_Gamma", "PE_Theta", "PE_Vega",
            "ATM_Distance", "IV_CE", "IV_PE", "PCR_Strike", "VIX_Snapshot", "Row_Hash",
            # 🆕 Provenance columns: make it visible when a price is a real traded
            # candle vs. a carried-forward/live-tick value, instead of writing
            # both cases as indistinguishable-looking numbers.
            "CE_Price_Source", "PE_Price_Source"
        ]
        self.header_count = len(headers)

        try:
            default_sheet = sh.worksheet("Sheet1")
            default_sheet.update_title(TARGET_INDICES["BANKNIFTY"]["sheet_tab"])
            print(f"🔄 [MIGRATION] 'Sheet1' found and renamed to '{TARGET_INDICES['BANKNIFTY']['sheet_tab']}' successfully.")
        except gspread.exceptions.WorksheetNotFound:
            pass

        for index_id, meta in TARGET_INDICES.items():
            tab_title = meta["sheet_tab"]
            try:
                wks = sh.worksheet(tab_title)
            except gspread.exceptions.WorksheetNotFound:
                wks = sh.add_worksheet(title=tab_title, rows="1000", cols=len(headers) + 5)

            existing_headers = wks.row_values(1)
            if not existing_headers:
                wks.append_row(headers)
                print(f"📊 Tab '{tab_title}' initialized with systematic headers.")
            elif len(existing_headers) < len(headers):
                # Existing sheet predates the provenance columns — extend it in
                # place rather than silently misaligning future appended rows.
                # The worksheet's *grid* (not just its header row) is capped at
                # whatever it was created with (e.g. 38 cols for older tabs), so
                # the new column range must be grown before writing into it —
                # otherwise gspread raises "exceeds grid limits".
                missing = headers[len(existing_headers):]
                if wks.col_count < len(headers):
                    wks.add_cols(len(headers) - wks.col_count)
                wks.update(
                    range_name=f"{gspread.utils.rowcol_to_a1(1, len(existing_headers) + 1)}",
                    values=[missing]
                )
                print(f"🔄 [MIGRATION] Tab '{tab_title}' extended with new columns: {missing}")
            self.worksheets[index_id] = wks

    def append_rows_batch(self, index_id, matrix):
        if not matrix:
            print(f"❌ {index_id}: Empty matrix received")
            return False
        if index_id not in self.worksheets:
            print(f"❌ {index_id}: Worksheet not found")
            return False
        worksheet = self.worksheets[index_id]
        # Fast append: do NOT read whole sheet before/after each write.
        # Large get_all_values() calls were causing the logger to lag by many minutes.
        for attempt in range(3):
            try:
                worksheet.append_rows(matrix, value_input_option="USER_ENTERED")
                print(f"📊 {index_id}: appended_rows={len(matrix)}")
                return True
            except Exception as e:
                print(f"⚠️ Google Sheet append retry {attempt+1}/3 failed for {index_id}: {e}")
                time.sleep(1.5 * (attempt + 1))
        print(f"❌ Google Sheet append failed for {index_id} after retries")
        return False

# ==============================================================================
# 📡 MODULE 3: MULTI-INDEX SCRIP TOKEN MAPPING AND DISCOVERY
# ==============================================================================
class InstrumentManager:
    @staticmethod
    def get_scrip_list():
        print("📥 Requesting OpenAPI Scrip List master from Angel Broking endpoints...")
        url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            response = urllib.request.urlopen(req)
            return json.loads(response.read())
        except Exception as e:
            print(f"❌ Master file retrieval broke: {e}")
            sys.exit(1)

    @classmethod
    def process_options_chain(cls, scrip_json):
        records = []
        # Normalizing to uppercase to avoid accidental typing discrepancies
        valid_underlyings = [str(meta["underlying_name"]).strip().upper() for meta in TARGET_INDICES.values()]
        
        for item in scrip_json:
            name = item.get("name")
            if name:
                name_clean = str(name).strip().upper()
                if name_clean in valid_underlyings and item.get("instrumenttype") in ["OPTIDX", "OFTIDX"]:
                    try:
                        expiry = datetime.strptime(item["expiry"], "%d%b%Y").date()
                        strike = float(item["strike"]) / 100.0 if float(item["strike"]) > 1000 else float(item["strike"])
                        records.append({
                            "token": str(item["token"]), 
                            "symbol": str(item["symbol"]),
                            "scrip_name": name_clean,  # Stored clean to match configuration keys perfectly
                            "strike": strike, 
                            "expiry": expiry,
                            "type": "CE" if item["symbol"].endswith("CE") else "PE"
                        })
                    except Exception:
                        continue
        return pd.DataFrame(records)

    @staticmethod
    def find_vix_instrument(scrip_json):
        """Resolve the real India VIX index token/exchange from the live broker
        master file, instead of hardcoding a token number we cannot verify from
        this environment. Returns (token, exchange, scrip_name) or None if the
        master file doesn't expose a recognizable VIX index entry."""
        for item in scrip_json:
            name = str(item.get("name", "")).strip().upper()
            symbol = str(item.get("symbol", "")).strip().upper()
            if "VIX" in name or "VIX" in symbol:
                if item.get("instrumenttype") in ("AMXIDX", "INDEX", "") or item.get("exch_seg") == "NSE":
                    return {
                        "token": str(item.get("token")),
                        "exchange": item.get("exch_seg", "NSE"),
                        "scrip_name": item.get("name") or item.get("symbol")
                    }
        return None

# ==============================================================================
# 🛰️ MODULE 4: CENTRAL LIVE SNAPSHOT METRICS STORAGE
# ==============================================================================
class RealTimeDataCache:
    def __init__(self):
        self.lock = threading.Lock()
        self.token_store = {}
        self.index_ltps = {idx: 0.0 for idx in TARGET_INDICES}
        self.vix_ltp = None  # None means "no real VIX value observed yet" — never fabricated

    def update_vix(self, ltp):
        with self.lock:
            self.vix_ltp = ltp

    def get_vix(self):
        with self.lock:
            return self.vix_ltp

    def update_index(self, index_id, ltp):
        with self.lock:
            self.index_ltps[index_id] = ltp

    def update_option_oi(self, token, ltp, oi):
        token = str(token).strip()
        with self.lock:
            self.token_store[token] = {
                "ltp": float(ltp),
                "oi": int(oi or 0)
            }

    def get_snapshots(self):
        with self.lock:
            return self.index_ltps.copy(), json.loads(json.dumps(self.token_store))

global_data_cache = RealTimeDataCache()

# ==============================================================================
# 🔄 MODULE 5: CONTINUOUS BACKGROUND POLLING THREAD BLOCK
# ==============================================================================
def continuous_polling_worker(smart_conn, options_df, vix_instrument=None):
    print("🛰️ Background Tracking Thread Activated. Polling all 4 index matrix fields safely...")
    while True:
        try:
            now_ist = datetime.now(IST)
            if (9, 15) <= (now_ist.hour, now_ist.minute) <= (15, 30):
                
                # Step 1: Track active index spot tickers via live ltpData
                for index_id, meta in TARGET_INDICES.items():
                    spot_rest = smart_conn.ltpData(meta["exchange"], meta["scrip_name"], meta["token"])
                    if spot_rest.get("status") and spot_rest.get("data"):
                        idx_price = float(spot_rest["data"]["ltp"])
                        global_data_cache.update_index(index_id, idx_price)

                # Step 1b: Track real India VIX, resolved dynamically from the broker
                # master file (find_vix_instrument). If it wasn't found at startup,
                # we simply never populate a VIX value — we do not fabricate one.
                if vix_instrument:
                    try:
                        vix_rest = smart_conn.ltpData(
                            vix_instrument["exchange"], vix_instrument["scrip_name"], vix_instrument["token"]
                        )
                        if vix_rest.get("status") and vix_rest.get("data"):
                            global_data_cache.update_vix(float(vix_rest["data"]["ltp"]))
                    except Exception as e:
                        print(f"⚠️ VIX ltp fetch failed: {e}")
                    
                # Step 2: Track underlying active options tokens
                current_ltps, _ = global_data_cache.get_snapshots()
                token_payload_nfo = []
                token_payload_bfo = []

                for index_id, idx_price in current_ltps.items():
                    if idx_price == 0.0: continue
                    meta = TARGET_INDICES[index_id]
                    
                    atm_strike = round(idx_price / meta["strike_step"]) * meta["strike_step"]
                    index_slice = options_df[options_df["scrip_name"] == meta["underlying_name"].upper()]
                    if index_slice.empty: continue
                    
                    current_expiry = index_slice["expiry"].min()
                    target_strikes = [atm_strike + (offset * meta["strike_step"]) for offset in range(-5, 6)]
                    
                    for strike in target_strikes:
                        slice_df = index_slice[(index_slice["strike"] == float(strike)) & (index_slice["expiry"] == current_expiry)]
                        if slice_df.empty: continue
                        ce_meta = slice_df[slice_df["type"] == "CE"]
                        pe_meta = slice_df[slice_df["type"] == "PE"]
                        if ce_meta.empty or pe_meta.empty: continue
                        
                        t_ce = str(ce_meta.iloc[0]["token"])
                        t_pe = str(pe_meta.iloc[0]["token"])
                        
                        if meta["exchange"] == "BSE":
                            token_payload_bfo.extend([t_ce, t_pe])
                        else:
                            token_payload_nfo.extend([t_ce, t_pe])

                for exchange_code, raw_token_list in [("NFO", list(set(token_payload_nfo))), ("BFO", list(set(token_payload_bfo)))]:
                    if not raw_token_list: continue
                    
                    chunk_size = 10
                    token_chunks = [raw_token_list[i:i + chunk_size] for i in range(0, len(raw_token_list), chunk_size)]
                    
                    for chunk in token_chunks:
                        market_payload = smart_conn.getMarketData(mode="FULL", exchangeTokens={exchange_code: chunk})
                        if not market_payload.get("status"): 
                            print(f"⚠️ OI fetch failed for {exchange_code} chunk size={len(chunk)}")
                            continue
     
                        if market_payload.get("status") and market_payload.get("data") and market_payload["data"].get("fetched"):
                            fetched_ticks = market_payload["data"]["fetched"]
                            
                            # 💎 FIXED INDENTATION: Everything parsing the ticks must live inside this loop
                            for tick in fetched_ticks:
                                print(
                                    f"DEBUG TOKEN={tick.get('symbolToken')} "
                                    f"LTP={tick.get('ltp')} "
                                    f"OI={tick.get('opnInterest')} "
                                    f"KEYS={list(tick.keys())}"
                                )
                                
                                token = str(tick.get("symbolToken"))
                                ltp = float(tick.get("ltp", 0))
                                
                                oi = int(
                                    tick.get("opnInterest")
                                    or tick.get("openInterest")
                                    or tick.get("open_interest")
                                    or 0
                                )

                                if ltp > 0:
                                    global_data_cache.update_option_oi(token, ltp, oi)                      
            time.sleep(8)  
        except Exception as e:
            print(f"⚠️ Warning inside background worker loop: {e}")
            time.sleep(5)

# ==============================================================================
# 🛰️ MODULE 6: MAIN HISTORICAL CANDLE EXTRACTION ENGINE
# ==============================================================================
def fetch_verified_candle_metrics(smart_conn, exchange, token, trading_symbol, start_str, end_str):
    try:
        params = {
            "exchange": exchange,
            "symboltoken": str(token),
            "tradingsymbol": str(trading_symbol),  
            "interval": "ONE_MINUTE",
            "fromdate": start_str,  # Expected format: "YYYY-MM-DD HH:MM"
            "todate": end_str      # Expected format: "YYYY-MM-DD HH:MM"
        }
        res = smart_conn.getCandleData(params)
        if res.get("status") and res.get("data") and len(res["data"]) > 0:
            c = res["data"][-1]
            return {
                "open": float(c[1]), "high": float(c[2]), "low": float(c[3]), "close": float(c[4]), "volume": int(c[5])
            }
    except Exception:
        pass
    return None

def main():
    print("\n🔑 --- STARTING ENGINE REGISTRATION ---")
    client_code = os.getenv("ANGEL_CLIENT_CODE")
    api_key = os.getenv("ANGEL_API_KEY")
    password = os.getenv("ANGEL_PASSWORD")
    totp_secret = os.getenv("ANGEL_TOTP_SECRET")

    try:
        smart_conn = SmartConnect(api_key=api_key)
        totp_obj = pyotp.TOTP(totp_secret.strip().replace(" ", ""))
        session = smart_conn.generateSession(client_code, password, totp_obj.now())
        if not session.get("status"):
            print(f"❌ Handshake Denied: {session.get('message')}")
            sys.exit(1)
        print("✅ SUCCESS: Main session authenticated successfully.")
    except Exception as e:
        print(f"❌ Connection crash: {e}")
        sys.exit(1)

    sheet_name = os.getenv("GOOGLE_SHEET_NAME", "MultiIndex_Options_Archive_2026")
    sheet_writer = GoogleSheetStreamer("google_creds.json", sheet_name) if STORE_IN_GOOGLESHEET else None
    db_writer = PostgresWriter() if STORE_IN_DB else None
    print(f"📦 Data store targets: {', '.join(DATA_STORE_TARGETS) if DATA_STORE_TARGETS else 'db'}")
    scrip_json = InstrumentManager.get_scrip_list()
    options_df = InstrumentManager.process_options_chain(scrip_json)

    # Resolve the real India VIX instrument from the live master file. If it
    # isn't found, vix_instrument stays None and VIX_Snapshot is written blank
    # for this run rather than a hardcoded guess.
    vix_instrument = InstrumentManager.find_vix_instrument(scrip_json)
    if vix_instrument:
        print(f"✅ Resolved live India VIX instrument: {vix_instrument}")
    else:
        print("⚠️ Could not resolve a live India VIX instrument from the master file — VIX_Snapshot will be left blank, not guessed.")

    bg_thread = threading.Thread(target=continuous_polling_worker, args=(smart_conn, options_df, vix_instrument))
    bg_thread.daemon = True
    bg_thread.start()

    print("⏳ System setup finalized. Sheet commit thread active...")
    
    historical_options_oi_baselines = {}
    last_known_option_prices = {} 
    running_cumulative_volumes = {}
    previous_minute_volumes = {}
    
    processed_minutes_registry = {idx: None for idx in TARGET_INDICES}

    while True:
        try:
            now_ist = datetime.now(IST)
            current_min = now_ist.strftime('%Y-%m-%d %H:%M')

            if (9, 15) <= (now_ist.hour, now_ist.minute) <= (15, 30):
                
                for index_id, idx_meta in TARGET_INDICES.items():
                    # Catch up all missing minutes up to current_time - 1 minute.
                    # This prevents a single delayed cycle from permanently keeping the logger behind.
                    market_cutoff = now_ist.replace(second=0, microsecond=0) - timedelta(minutes=1)
                    last_processed = processed_minutes_registry.get(index_id)
                    if last_processed:
                        next_target = IST.localize(datetime.strptime(last_processed, "%Y-%m-%d %H:%M")) + timedelta(minutes=1)
                    else:
                        next_target = market_cutoff

                    catchup_guard = 0
                    while next_target <= market_cutoff and catchup_guard < 20:
                        target_time = next_target
                        catchup_guard += 1
                        start_query_str = target_time.strftime("%Y-%m-%d %H:%M")
                        end_query_str = target_time.strftime("%Y-%m-%d %H:%M")
                        timestamp_str = target_time.strftime("%Y-%m-%d %H:%M:00")

                        print(f"🔍 [LIVE TRACE] Checking pipeline for {index_id} at {now_ist.strftime('%H:%M:%S')}. Query window: {start_query_str}")

                        # ==============================================================================
                        # 💎 REAL MINUTE CANDLE FIRST, LIVE-TICK SYNTHESIS ONLY AS LAST RESORT
                        # ==============================================================================
                        # fetch_verified_candle_metrics() returns a genuine 1-minute OHLC candle from
                        # the broker's historical candle API and MUST be the primary source — it is the
                        # only path that ever has real high/low. The live LTP cache only ever contains a
                        # single instantaneous tick, so building open/high/low/close from it always
                        # produces a flat (zero-body) candle. Previously this branch order was reversed,
                        # which meant every minute the live cache was populated (i.e. almost always)
                        # silently overrode the real candle with a flat one.
                        idx_candle = fetch_verified_candle_metrics(
                            smart_conn, 
                            idx_meta["hist_exchange"], 
                            idx_meta["hist_token"], 
                            idx_meta["hist_symbol"], 
                            start_query_str, 
                            end_query_str
                        )

                        if not idx_candle or idx_candle["close"] <= 0.0:
                            # Genuine fallback: broker historical-candle API failed/returned nothing.
                            # Use the live tick cache so we don't lose the minute entirely, but this
                            # candle will unavoidably be flat (open==high==low==close) since it's a
                            # single price snapshot, not an aggregated range.
                            current_ltps, live_oi_snapshot = global_data_cache.get_snapshots()
                            live_spot_price = current_ltps.get(index_id, 0.0)
                            if live_spot_price > 0.0:
                                idx_candle = {
                                    "open": live_spot_price,
                                    "high": live_spot_price,
                                    "low": live_spot_price,
                                    "close": live_spot_price,
                                    "volume": 0
                                }
                        else:
                            _, live_oi_snapshot = global_data_cache.get_snapshots()
                        
                        if not idx_candle or idx_candle["close"] <= 0.0:
                            print(f"⚠️ [LIVE TRACE] {index_id} skipped for {start_query_str}. Reason: Live data streaming cache initializing...")
                            processed_minutes_registry[index_id] = target_time.strftime("%Y-%m-%d %H:%M")
                            next_target = target_time + timedelta(minutes=1)
                            time.sleep(0.15)
                            continue

                        idx_close = idx_candle["close"]
                        atm_strike = round(idx_close / idx_meta["strike_step"]) * idx_meta["strike_step"]
                        
                        index_slice = options_df[options_df["scrip_name"] == idx_meta["underlying_name"].upper()]
                        if index_slice.empty:
                            print(f"⚠️ [LIVE TRACE] {index_id} skipped for {start_query_str}. Reason: Master dataframe slice empty for underlying '{idx_meta['underlying_name']}'")
                            processed_minutes_registry[index_id] = target_time.strftime("%Y-%m-%d %H:%M")
                            next_target = target_time + timedelta(minutes=1)
                            time.sleep(0.15)
                            continue
                        
                        valid_expiries = index_slice[index_slice["expiry"] >= now_ist.date()]
                        if valid_expiries.empty:
                            print(f"⚠️ [LIVE TRACE] {index_id} skipped for {start_query_str}. Reason: No active non-expired contracts found.")
                            processed_minutes_registry[index_id] = target_time.strftime("%Y-%m-%d %H:%M")
                            next_target = target_time + timedelta(minutes=1)
                            time.sleep(0.15)
                            continue
                        current_expiry = valid_expiries["expiry"].min()
                        
                        expiry_datetime = IST.localize(
                            datetime.combine(
                                current_expiry,
                                datetime.strptime("15:30", "%H:%M").time()
                            )
                        )           
                        days_to_expiry = max((expiry_datetime - now_ist).total_seconds() / 86400, 0.001)
                        
                        target_strikes = [atm_strike + (offset * idx_meta["strike_step"]) for offset in range(-5, 6)]
                        minute_batch_payload = []

                        sample_token_check = index_slice[index_slice["strike"] == float(atm_strike)]
                        if not sample_token_check.empty:
                            check_tok = str(sample_token_check.iloc[0]["token"])
                            if live_oi_snapshot.get(check_tok, {}).get("oi", 0) == 0:
                                print(f"ℹ️ [LIVE TRACE] Background streaming cache for {index_id} ATM token ({check_tok}) is currently showing 0 Open Interest.")

                        for strike in target_strikes:
                            slice_df = index_slice[(index_slice["strike"] == float(strike)) & (index_slice["expiry"] == current_expiry)]
                            if slice_df.empty: continue
                            ce_meta = slice_df[slice_df["type"] == "CE"]
                            pe_meta = slice_df[slice_df["type"] == "PE"]
                            if ce_meta.empty or pe_meta.empty: continue
                            
                            ce_tok, ce_sym = str(ce_meta.iloc[0]["token"]), ce_meta.iloc[0]["symbol"]
                            pe_tok, pe_sym = str(pe_meta.iloc[0]["token"]), pe_meta.iloc[0]["symbol"]

                            # Option charts fetch requests run on alternative string configurations
                            ce_candle = fetch_verified_candle_metrics(smart_conn, "NFO" if index_id != "SENSEX" else "BFO", ce_tok, ce_sym, start_query_str, end_query_str)
                            pe_candle = fetch_verified_candle_metrics(smart_conn, "NFO" if index_id != "SENSEX" else "BFO", pe_tok, pe_sym, start_query_str, end_query_str)

                            ce_live_oi = int(live_oi_snapshot.get(str(ce_tok), {}).get("oi", historical_options_oi_baselines.get(str(ce_tok),0)))
                            pe_live_oi = int(live_oi_snapshot.get(str(pe_tok), {}).get("oi", historical_options_oi_baselines.get(str(pe_tok),0)))

                            # CALL RESOLVER
                            # Provenance order, strictly weakest-to-strongest fabrication:
                            #   1) CANDLE     — a genuine traded 1-minute OHLC candle (best)
                            #   2) LAST_KNOWN — this option's own last real traded close, carried
                            #                   forward because it didn't trade again this minute
                            #   3) LIVE_LTP   — a live tick from the background OI/LTP poller
                            #                   (real quote, just not a fresh candle)
                            # There is deliberately no 4th tier that invents a price (e.g. the old
                            # `idx_close * 0.007` guess). If none of the above exist, this leg has
                            # no real data basis and the strike is skipped for this minute instead
                            # of writing a fabricated number — see the skip check below.
                            if ce_candle:
                                c_open, c_high, c_low, c_close, c_vol = ce_candle["open"], ce_candle["high"], ce_candle["low"], ce_candle["close"], ce_candle["volume"]
                                last_known_option_prices[ce_tok] = c_close
                                ce_source = "CANDLE"
                            elif ce_tok in last_known_option_prices:
                                backup_price = last_known_option_prices[ce_tok]
                                c_open, c_high, c_low, c_close, c_vol = backup_price, backup_price, backup_price, backup_price, 0
                                ce_source = "LAST_KNOWN"
                            elif live_oi_snapshot.get(ce_tok, {}).get("ltp", 0) > 0:
                                backup_price = live_oi_snapshot[ce_tok]["ltp"]
                                c_open, c_high, c_low, c_close, c_vol = backup_price, backup_price, backup_price, backup_price, 0
                                ce_source = "LIVE_LTP"
                            else:
                                c_open = c_high = c_low = c_close = c_vol = None
                                ce_source = "NO_DATA"

                            # PUT RESOLVER (same provenance rules as the call leg above)
                            if pe_candle:
                                p_open, p_high, p_low, p_close, p_vol = pe_candle["open"], pe_candle["high"], pe_candle["low"], pe_candle["close"], pe_candle["volume"]
                                last_known_option_prices[pe_tok] = p_close
                                pe_source = "CANDLE"
                            elif pe_tok in last_known_option_prices:
                                backup_price = last_known_option_prices[pe_tok]
                                p_open, p_high, p_low, p_close, p_vol = backup_price, backup_price, backup_price, backup_price, 0
                                pe_source = "LAST_KNOWN"
                            elif live_oi_snapshot.get(pe_tok, {}).get("ltp", 0) > 0:
                                backup_price = live_oi_snapshot[pe_tok]["ltp"]
                                p_open, p_high, p_low, p_close, p_vol = backup_price, backup_price, backup_price, backup_price, 0
                                pe_source = "LIVE_LTP"
                            else:
                                p_open = p_high = p_low = p_close = p_vol = None
                                pe_source = "NO_DATA"

                            if ce_source == "NO_DATA" or pe_source == "NO_DATA":
                                # No real price basis exists for at least one leg of this strike —
                                # skip it rather than write a fabricated row. This minute/strike
                                # will simply be absent from the archive instead of misleading.
                                print(f"⚠️ [LIVE TRACE] {index_id} strike {strike} skipped for {start_query_str}. Reason: no real price data for {'CE' if ce_source == 'NO_DATA' else 'PE'} leg.")
                                continue

                            # TRUE VOLUME DELTA + STABLE CUMULATIVE VOLUME
                            ce_volume_key = f"{index_id}_{strike}_CE"
                            pe_volume_key = f"{index_id}_{strike}_PE"

                            prev_ce_vol = previous_minute_volumes.get(ce_volume_key, c_vol)
                            prev_pe_vol = previous_minute_volumes.get(pe_volume_key, p_vol)

                            ce_volume_delta = max(0, c_vol - prev_ce_vol)
                            pe_volume_delta = max(0, p_vol - prev_pe_vol)

                            previous_minute_volumes[ce_volume_key] = c_vol
                            previous_minute_volumes[pe_volume_key] = p_vol

                            if ce_volume_key not in running_cumulative_volumes:
                                running_cumulative_volumes[ce_volume_key] = c_vol
                            else:
                                running_cumulative_volumes[ce_volume_key] += ce_volume_delta

                            if pe_volume_key not in running_cumulative_volumes:
                                running_cumulative_volumes[pe_volume_key] = p_vol
                            else:
                                running_cumulative_volumes[pe_volume_key] += pe_volume_delta

                            ce_cum_vol = running_cumulative_volumes[ce_volume_key]
                            pe_cum_vol = running_cumulative_volumes[pe_volume_key]

                            if ce_tok not in historical_options_oi_baselines and ce_live_oi > 0:
                                historical_options_oi_baselines[ce_tok] = ce_live_oi
                            if pe_tok not in historical_options_oi_baselines and pe_live_oi > 0:
                                historical_options_oi_baselines[pe_tok] = pe_live_oi

                            ce_oi_change = ce_live_oi - historical_options_oi_baselines.get(ce_tok, ce_live_oi)
                            pe_oi_change = pe_live_oi - historical_options_oi_baselines.get(pe_tok, pe_live_oi)

                            ce_iv, ce_del, ce_gam, ce_th, ce_vg = calculate_bs_metrics(idx_close, strike, days_to_expiry, c_close, "CE")
                            pe_iv, pe_del, pe_gam, pe_th, pe_vg = calculate_bs_metrics(idx_close, strike, days_to_expiry, p_close, "PE")
                            
                            atm_dist = abs(idx_close - strike)
                            pcr = round(pe_live_oi / ce_live_oi, 2) if ce_live_oi > 0 else 0.0
                            hash_src = f"{timestamp_str}_{strike}_{idx_close}"
                            row_hash = hashlib.md5(hash_src.encode()).hexdigest()

                            # Write blank cells (empty string, not a fabricated number) wherever
                            # Greeks/VIX could not be computed/observed from real data.
                            vix_value = global_data_cache.get_vix()
                            row = [
                                timestamp_str, idx_candle["open"], idx_candle["high"], idx_candle["low"], idx_close, strike,
                                ce_sym, c_open, c_high, c_low, c_close, ce_volume_delta, ce_cum_vol, ce_live_oi, ce_oi_change,
                                ce_del if ce_del is not None else "", ce_gam if ce_gam is not None else "",
                                ce_th if ce_th is not None else "", ce_vg if ce_vg is not None else "",
                                pe_sym, p_open, p_high, p_low, p_close, pe_volume_delta, pe_cum_vol, pe_live_oi, pe_oi_change,
                                pe_del if pe_del is not None else "", pe_gam if pe_gam is not None else "",
                                pe_th if pe_th is not None else "", pe_vg if pe_vg is not None else "",
                                atm_dist,
                                ce_iv if ce_iv is not None else "", pe_iv if pe_iv is not None else "",
                                pcr, vix_value if vix_value is not None else "", row_hash,
                                ce_source, pe_source
                            ]
                            minute_batch_payload.append(row)

                        if minute_batch_payload:
                            if sheet_writer:
                                sheet_writer.append_rows_batch(index_id, minute_batch_payload)
                            if db_writer:
                                db_writer.insert_batch(index_id, minute_batch_payload)
                            print(f"✅ [{target_time.strftime('%H:%M:%S')}] Saved true 11-strike option matrix for {index_id}")
                            sys.stdout.flush()
                            processed_minutes_registry[index_id] = target_time.strftime("%Y-%m-%d %H:%M")
                        else:
                            print(f"⚠️ [LIVE TRACE] {index_id} generated 0 payload rows for {start_query_str}. Skipping spreadsheet commit.")
                            # Mark this minute as processed so one bad/minor gap minute does not
                            # block the rest of the day for that index.
                            processed_minutes_registry[index_id] = target_time.strftime("%Y-%m-%d %H:%M")

                        next_target = target_time + timedelta(minutes=1)

                        # small spacing between catch-up minutes to avoid API burst, but keep it light
                        time.sleep(0.15) 

            time.sleep(5) 
        except Exception as loop_err:
            print(f"❌ [LIVE TRACE CRITICAL ERROR]: {loop_err}")
            time.sleep(5)

def run_dummy_web_server():
    from http.server import SimpleHTTPRequestHandler
    import socketserver
    port = int(os.getenv("PORT", 10000))
    class SafeHandler(SimpleHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Data Logger Status: ACTIVE")
    socketserver.TCPServer.allow_reuse_address = True
    try:
        with socketserver.TCPServer(("0.0.0.0", port), SafeHandler) as httpd:
            httpd.serve_forever()
    except Exception:
        pass

if __name__ == "__main__":
    web_thread = threading.Thread(target=run_dummy_web_server)
    web_thread.daemon = True
    web_thread.start()
    time.sleep(1)
    main()
