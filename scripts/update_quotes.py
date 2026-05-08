import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / 'data'
SYMBOLS_FILE = DATA_DIR / 'symbols.json'
QUOTES_FILE = DATA_DIR / 'quotes.json'
API_KEY = os.getenv('FINNHUB_API_KEY')
RESOLUTION = 'D'
CANDLE_LOOKBACK_DAYS = 40
NEWS_LOOKBACK_DAYS = 7
LIQUIDITY_THRESHOLD_USD = 10_000_000
VOLUME_SPIKE_MULTIPLIER = 2.0
BREAKOUT_WINDOW = 20
API_PAUSE_SECONDS = 0.7

if not API_KEY:
    raise RuntimeError('FINNHUB_API_KEY is not set')

if not SYMBOLS_FILE.exists():
    raise FileNotFoundError(f'Missing symbols file: {SYMBOLS_FILE}')

with SYMBOLS_FILE.open('r', encoding='utf-8') as f:
    symbols = json.load(f)


def fetch_json(base_url, params):
    query = dict(params)
    query['token'] = API_KEY
    url = f"{base_url}?{urlencode(query)}"
    req = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urlopen(req, timeout=25) as response:
        return json.loads(response.read().decode('utf-8'))


def fetch_quote(symbol):
    return fetch_json('https://finnhub.io/api/v1/quote', {'symbol': symbol})


def fetch_candles(symbol, start_ts, end_ts):
    return fetch_json(
        'https://finnhub.io/api/v1/stock/candle',
        {
            'symbol': symbol,
            'resolution': RESOLUTION,
            'from': start_ts,
            'to': end_ts,
        },
    )


def fetch_company_news(symbol, news_from, news_to):
    return fetch_json(
        'https://finnhub.io/api/v1/company-news',
        {
            'symbol': symbol,
            'from': news_from,
            'to': news_to,
        },
    )


def numeric_avg(values):
    nums = [x for x in values if isinstance(x, (int, float))]
    return sum(nums) / len(nums) if nums else None


def extract_candle_metrics(candles):
    if not isinstance(candles, dict) or candles.get('s') != 'ok':
        return {}

    closes = candles.get('c', [])
    highs = candles.get('h', [])
    volumes = candles.get('v', [])
    timestamps = candles.get('t', [])

    if len(closes) < BREAKOUT_WINDOW or len(volumes) < BREAKOUT_WINDOW:
        return {
            'closes': closes,
            'highs': highs,
            'volumes': volumes,
            'timestamps': timestamps,
            'avg_volume_20': None,
            'avg_close_20': None,
            'avg_dollar_volume_20': None,
            'latest_volume': volumes[-1] if volumes else None,
            'latest_close': closes[-1] if closes else None,
            'prior_breakout_high': None,
            'latest_candle_time': datetime.fromtimestamp(timestamps[-1], tz=timezone.utc).isoformat() if timestamps else None,
        }

    recent_closes = closes[-BREAKOUT_WINDOW:]
    recent_highs = highs[-BREAKOUT_WINDOW:]
    recent_volumes = volumes[-BREAKOUT_WINDOW:]
    avg_volume_20 = numeric_avg(recent_volumes)
    avg_close_20 = numeric_avg(recent_closes)
    avg_dollar_volume_20 = avg_volume_20 * avg_close_20 if avg_volume_20 and avg_close_20 else None
    prior_breakout_high = max(recent_highs[:-1]) if len(recent_highs) >= 2 else None

    return {
        'closes': closes,
        'highs': highs,
        'volumes': volumes,
        'timestamps': timestamps,
        'avg_volume_20': avg_volume_20,
        'avg_close_20': avg_close_20,
        'avg_dollar_volume_20': avg_dollar_volume_20,
        'latest_volume': recent_volumes[-1] if recent_volumes else None,
        'latest_close': closes[-1] if closes else None,
        'prior_breakout_high': prior_breakout_high,
        'latest_candle_time': datetime.fromtimestamp(timestamps[-1], tz=timezone.utc).isoformat() if timestamps else None,
    }


def is_liquid(avg_dollar_volume_20):
    return bool(avg_dollar_volume_20 and avg_dollar_volume_20 >= LIQUIDITY_THRESHOLD_USD)


def has_catalyst(news_items):
    return bool(isinstance(news_items, list) and len(news_items) > 0)


def catalyst_details(news_items):
    if not isinstance(news_items, list) or not news_items:
        return None, None, 0
    first = news_items[0]
    return first.get('headline'), first.get('source'), len(news_items)


def is_breakout(latest_close, prior_breakout_high):
    return bool(latest_close and prior_breakout_high and latest_close > prior_breakout_high)


