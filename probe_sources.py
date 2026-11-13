"""One-off check: which free price sources answer from GitHub's servers? Public symbols only, prints status only."""
import json
import re
import time
import urllib.parse
import urllib.request
import http.cookiejar

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


def opener():
    cj = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj)), cj


def get(op, url, data=None, headers=None, timeout=20):
    h = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "en-IN,en;q=0.9"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h, method="POST" if data else "GET")
    with op.open(req, timeout=timeout) as r:
        return r.status, r.read()


def run(name, fn):
    t = time.time()
    try:
        out = fn()
        print(f"OK   {name}: {out} ({time.time() - t:.1f}s)")
    except Exception as e:
        print(f"FAIL {name}: {type(e).__name__} {str(e)[:90]}")


def yahoo_crumb():
    op, cj = opener()
    try:
        get(op, "https://fc.yahoo.com")
    except Exception:
        pass
    _, crumb = get(op, "https://query2.finance.yahoo.com/v1/test/getcrumb")
    crumb = crumb.decode()
    _, b = get(op, "https://query2.finance.yahoo.com/v8/finance/chart/RELIANCE.NS?range=1d&interval=5m&crumb=" + urllib.parse.quote(crumb))
    j = json.loads(b)
    m = j["chart"]["result"][0]["meta"]
    return f"price {m.get('regularMarketPrice')} age {round((time.time() - m.get('regularMarketTime', 0)) / 60)} min"


def yahoo_daily_crumb():
    op, cj = opener()
    try:
        get(op, "https://fc.yahoo.com")
    except Exception:
        pass
    _, crumb = get(op, "https://query2.finance.yahoo.com/v1/test/getcrumb")
    _, b = get(op, "https://query1.finance.yahoo.com/v8/finance/chart/RELIANCE.NS?range=2y&interval=1d&crumb=" + urllib.parse.quote(crumb.decode()))
    return f"{len(json.loads(b)['chart']['result'][0]['timestamp'])} daily candles"


def tradingview():
    op, _ = opener()
    body = json.dumps({"symbols": {"tickers": ["NSE:RELIANCE", "NSE:NIFTY", "NSE:IRFC"], "query": {"types": []}},
                       "columns": ["close", "change", "high", "low", "volume", "update_mode"]}).encode()
    _, b = get(op, "https://scanner.tradingview.com/india/scan", data=body, headers={"Content-Type": "application/json"})
    j = json.loads(b)
    return "; ".join(f"{d['s']} {d['d']}" for d in j.get("data", []))


def nse_api():
    op, _ = opener()
    get(op, "https://www.nseindia.com/")
    _, b = get(op, "https://www.nseindia.com/api/quote-equity?symbol=RELIANCE", headers={"Referer": "https://www.nseindia.com/"})
    return f"lastPrice {json.loads(b)['priceInfo']['lastPrice']}"


def nse_chart():
    op, _ = opener()
    get(op, "https://www.nseindia.com/")
    _, b = get(op, "https://www.nseindia.com/api/chart-databyindex?index=RELIANCEEQN", headers={"Referer": "https://www.nseindia.com/"})
    return f"{len(json.loads(b).get('grapthData', []))} intraday points"


def nse_archive():
    op, _ = opener()
    _, b = get(op, "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_12112026.csv")
    return f"{len(b)} bytes, {b[:60]!r}"


def moneycontrol():
    op, _ = opener()
    _, b = get(op, "https://priceapi.moneycontrol.com/pricefeed/nse/equitycash/RI")
    d = json.loads(b)["data"]
    return f"price {d.get('pricecurrent')} time {d.get('lastupd')}"


def google_consent():
    op, _ = opener()
    _, b = get(op, "https://www.google.com/finance/quote/RELIANCE:NSE?hl=en&gl=in",
               headers={"Cookie": "CONSENT=YES+cb; SOCS=CAESEwgDEgk0ODE3Nzk3MjQaAmVuIAEaBgiA_LyaBg"})
    h = b.decode("utf-8", "replace")
    m = re.search(r'data-last-price="([0-9.]+)"', h)
    return f"price {m.group(1)}" if m else f"no price; page starts {h[:80]!r}"


def stooq():
    op, _ = opener()
    _, b = get(op, "https://stooq.com/q/l/?s=reliance.in&f=sd2t2ohlcv&h&e=csv")
    return b.decode()[:120]


for n, f in (("Yahoo chart with crumb", yahoo_crumb), ("Yahoo daily 2y with crumb", yahoo_daily_crumb),
             ("TradingView scanner", tradingview), ("NSE quote API", nse_api), ("NSE intraday chart API", nse_chart),
             ("NSE archive bhavcopy", nse_archive), ("Moneycontrol price API", moneycontrol),
             ("Google Finance with consent", google_consent), ("Stooq", stooq)):
    run(n, f)
