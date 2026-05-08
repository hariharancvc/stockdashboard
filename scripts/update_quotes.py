import json
import os
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / 'data'
SYMBOLS_FILE = DATA_DIR / 'symbols.json'
QUOTES_FILE = DATA_DIR / 'quotes.json'
API_KEY = os.getenv('FINNHUB_API_KEY')

if not API_KEY:
    raise RuntimeError('FINNHUB_API_KEY is not set')

if not SYMBOLS_FILE.exists():
    raise FileNotFoundError(f'Missing symbols file: {SYMBOLS_FILE}')

with SYMBOLS_FILE.open('r', encoding='utf-8') as f:
    symbols = json.load(f)

results = []
errors = []

for item in symbols:
    symbol = item.get('finnhubSymbol')
    if not symbol:
        continue

    url = f'https://finnhub.io/api/v1/quote?symbol={symbol}&token={API_KEY}'
    req = Request(url, headers={'User-Agent': 'Mozilla/5.0'})

    try:
        with urlopen(req, timeout=20) as response:
            data = json.loads(response.read().decode('utf-8'))

        results.append({
            'company': item.get('company'),
            'ticker': item.get('ticker'),
            'finnhubSymbol': symbol,
            'column': item.get('column'),
            'currentPrice': data.get('c'),
            'change': data.get('d'),
            'percentChange': data.get('dp'),
            'high': data.get('h'),
            'low': data.get('l'),
            'open': data.get('o'),
            'prevClose': data.get('pc'),
            'timestamp': data.get('t')
        })
    except HTTPError as e:
        errors.append({'symbol': symbol, 'type': 'HTTPError', 'status': e.code, 'message': str(e)})
    except URLError as e:
        errors.append({'symbol': symbol, 'type': 'URLError', 'message': str(e)})
    except Exception as e:
        errors.append({'symbol': symbol, 'type': 'Exception', 'message': str(e)})

    time.sleep(1)

payload = {
    'updatedAt': int(time.time()),
    'source': 'finnhub',
    'items': results,
    'errors': errors
}

DATA_DIR.mkdir(parents=True, exist_ok=True)
with QUOTES_FILE.open('w', encoding='utf-8') as f:
    json.dump(payload, f, indent=2)

print(f'Wrote {len(results)} quotes to {QUOTES_FILE}')
if errors:
    print(f'Encountered {len(errors)} errors')
