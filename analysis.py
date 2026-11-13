"""Chart reading for a tracked stock with the Stock Deep Check / Trade Analyzer logic (dc_core.py), on three time
frames - weekly, daily and hourly - so higher-time-frame lines also show on the lower charts (Nitin, 9 Nov 2026).
Lines are found on COMPLETED candles only (rule R5); indicator values 'now' include today's live candle."""
import datetime as dt

import numpy as np
import pandas as pd

import dc_core as C

IST = dt.timezone(dt.timedelta(minutes=330))


def frame(candles):
    """[(epoch, o, h, l, c, v)] -> DataFrame date/open/high/low/close/volume (IST, no time zone)."""
    if not candles:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
    d = pd.DataFrame(candles, columns=["t", "open", "high", "low", "close", "volume"])
    d["date"] = pd.to_datetime(d.t, unit="s", utc=True).dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
    return d.drop(columns="t").sort_values("date").reset_index(drop=True)


def read(d, look=260):
    """Lines and levels of one time frame. d must hold completed candles."""
    out = {"d": d, "lines": [], "levels": [], "floor": None, "ceiling": None, "decision": []}
    if len(d) < 30:
        return out
    d = C.indicators(d)
    out["d"] = d
    ph, pl = C.swings(d, 3, look)
    out["lines"] = C.trendlines(d, ph, pl)
    out["levels"] = C.horizontals(d, ph, pl)
    out["floor"], out["ceiling"] = C.flat_zone(d, side="low"), C.flat_zone(d, side="high")
    extra = ([{"price": out["floor"]["lo"], "role": "floor"}] if out["floor"] else []) + \
            ([{"price": out["ceiling"]["hi"], "role": "ceiling"}] if out["ceiling"] else [])
    out["decision"] = C.cross_points(out["lines"], out["levels"] + extra, d)
    try:
        out["div"] = C.divergences(d) if len(d) > 40 else {}
        out["candles"] = C.candles(d)
    except Exception:
        out["div"], out["candles"] = {}, []
    return out


def analyse(daily_c, hourly_c, price, today):
    """daily_c / hourly_c = Yahoo candles. Returns facts for the message and the picture."""
    dall = frame(daily_c)
    done = dall[dall.date.dt.date < today].reset_index(drop=True) if len(dall) else dall
    f = {"price": price}
    if len(done) < 30:
        f["daily"], f["weekly"], f["hourly"] = read(done), read(done.iloc[0:0]), read(frame([]))
        return f
    live = done.copy()
    live.loc[len(live)] = {"date": pd.Timestamp(today), "open": live.close.iloc[-1], "high": max(price, live.close.iloc[-1]),
                           "low": min(price, live.close.iloc[-1]), "close": price, "volume": float("nan")}
    li = C.indicators(live)
    t = li.iloc[-1]
    f.update(rsi=float(t.rsi), ma20=float(t.ma20), ma50=float(t.ma50) if not np.isnan(t.ma50) else None,
             ma200=float(t.ma200) if not np.isnan(t.ma200) else None, atr=float(li.atr.iloc[-2]),
             prev_close=float(done.close.iloc[-1]), hi52=float(done.high.iloc[-250:].max()),
             lo52=float(done.low.iloc[-250:].min()))
    f["daily"] = read(done)
    wk = C.weekly(done)
    f["weekly"] = read(wk[["date", "open", "high", "low", "close", "volume"]], look=156)
    hd = frame(hourly_c)
    if len(hd):
        hd = hd[hd.date < pd.Timestamp(dt.datetime.now(IST).replace(tzinfo=None) - dt.timedelta(minutes=60))]
    f["hourly"] = read(hd.reset_index(drop=True), look=150) if len(hd) >= 30 else {"d": hd, "lines": [], "levels": [],
                                                                                    "floor": None, "ceiling": None,
                                                                                    "decision": []}
    f["hourly_all"] = frame(hourly_c)
    return f


def nearest(levels, price, side):
    xs = [x for x in levels if (x["price"] < price if side == "below" else x["price"] >= price)]
    if not xs:
        return None
    return max(xs, key=lambda x: x["price"]) if side == "below" else min(xs, key=lambda x: x["price"])


def line_now(ln, d, when=None):
    """Value of a trendline at the last bar (or projected `when` bars later)."""
    n = len(d) - 1 + (when or 0)
    return ln["p0"] + ln["slope"] * (n - ln["i0"])


def summary(f):
    """Short plain facts for the Slack text."""
    p = f["price"]
    out = []
    if f.get("prev_close"):
        out.append(f"today {(p / f['prev_close'] - 1) * 100:+.1f}%")
    if f.get("rsi") is not None and not np.isnan(f["rsi"]):
        out.append(f"RSI {f['rsi']:.0f}")
    if f.get("ma200"):
        out.append(f"{'above' if p >= f['ma200'] else 'below'} 200-day avg ₹{f['ma200']:,.2f}")
    lv = (f.get("daily") or {}).get("levels") or []
    s, r = nearest(lv, p, "below"), nearest(lv, p, "above")
    sr = []
    if s:
        sr.append(f"support ₹{s['price']:,.2f} ({s['touches']} touches)")
    if r:
        sr.append(f"resistance ₹{r['price']:,.2f} ({r['touches']} touches)")
    for ln in (f.get("daily") or {}).get("lines") or []:
        sr.append(f"{'rising' if ln['kind'] == 'up' else 'falling'} line ₹{ln['today']:,.2f} ({ln['n']} touches)")
    dps = (f.get("daily") or {}).get("decision") or []
    if dps:
        dp = dps[0]
        sr.append(f"decision point ₹{dp['level']:,.2f} in {max(0, dp['bars_ahead']):.0f} days")
    return " · ".join(out), " · ".join(sr)
