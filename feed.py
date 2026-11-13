"""Free market data for WATCHING only (Nitin's rule G20: screening and first checks may use free/NSE data; every number
behind the final instruction comes from INDmoney, which the Claude 360-degree check reads live).

Main feed: Yahoo Finance chart API (NSE symbols as SYMBOL.NS, Nifty 50 = ^NSEI), live price and daily/hourly
candles. Second, independent source used to rule out a bad tick before an instant message: TradingView's scanner. The INDstocks login is NOT used here: INDstocks
keeps one live token per account and the Trade Watch jobs already share it."""
import datetime as dt
import http.cookiejar as http_cookiejar
import json
import time
import urllib.error
import urllib.parse
import urllib.request

import net

IST = dt.timezone(dt.timedelta(minutes=330))
INDEX_YAHOO = {"NIFTY": "^NSEI", "NIFTY50": "^NSEI", "BANKNIFTY": "^NSEBANK", "FINNIFTY": "NIFTY_FIN_SERVICE.NS",
               "SENSEX": "^BSESN", "INDIAVIX": "^INDIAVIX", "MIDCPNIFTY": "NIFTY_MID_SELECT.NS"}


def yahoo_symbol(item_or_symbol):
    if isinstance(item_or_symbol, dict):
        if item_or_symbol.get("yahoo"):
            return item_or_symbol["yahoo"]
        s = item_or_symbol["symbol"]
    else:
        s = item_or_symbol
    s = s.strip().upper()
    return INDEX_YAHOO.get(s.replace(" ", ""), s + ".NS")


class Feed:
    """Yahoo needs a session cookie and a 'crumb' when called from GitHub's servers (tested 13 Nov 2026: plain calls
    get HTTP 429). TradingView's public scanner is the second, independent source (15 minutes delayed - used only to
    rule out a bad tick, never as the price shown)."""

    def __init__(self, http=None, sleep=time.sleep):
        self.sleep = sleep
        self.cj = http_cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))
        self.crumb = None
        self.n = 0
        self.errors = 0

    def _get(self, url, data=None, headers=None, timeout=25):
        net.guard("POST" if data else "GET", url)
        h = {"User-Agent": net.UA, "Accept": "*/*", "Accept-Language": "en-IN,en;q=0.9"}
        h.update(headers or {})
        req = urllib.request.Request(url, data=data, headers=h, method="POST" if data else "GET")
        try:
            with self.op.open(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            raise net.HttpError(e.code, e.read()[:120].decode("utf-8", "replace"))
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            raise net.HttpError(0, str(e)[:100])

    def _new_crumb(self):
        try:
            self._get("https://fc.yahoo.com/")
        except net.HttpError:
            pass  # this page answers 404 but sets the session cookie
        self.crumb = self._get("https://query2.finance.yahoo.com/v1/test/getcrumb").decode().strip()

    def chart(self, ysym, rng="1d", interval="1m"):
        """-> {price, time (epoch), prev_close, candles: [(epoch, o, h, l, c, v)], age_s}"""
        for attempt in range(3):
            try:
                if not self.crumb:
                    self._new_crumb()
                host = "query1" if self.n % 2 == 0 else "query2"
                self.n += 1
                url = (f"https://{host}.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ysym, safe='')}"
                       f"?range={rng}&interval={interval}&includePrePost=false&crumb={urllib.parse.quote(self.crumb)}")
                j = json.loads(self._get(url).decode())
                break
            except net.HttpError as e:
                if e.status in (401, 403, 429) and attempt < 2:
                    self.crumb = None
                    self.sleep(3 * (attempt + 1))
                    continue
                self.errors += 1
                raise
        res = (j.get("chart") or {}).get("result") or []
        if not res:
            raise net.HttpError(404, "no data")
        r = res[0]
        meta = r.get("meta") or {}
        ts = r.get("timestamp") or []
        q = ((r.get("indicators") or {}).get("quote") or [{}])[0]
        cs = []
        for i, t in enumerate(ts):
            try:
                o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
                v = (q.get("volume") or [0] * len(ts))[i] or 0
            except (KeyError, IndexError, TypeError):
                continue
            if None in (o, h, l, c):
                continue
            cs.append((int(t), float(o), float(h), float(l), float(c), float(v)))
        price = meta.get("regularMarketPrice")
        when = meta.get("regularMarketTime") or (cs[-1][0] if cs else None)
        return {"price": float(price) if price is not None else (cs[-1][4] if cs else None),
                "time": int(when) if when else None,
                "prev_close": meta.get("chartPreviousClose") or meta.get("previousClose"),
                "candles": cs,
                "age_s": (time.time() - int(when)) if when else None}

    def second(self, tvsym):
        """TradingView's public scanner (15 minutes delayed): {price, time}. A sanity check only."""
        body = json.dumps({"symbols": {"tickers": [tvsym], "query": {"types": []}}, "columns": ["close"]}).encode()
        j = json.loads(self._get("https://scanner.tradingview.com/india/scan", data=body,
                                 headers={"Content-Type": "application/json"}).decode())
        data = j.get("data") or []
        if not data or not data[0].get("d"):
            raise net.HttpError(404, "no data")
        return {"price": float(data[0]["d"][0]), "time": None}


def tv_symbol(item_or_symbol):
    if isinstance(item_or_symbol, dict):
        if item_or_symbol.get("tv"):
            return item_or_symbol["tv"]
        s = item_or_symbol["symbol"]
    else:
        s = item_or_symbol
    s = s.strip().upper()
    return {"NIFTY": "NSE:NIFTY", "NIFTY50": "NSE:NIFTY", "BANKNIFTY": "NSE:BANKNIFTY"}.get(s, "NSE:" + s.replace("&", "_"))


def day_of(epoch):
    return dt.datetime.fromtimestamp(epoch, IST).date()


def hm(epoch):
    return dt.datetime.fromtimestamp(epoch, IST).strftime("%H:%M") if epoch else "?"
