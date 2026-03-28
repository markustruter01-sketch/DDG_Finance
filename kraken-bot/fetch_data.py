"""
fetch_data.py  —  Kraken Historical Data Pipeline
===================================================
This script is our historical data engine. Its one job is to connect to
Kraken's public market-data API, download a full year of BTC/USD hourly
price candles (OHLCV), clean them up, and save everything to a CSV file
that the rest of the trading bot can use for backtesting and strategy tuning.

No API keys are needed — Kraken makes historical price data publicly
available without authentication.

Run with:  python3 kraken-bot/fetch_data.py
Output  :  kraken_training_data.csv  (created in the project root)

IMPORTANT — Kraken API depth limitation
----------------------------------------
Kraken's public OHLCV endpoint has a hard cap: regardless of the `since`
parameter you pass, it returns at most ~720 candles per symbol/timeframe
combination across the entire rolling window currently stored on their servers.
For the 1h timeframe this means you will typically get ~720 rows (~30 days),
not the full 365 days described in the task specification.

This is an upstream API constraint — the script itself is correct and will
fetch everything Kraken makes available. If true 365-day hourly history is
required, use a paid Kraken historical-data endpoint, or switch to an
alternative data vendor (e.g. CryptoCompare, Kaiko, or a Binance mirror) while
keeping the same six-column CSV contract (timestamp, open, high, low, close,
volume) so the rest of the codebase does not need to change.
"""

import time
from datetime import datetime, timezone, timedelta
from collections import deque

import ccxt        # The universal crypto exchange library — handles all the
                   # messy API details for us (rate limits, auth, pagination)
import pandas as pd  # pandas gives us a powerful table (DataFrame) to organise
                     # and export the data cleanly


# ── Step 1: Connect to Kraken ────────────────────────────────────────────────
# We create a "public" connection — no API keys needed for reading price data.
# Setting 'enableRateLimit' to True tells ccxt to automatically pause between
# requests so we don't get banned by Kraken for hitting their API too fast.

exchange = ccxt.kraken({
    "enableRateLimit": True,
})

print("✓ Connected to Kraken (public API — no keys required)")


# ── Step 2: Define what data we want ─────────────────────────────────────────
# We want BTC/USD because it is the most liquid crypto pair on Kraken.
# The '1h' timeframe means each candle represents one hour of trading.
# DAYS_BACK = 365 gives us exactly one calendar year of price history.

SYMBOL    = "BTC/USD"          # The trading pair we want data for
TIMEFRAME = "1h"               # One candle per hour
DAYS_BACK = 365                # How far back in time to look
BATCH     = 720                # How many candles to fetch in one request.
                               # Kraken's API returns a maximum of 720 candles
                               # per call, so we fetch in batches and stitch
                               # them together.

# Calculate the Unix timestamp (milliseconds) for exactly 365 days ago.
# ccxt uses milliseconds for all timestamps — hence * 1000.
since_ms = exchange.parse8601(
    (datetime.now(tz=timezone.utc) - timedelta(days=DAYS_BACK))
    .strftime("%Y-%m-%dT%H:%M:%SZ")
)