def has_volume_spike(latest_volume, avg_volume_20):
    return bool(latest_volume and avg_volume_20 and latest_volume >= VOLUME_SPIKE_MULTIPLIER * avg_volume_20)


def compute_signal(liquid, catalyst, breakout, volume_spike_2x):
    if liquid and catalyst and (breakout or volume_spike_2x):
        return 'Buy'
    if liquid:
        return 'Hold'
    return 'Sell'


def build_result(item, quote, candle_metrics, news_items):
    avg_volume_20 = candle_metrics.get('avg_volume_20')
    avg_dollar_volume_20 = candle_metrics.get('avg_dollar_volume_20')
    latest_volume = candle_metrics.get('latest_volume')
    latest_close = candle_metrics.get('latest_close') or quote.get('c')
    prior_breakout_high = candle_metrics.get('prior_breakout_high')

    liquid = is_liquid(avg_dollar_volume_20)
    catalyst = has_catalyst(news_items)
    breakout = is_breakout(latest_close, prior_breakout_high)
    volume_spike_2x = has_volume_spike(latest_volume, avg_volume_20)
    signal = compute_signal(liquid, catalyst, breakout, volume_spike_2x)
    catalyst_headline, catalyst_source, news_count = catalyst_details(news_items)

    return {
        'company': item.get('company'),
        'ticker': item.get('ticker'),
        'finnhubSymbol': item.get('finnhubSymbol'),
        'column': item.get('column'),
        'currentPrice': quote.get('c'),
        'change': quote.get('d'),
        'percentChange': quote.get('dp'),
        'high': quote.get('h'),
        'low': quote.get('l'),
        'open': quote.get('o'),
        'prevClose': quote.get('pc'),
        'timestamp': quote.get('t'),
        'liquid': liquid,
        'avgVolume20': avg_volume_20,
        'avgDollarVolume20': avg_dollar_volume_20,
        'latestVolume': latest_volume,
        'volumeSpike2x': volume_spike_2x,
        'breakout': breakout,
        'breakoutLevel': prior_breakout_high,
        'catalyst': catalyst,
        'catalystHeadline': catalyst_headline,
        'catalystSource': catalyst_source,
        'newsCount7d': news_count,
        'latestCandleTime': candle_metrics.get('latest_candle_time'),
        'signal': signal,
    }


def main():
    now = datetime.now(timezone.utc)
    start_ts = int((now - timedelta(days=CANDLE_LOOKBACK_DAYS)).timestamp())
    end_ts = int(now.timestamp())
    news_from = (now - timedelta(days=NEWS_LOOKBACK_DAYS)).date().isoformat()
    news_to = now.date().isoformat()

results = []
errors = []

for item in symbols:
    symbol = item.get('finnhubSymbol')
    if not symbol:
        continue

    try:
        quote = fetch_quote(symbol)
        time.sleep(API_PAUSE_SECONDS)

        candles = fetch_candles(symbol, start_ts, end_ts)
        time.sleep(API_PAUSE_SECONDS)

        news_items = fetch_company_news(symbol, news_from, news_to)
        time.sleep(API_PAUSE_SECONDS)

        candle_metrics = extract_candle_metrics(candles)
        result = build_result(item, quote, candle_metrics, news_items)
        results.append(result)

    except HTTPError as e:
        errors.append({'symbol': symbol, 'type': 'HTTPError', 'status': e.code, 'message': str(e)})
    except URLError as e:
        errors.append({'symbol': symbol, 'type': 'URLError', 'message': str(e)})
    except Exception as e:
        errors.append({'symbol': symbol, 'type': 'Exception', 'message': str(e)})

payload = {
    'updatedAt': int(time.time()),
    'source': 'finnhub',
    'ruleVersion': 'v3-helper-functions',
    'settings': {
        'resolution': RESOLUTION,
        'candleLookbackDays': CANDLE_LOOKBACK_DAYS,
        'newsLookbackDays': NEWS_LOOKBACK_DAYS,
        'liquidityThresholdUsd': LIQUIDITY_THRESHOLD_USD,
        'volumeSpikeMultiplier': VOLUME_SPIKE_MULTIPLIER,
        'breakoutWindow': BREAKOUT_WINDOW,
    },
    'items': results,
    'errors': errors,
}

DATA_DIR.mkdir(parents=True, exist_ok=True)
with QUOTES_FILE.open('w', encoding='utf-8') as f:
    json.dump(payload, f, indent=2)

print(f'Wrote {len(results)} quotes to {QUOTES_FILE}')
if errors:
    print(f'Encountered {len(errors)} errors')


if __name__ == '__main__':
    main()