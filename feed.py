"""Free market data for WATCHING only (Nitin's rule G20: screening and first checks may use free/NSE data; every number
behind the final instruction comes from INDmoney, which the Claude 360-degree check reads live).

Main feed: Yahoo Finance chart API (NSE symbols as SYMBOL.NS, Nifty 50 = ^NSEI). Second, independent source used to
confirm a hit before anyone is tagged: Google Finance's quote page. The INDstocks login is NOT used here: INDstocks
keeps one live token per account and the Trade Watch jobs already share it."""
import datetime as dt
import re
import time
import urllib.parse

import net

IST = dt.timezone(dt.timedelta(minutes=330))
INDEX_YAHOO = {"NIFTY": "^NSEI", "NIFTY50": "^NSEI", "BANKNIFTY": "^NSEBANK", "FINNIFTY": "NIFTY_FIN_SERVICE.NS",
               "SENSEX": "^BSESN", "INDIAVIX": "^INDIAVIX", "MIDCPNIFTY": "NIFTY_MID_SELECT.NS"}
INDEX_GOOGLE = {"NIFTY": "NIFTY_50:INDEXNSE", "NIFTY50": "NIFTY_50:INDEXNSE", "BANKNIFTY": "NIFTY_BANK:INDEXNSE",
                "SENSEX": "SENSEX:INDEXBOM"}


def yahoo_symbol(item_or_symbol):
    if isinstance(item_or_symbol, dict):
        if item_or_symbol.get("yahoo"):
            return item_or_symbol["yahoo"]
        s = item_or_symbol["symbol"]
    else:
        s = item_or_symbol
    s = s.strip().upper()
    return INDEX_YAHOO.get(s.replace(" ", ""), s + ".NS")


def google_symbol(item_or_symbol):
    if isinstance(item_or_symbol, dict):
        if item_or_symbol.get("google"):
            return item_or_symbol["google"]
        s = item_or_symbol["symbol"]
    else:
        s = item_or_symbol
    s = s.strip().upper()
    return INDEX_GOOGLE.get(s.replace(" ", ""), s + ":NSE")


class Feed:
    def __init__(self, http=net.request, sleep=time.sleep):
        self.http, self.sleep = http, sleep
        self.n = 0
        self.errors = 0

    def chart(self, ysym, rng="1d", interval="1m"):
        """-> {price, time (epoch), prev_close, candles: [(epoch, o, h, l, c, v)], age_s}"""
        host = "query1" if self.n % 2 == 0 else "query2"
        self.n += 1
        url = (f"https://{host}.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ysym, safe='')}"
               f"?range={rng}&interval={interval}&includePrePost=false&events=div%2Csplit")
        try:
            j = net.retry(lambda: self.http("GET", url), tries=2, wait=3)
        except Exception:
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

    def google(self, gsym):
        """-> {price, time} from Google Finance's quote page (an independent check)."""
        url = f"https://www.google.com/finance/quote/{urllib.parse.quote(gsym, safe=':_')}?hl=en"
        html = net.retry(lambda: self.http("GET", url, as_json=False), tries=2, wait=2).decode("utf-8", "replace")
        m = re.search(r'data-last-price="([0-9.]+)"', html)
        if not m:
            raise net.HttpError(0, "no price on page")
        t = re.search(r'data-last-normal-market-timestamp="([0-9]+)"', html)
        return {"price": float(m.group(1)), "time": int(t.group(1)) if t else None}


def day_of(epoch):
    return dt.datetime.fromtimestamp(epoch, IST).date()


def hm(epoch):
    return dt.datetime.fromtimestamp(epoch, IST).strftime("%H:%M") if epoch else "?"