print(f"  Symbol    : {SYMBOL}")
print(f"  Timeframe : {TIMEFRAME}")
print(f"  Start date: {datetime.utcfromtimestamp(since_ms / 1000).strftime('%Y-%m-%d %H:%M UTC')}")
print(f"  End date  : {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
print(f"  Expected  : ~{DAYS_BACK * 24} candles ({DAYS_BACK} days × 24 hours)\n")


# ── Step 3: Fetch data in batches with retry logic ────────────────────────────
# Because Kraken only returns 720 candles per request, we need to loop:
# fetch a batch → move the start time forward → fetch the next batch → repeat
# until we have collected the full year.
#
# We also add retry logic: if a request fails (e.g. network hiccup), we
# try up to 3 times before giving up. This makes the script robust enough
# to run unattended in production.

MAX_RETRIES = 3   # How many times to retry a failed API call before giving up
all_candles = []  # We will collect every candle here
current_since = since_ms  # We advance this forward with each batch

print("Fetching data from Kraken...")

while True:
    # ── Attempt this batch with up to MAX_RETRIES tries ──────────────────────
    batch = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            # Ask Kraken for up to BATCH candles starting from 'current_since'.
            # ccxt returns a list of [timestamp_ms, open, high, low, close, volume]
            batch = exchange.fetch_ohlcv(
                symbol=SYMBOL,
                timeframe=TIMEFRAME,
                since=current_since,
                limit=BATCH,
            )
            break  # If we got here without an exception, the request succeeded
        except Exception as err:
            if attempt < MAX_RETRIES:
                wait = 5 * attempt  # Back off: wait 5s, then 10s, then 15s
                print(f"  ⚠ Attempt {attempt} failed ({err}) — retrying in {wait}s...")
                time.sleep(wait)
            else:
                # We exhausted all retries — raise the error so the user knows
                raise RuntimeError(
                    f"Failed to fetch data after {MAX_RETRIES} attempts: {err}"
                )

    # ── Check if this batch has any data ─────────────────────────────────────
    if not batch:
        # An empty batch means we have reached the present — we're done!
        print("  ✓ No more candles available — reached current time.\n")
        break

    # ── Add this batch to our collection ─────────────────────────────────────
    all_candles.extend(batch)

    # ── Print progress so the user can see it working ────────────────────────
    last_ts   = batch[-1][0]  # Timestamp of the last candle in this batch (ms)
    last_dt   = datetime.utcfromtimestamp(last_ts / 1000).strftime("%Y-%m-%d %H:%M")
    print(f"  Fetched {len(batch):>4} candles | Total so far: {len(all_candles):>6} | Up to: {last_dt} UTC")

    # ── If we got fewer candles than the batch size, we've hit the end ───────
    if len(batch) < BATCH:
        print("  ✓ Partial batch received — no more historical data available.\n")
        break

    # ── Advance the start time to just after the last candle we received ──────
    # Adding 1 ms prevents us from fetching the same last candle twice
    current_since = last_ts + 1

    # ── Be polite to Kraken's servers — pause briefly between requests ────────
    time.sleep(exchange.rateLimit / 1000)  # rateLimit is in ms, sleep takes seconds


# ── Step 4: Sanity check ─────────────────────────────────────────────────────
# Make sure we actually collected some data before proceeding.

if not all_candles:
    raise RuntimeError(
        "No candles were fetched — check your internet connection or the symbol name."
    )

print(f"Raw candles collected: {len(all_candles):,}")


# ── Step 5: Build a clean pandas DataFrame ────────────────────────────────────
# Each candle from ccxt is a list: [timestamp_ms, open, high, low, close, volume]
# We unpack these into named columns so the data is readable and easy to work with.

df = pd.DataFrame(
    all_candles,
    columns=["timestamp_ms", "open", "high", "low", "close", "volume"],
)

# Convert the millisecond Unix timestamp into a human-readable datetime string.
# This makes the CSV file much easier to read and import into other tools.
df["timestamp"] = pd.to_datetime(df["timestamp_ms"], unit="ms", utc=True)
df["timestamp"] = df["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S UTC")

# Drop the raw millisecond column — we only need the readable version
df = df.drop(columns=["timestamp_ms"])

# Reorder so timestamp comes first, then the OHLCV columns
df = df[["timestamp", "open", "high", "low", "close", "volume"]]

# Remove any duplicate rows (can happen at batch boundaries)
df = df.drop_duplicates(subset=["timestamp"])

# Sort chronologically — oldest candle first
df = df.sort_values("timestamp").reset_index(drop=True)

# Round prices to 2 decimal places and volume to 8 (crypto precision)
df["open"]   = df["open"].round(2)
df["high"]   = df["high"].round(2)
df["low"]    = df["low"].round(2)
df["close"]  = df["close"].round(2)
df["volume"] = df["volume"].round(8)

print(f"After cleaning        : {len(df):,} unique candles")


# ── Step 6: Export to CSV ─────────────────────────────────────────────────────
# We save the file to the project root so it's easy to find and reference.
# index=False means we don't write the row numbers (0, 1, 2…) into the CSV.

OUTPUT_PATH = "kraken_training_data.csv"
df.to_csv(OUTPUT_PATH, index=False)


# ── Step 7: Print a final summary ─────────────────────────────────────────────
first_date = df["timestamp"].iloc[0]
last_date  = df["timestamp"].iloc[-1]

print("\n" + "=" * 60)
print("  KRAKEN DATA PIPELINE — COMPLETE")
print("=" * 60)
print(f"  Symbol    : {SYMBOL}")
print(f"  Timeframe : {TIMEFRAME} (1-hour candles)")
print(f"  Rows      : {len(df):,} candles")
print(f"  From      : {first_date}")
print(f"  To        : {last_date}")
print(f"  Saved to  : {OUTPUT_PATH}")
print("=" * 60)
print("\nThis file is ready to use for backtesting.")
print("Load it in Python with:  pd.read_csv('kraken_training_data.csv')")
