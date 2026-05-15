import json
import time
from pathlib import Path

import yfinance as yf

SCRIPT_DIR = Path(__file__).parent.absolute()
ROOT_DIR = SCRIPT_DIR.parent
DATA_DIR = ROOT_DIR / "data"
SYMBOLS_FILE = DATA_DIR / "symbols.json"
QUOTES_FILE = DATA_DIR / "quotes.json"

LIQUIDITY_THRESHOLD = 10_000_000
BREAKOUT_PCT = 0.02
BREAKOUT_WINDOW = 20
VOLUME_SPIKE_MULTIPLIER = 2.0
API_PAUSE_SECONDS = 0.4

DATA_DIR.mkdir(parents=True, exist_ok=True)

with open(SYMBOLS_FILE, "r", encoding="utf-8") as f:
    raw = json.load(f)
    symbols = raw["items"] if isinstance(raw, dict) and "items" in raw else raw


def to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def numeric_avg(values):
    nums = [x for x in values if isinstance(x, (int, float))]
    return sum(nums) / len(nums) if nums else None


def is_liquid(avg_dollar, threshold=LIQUIDITY_THRESHOLD):
    return bool(avg_dollar and avg_dollar >= threshold)


def has_catalyst(news_items, min_count=1):
    return len(news_items) >= min_count


def is_breakout(close_price, prior_high, pct=BREAKOUT_PCT):
    return bool(close_price and prior_high and close_price >= prior_high * (1 + pct))


def has_volume_spike(current_volume, avg_volume, mult=VOLUME_SPIKE_MULTIPLIER):
    return bool(current_volume and avg_volume and current_volume >= avg_volume * mult)


def compute_signal(liquid, catalyst, breakout, volume_spike_2x):
    if liquid and catalyst and (breakout or volume_spike_2x):
        return "Buy"
    if liquid:
        return "Hold"
    return "Sell"


results = []
errors = []

for item in symbols:
    symbol = item.get("finnhubSymbol") or item.get("ticker")
    if not symbol:
        continue
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="2mo", interval="1d")

        if hist.empty:
            errors.append({"symbol": symbol, "error": "No historical data returned"})
            continue

        closes = hist["Close"].tolist()
        volumes = hist["Volume"].tolist()
        latest = hist.iloc[-1]

        latest_close = to_float(latest["Close"])
        prev_close = to_float(hist.iloc[-2]["Close"]) if len(hist) >= 2 else None
        latest_volume = to_float(latest["Volume"])

        recent_closes = closes[-BREAKOUT_WINDOW:]
        prior_high = max(recent_closes[:-1]) if len(recent_closes) > 1 else None

        recent_volumes = volumes[-20:]
        avg_volume_20 = numeric_avg(recent_volumes[:-1]) if len(recent_volumes) > 1 else None

        avg_dollar_volume_20 = None
        if avg_volume_20 and latest_close:
            avg_dollar_volume_20 = round(avg_volume_20 * latest_close)

        percent_change = None
        if prev_close and latest_close and prev_close != 0:
            percent_change = round((latest_close - prev_close) / prev_close * 100, 4)

        news_items = []
        try:
            news_raw = ticker.news or []
            news_items = news_raw[:10]
        except Exception:
            pass

        headline = None
        if news_items:
            try:
                first = news_items[0]
                headline = (first.get("content", {}).get("title") or first.get("title") or "")[:100] or None
            except Exception:
                pass

        liquid = is_liquid(avg_dollar_volume_20)
        catalyst = has_catalyst(news_items)
        breakout = is_breakout(latest_close, prior_high)
        volume_spike_2x = has_volume_spike(latest_volume, avg_volume_20)
        signal = compute_signal(liquid, catalyst, breakout, volume_spike_2x)

        quote_ts = int(latest.name.timestamp()) if hasattr(latest.name, "timestamp") else int(time.time())

        results.append({
            "company": item.get("company", symbol),
            "ticker": symbol,
            "finnhubSymbol": symbol,
            "column": item.get("column", ""),
            "currentPrice": round(latest_close, 4) if latest_close else None,
            "prevClose": prev_close,
            "percentChange": percent_change,
            "volume": int(latest_volume) if latest_volume else None,
            "avgVolume20": int(avg_volume_20) if avg_volume_20 else None,
            "avgDollarVolume20": avg_dollar_volume_20,
            "timestamp": quote_ts,
            "liquid": liquid,
            "catalyst": catalyst,
            "catalystHeadline": headline,
            "breakout": breakout,
            "breakoutLevel": round(prior_high, 4) if prior_high else None,
            "volumeSpike2x": volume_spike_2x,
            "signal": signal,
            "dataSource": "Yahoo Finance / yfinance",
        })

        time.sleep(API_PAUSE_SECONDS)

    except Exception as e:
        errors.append({"symbol": symbol, "error": str(e)})

payload = {
    "updatedAt": int(time.time()),
    "source": "yahoo_finance",
    "ruleVersion": "v3-yfinance",
    "settings": {
        "liquidityThresholdUsd": LIQUIDITY_THRESHOLD,
        "breakoutWindow": BREAKOUT_WINDOW,
        "breakoutPct": BREAKOUT_PCT,
        "volumeSpikeMultiplier": VOLUME_SPIKE_MULTIPLIER,
    },
    "items": results,
    "errors": errors,
}

with open(QUOTES_FILE, "w", encoding="utf-8") as f:
    json.dump(payload, f, indent=2)

print(f"Wrote {len(results)} quotes to {QUOTES_FILE}")
if errors:
    print(f"Encountered {len(errors)} errors")


if __name__ == "__main__":
    pass
