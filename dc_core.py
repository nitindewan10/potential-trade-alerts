"""Copy of deep_check/core.py from the Stock Deep Check (Trade Analyzer logic), unchanged, so the tracker draws
the same lines: trendlines need 3+ touches within 1%, 5+ bars apart, no close more than 1% through the line;
floors/ceilings, decision points (a trendline meeting a horizontal level), divergences and candle names."""
import numpy as np
import pandas as pd

# ---------------------------------------------------------------- indicators

def wilder(s, n):
    return s.ewm(alpha=1 / n, adjust=False).mean()


def indicators(d):
    """d: DataFrame with date, open, high, low, close, volume (oldest first). Adds indicator columns in place."""
    d = d.sort_values("date").reset_index(drop=True)
    c, h, l, o, v = d.close, d.high, d.low, d.open, d.volume.astype(float)
    dl = c.diff()
    up, dn = wilder(dl.clip(lower=0), 14), wilder((-dl).clip(lower=0), 14)
    d["rsi"] = 100 - 100 / (1 + up / dn)
    e12, e26 = c.ewm(span=12, adjust=False).mean(), c.ewm(span=26, adjust=False).mean()
    d["macd"] = e12 - e26
    d["sig"] = d.macd.ewm(span=9, adjust=False).mean()
    d["mh"] = d.macd - d.sig
    m, sd = c.rolling(20).mean(), c.rolling(20).std(ddof=0)
    d["bbm"], d["bbu"], d["bbl"] = m, m + 2 * sd, m - 2 * sd
    d["pb"] = (c - d.bbl) / (d.bbu - d.bbl)
    d["bw"] = (d.bbu - d.bbl) / m
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    d["atr"] = wilder(tr, 14)
    upm, dnm = h.diff(), -l.diff()
    pdm = pd.Series(np.where((upm > dnm) & (upm > 0), upm, 0.0), index=d.index)
    ndm = pd.Series(np.where((dnm > upm) & (dnm > 0), dnm, 0.0), index=d.index)
    d["pdi"], d["ndi"] = 100 * wilder(pdm, 14) / d.atr, 100 * wilder(ndm, 14) / d.atr
    dx = 100 * (d.pdi - d.ndi).abs() / (d.pdi + d.ndi)
    d["adx"] = wilder(dx, 14)
    ll, hh = l.rolling(14).min(), h.rolling(14).max()
    d["k"] = (100 * (c - ll) / (hh - ll)).rolling(3).mean()
    d["dd"] = d.k.rolling(3).mean()
    tp = (h + l + c) / 3
    mf = tp * v
    pos, neg = mf.where(tp > tp.shift(), 0), mf.where(tp < tp.shift(), 0)
    d["mfi"] = 100 - 100 / (1 + pos.rolling(14).sum() / neg.rolling(14).sum())
    d["obv"] = (np.sign(c.diff()).fillna(0) * v).cumsum()
    d["v20"] = v.rolling(20).mean()
    d["vr"] = v / d.v20
    for n in (20, 50, 100, 200):
        d[f"ma{n}"] = c.rolling(n).mean()
    rng = (h - l).replace(0, np.nan)
    d["body"] = (c - o).abs() / rng
    d["lw"] = (np.minimum(o, c) - l) / rng
    d["uw"] = (h - np.maximum(o, c)) / rng
    return d


def weekly(d):
    w = d.set_index("date").resample("W-FRI").agg({"open": "first", "high": "max", "low": "min", "close": "last",
                                                   "volume": "sum"}).dropna().reset_index()
    return indicators(w)


# ---------------------------------------------------------------- swing points and lines

def swings(d, k=3, look=260):
    hi, lo, N = d.high.values, d.low.values, len(d)
    s = max(k, N - look)
    ph = [i for i in range(s, N - k) if hi[i] == hi[i - k:i + k + 1].max()]
    pl = [i for i in range(s, N - k) if lo[i] == lo[i - k:i + k + 1].min()]
    for i in range(max(s, N - k), N):  # the last bars count when they are the extreme of the bars since
        if lo[i] == lo[i - k:N].min():
            pl.append(i)
        if hi[i] == hi[i - k:N].max():
            ph.append(i)
    return sorted(set(ph)), sorted(set(pl))


def trendlines(d, ph, pl, tol=0.01, gap=5, horizon=19):
    """Falling lines on swing highs and rising lines on swing lows with 3+ touches (Nitin's rule)."""
    hi, lo, cl, N = d.high.values, d.low.values, d.close.values, len(d)
    out = []
    for kind, xs, ys in (("down", ph, hi), ("up", pl, lo)):
        best = None
        for ai in range(len(xs)):
            for bi in range(ai + 1, len(xs)):
                i, j = xs[ai], xs[bi]
                slope = (ys[j] - ys[i]) / (j - i)
                if (kind == "down" and slope >= 0) or (kind == "up" and slope <= 0):
                    continue
                line = lambda t: ys[i] + slope * (t - i)
                touches = []
                for t in xs:
                    if t >= i and abs(ys[t] - line(t)) <= tol * line(t) and (not touches or t - touches[-1] >= gap):
                        touches.append(t)
                if len(touches) < 3:
                    continue
                ok = all(not (kind == "down" and cl[t] > line(t) * (1 + tol)) and
                         not (kind == "up" and cl[t] < line(t) * (1 - tol)) for t in range(i, N))
                if not ok:
                    continue
                cand = (len(touches), touches[-1], i, j, slope, touches)
                if best is None or cand[:2] > best[:2]:
                    best = cand
        if best:
            n, last, i, j, slope, touches = best
            # refit through the first and last touch (the drawn line)
            a, b = touches[0], touches[-1]
            slope = (ys[b] - ys[a]) / (b - a)
            out.append({"kind": kind, "touches": [(str(d.date[t].date()), round(float(ys[t]), 2)) for t in touches],
                        "i0": int(a), "p0": float(ys[a]), "slope": float(slope),
                        "today": float(ys[a] + slope * (N - 1 - a)), "ahead": float(ys[a] + slope * (N - 1 + horizon - a)),
                        "n": int(n)})
    return out


def horizontals(d, ph, pl, tol=0.01, near=0.25):
    """Price levels where 2+ swing highs/lows cluster within 1% (3+ = strong), within ±25% of the last close."""
    pts = [(float(d.low[i]), "L", i) for i in pl] + [(float(d.high[i]), "H", i) for i in ph]
    c = float(d.close.iloc[-1])
    seen, out = set(), []
    for p, _, _ in sorted(pts):
        if any(abs(p - q) <= tol * q for q in seen):
            continue
        grp = [q for q in pts if abs(q[0] - p) <= tol * p]
        if len(grp) >= 2 and abs(p / c - 1) <= near:
            lvl = float(np.mean([g[0] for g in grp]))
            seen.add(lvl)
            out.append({"price": round(lvl, 2), "lo": round(min(g[0] for g in grp), 2), "hi": round(max(g[0] for g in grp), 2),
                        "touches": len(grp), "dates": sorted({str(d.date[g[2]].date()) for g in grp}),
                        "role": "support" if lvl < c else "resistance"})
    return out


def flat_zone(d, look=30, tol=0.015, side="low"):
    """A floor (or ceiling): the price came back to within 1.5% of the lowest low (highest high) of the last 30 bars
    on 2+ separate visits (a visit = a run of consecutive days). 3+ visits = a strong floor."""
    x = (d.low if side == "low" else d.high).values[-look:]
    m = x.min() if side == "low" else x.max()
    near = [q for q in range(len(x)) if (x[q] <= m * (1 + tol) if side == "low" else x[q] >= m * (1 - tol))]
    visits = []
    for q in near:
        if visits and q - visits[-1][-1] == 1:
            visits[-1].append(q)
        else:
            visits.append([q])
    if len(visits) < 2:
        return None
    base = len(d) - len(x)
    dates = [str(d.date.iloc[base + q].date()) for q in near]
    vals = [round(float(x[q]), 2) for q in near]
    return {"tests": len(visits), "days": len(near), "dates": dates, "values": vals,
            "lo": round(float(min(vals)), 2), "hi": round(float(max(vals)), 2)}


def cross_points(lines, levels, d, horizon=40):
    """Nitin's decision points: where a rising or falling trendline meets a horizontal level in the next bars."""
    out, N = [], len(d)
    for ln in lines:
        for lv in levels:
            p = lv["price"]
            if ln["slope"] == 0:
                continue
            t = ln["i0"] + (p - ln["p0"]) / ln["slope"]
            ahead = t - (N - 1)
            if -5 <= ahead <= horizon:
                out.append({"line": ln["kind"], "level": p, "bars_ahead": round(float(ahead), 1),
                            "role": lv.get("role", "")})
    return sorted(out, key=lambda r: r["bars_ahead"])


# ---------------------------------------------------------------- divergences and candles

def divergences(d, back=(4, 30)):
    """Bullish: price at a new low vs the lowest low 4–30 bars back, while RSI / MACD histogram / OBV are higher.
    Bearish: the mirror at a new high. Also lists the rising RSI lows at the last three swing lows."""
    N = len(d)
    a, b = N - 1 - back[1], N - 1 - back[0]
    res = {}
    win = d.iloc[a:b]
    jl, jh = win.low.idxmin(), win.high.idxmax()
    lo_now, hi_now = d.low.iloc[-5:].min(), d.high.iloc[-5:].max()
    tl, th = d.low.iloc[-5:].idxmin(), d.high.iloc[-5:].idxmax()
    if lo_now < d.low[jl]:
        res["bull_rsi"] = bool(d.rsi[jl] <= d.rsi[tl] - 3)
        res["bull_macd"] = bool(d.mh[tl] > d.mh[jl])
        res["bull_obv"] = bool(d.obv[tl] > d.obv[jl])
        res["bull_ref"] = {"then": str(d.date[jl].date()), "now": str(d.date[tl].date()), "price": [round(d.low[jl], 2), round(lo_now, 2)],
                           "rsi": [round(d.rsi[jl], 1), round(d.rsi[tl], 1)], "mh": [round(d.mh[jl], 3), round(d.mh[tl], 3)]}
    if hi_now > d.high[jh]:
        res["bear_rsi"] = bool(d.rsi[jh] >= d.rsi[th] + 3)
        res["bear_macd"] = bool(d.mh[th] < d.mh[jh])
        res["bear_obv"] = bool(d.obv[th] < d.obv[jh])
        res["bear_ref"] = {"then": str(d.date[jh].date()), "now": str(d.date[th].date()), "price": [round(d.high[jh], 2), round(hi_now, 2)],
                           "rsi": [round(d.rsi[jh], 1), round(d.rsi[th], 1)], "mh": [round(d.mh[jh], 3), round(d.mh[th], 3)]}
    return res


def rsi_lows_chain(d, pl, n=3):
    """The last n swing lows with RSI: a rising RSI on falling price lows is the classic multi-point divergence."""
    pts = [i for i in pl if not np.isnan(d.rsi[i])][-n:]
    return [{"date": str(d.date[i].date()), "low": round(float(d.low[i]), 2), "rsi": round(float(d.rsi[i]), 1),
             "mh": round(float(d.mh[i]), 3)} for i in pts]


def candles(d):
    """Named candle patterns on the last 1–3 bars, with the price that would confirm them."""
    out = []
    t = d.iloc[-1]
    p1 = d.iloc[-2] if len(d) > 1 else t
    p2 = d.iloc[-3] if len(d) > 2 else p1
    rng = t.high - t.low
    down_trend = t.close < t.ma20 if not np.isnan(t.ma20) else False
    if t.body <= 0.15 and t.lw >= 0.3 and t.uw >= 0.3:
        out.append({"name": "Long-legged doji", "read": "undecided", "confirm_up": round(t.high, 2), "confirm_down": round(t.low, 2)})
    elif t.body <= 0.10:
        out.append({"name": "Doji", "read": "undecided", "confirm_up": round(t.high, 2), "confirm_down": round(t.low, 2)})
    if t.lw >= 0.55 and t.body <= 0.35 and t.uw <= 0.15:
        out.append({"name": "Hammer" if down_trend else "Hanging man", "read": "bullish" if down_trend else "bearish",
                    "confirm_up": round(t.high, 2), "confirm_down": round(t.low, 2)})
    if t.uw >= 0.55 and t.body <= 0.35 and t.lw <= 0.15:
        out.append({"name": "Shooting star" if not down_trend else "Inverted hammer",
                    "read": "bearish" if not down_trend else "bullish", "confirm_up": round(t.high, 2), "confirm_down": round(t.low, 2)})
    if t.body >= 0.85:
        out.append({"name": "Marubozu (" + ("up" if t.close > t.open else "down") + ")", "read": "bullish" if t.close > t.open else "bearish"})
    if t.close > t.open and p1.close < p1.open and t.close >= p1.open and t.open <= p1.close:
        out.append({"name": "Bullish engulfing", "read": "bullish", "confirm_down": round(t.low, 2)})
    if t.close < t.open and p1.close > p1.open and t.open >= p1.close and t.close <= p1.open:
        out.append({"name": "Bearish engulfing", "read": "bearish", "confirm_up": round(t.high, 2)})
    mid2 = (p2.open + p2.close) / 2
    if p2.close < p2.open and p2.body >= 0.6 and p1.body <= 0.3 and t.close > t.open and t.close > mid2:
        out.append({"name": "Morning star", "read": "bullish"})
    if p2.close > p2.open and p2.body >= 0.6 and p1.body <= 0.3 and t.close < t.open and t.close < mid2:
        out.append({"name": "Evening star", "read": "bearish"})
    # setup: a big red candle then a small body = a possible morning star if the next close beats the red body's middle
    if p1.close < p1.open and p1.body >= 0.6 and t.body <= 0.3:
        out.append({"name": "Possible morning star (needs the next candle)", "read": "watch",
                    "confirm_up": round((p1.open + p1.close) / 2, 2)})
    return out


# ---------------------------------------------------------------- pivots, Fibonacci, volume

def pivots(h, l, c):
    p = (h + l + c) / 3
    return {"P": p, "R1": 2 * p - l, "R2": p + (h - l), "S1": 2 * p - h, "S2": p - (h - l)}


def pivot_sets(d):
    t = d.iloc[-1]
    out = {"daily": pivots(t.high, t.low, t.close)}
    x = d.set_index("date")
    last = x.index[-1]
    wk = x[x.index.to_period("W-FRI") < last.to_period("W-FRI")]
    if len(wk):
        w = wk[wk.index.to_period("W-FRI") == wk.index[-1].to_period("W-FRI")]
        out["weekly"] = pivots(w.high.max(), w.low.min(), w.close.iloc[-1])
    mo = x[x.index.to_period("M") < last.to_period("M")]
    if len(mo):
        m = mo[mo.index.to_period("M") == mo.index[-1].to_period("M")]
        out["monthly"] = pivots(m.high.max(), m.low.min(), m.close.iloc[-1])
    return {k: {kk: round(float(vv), 2) for kk, vv in v.items()} for k, v in out.items()}


def fibs(d, long_hl=None):
    """52-week swing retracements, plus the long-term rally retracement when long-term highs/lows are given.
    long_hl: DataFrame of monthly (or weekly) date, high, low for many years."""
    y = d[d.date >= d.date.iloc[-1] - pd.Timedelta(days=365)]
    hi, lo = float(y.high.max()), float(y.low.min())
    hid, lod = y.date[y.high.idxmax()], y.date[y.low.idxmin()]
    out = {"52w": {"high": round(hi, 2), "high_date": str(hid.date()), "low": round(lo, 2), "low_date": str(lod.date())}}
    if hid < lod:  # a fall: retracements up from the low
        out["52w"]["dir"] = "fall"
        out["52w"]["levels"] = {f"{r:.1%}": round(lo + r * (hi - lo), 2) for r in (0.236, 0.382, 0.5, 0.618)}
    else:
        out["52w"]["dir"] = "rise"
        out["52w"]["levels"] = {f"{r:.1%}": round(hi - r * (hi - lo), 2) for r in (0.236, 0.382, 0.5, 0.618)}
    if long_hl is not None and len(long_hl) > 24:
        L = long_hl.reset_index(drop=True)
        ia = int(L.high.idxmax())
        ath, athd = float(L.high[ia]), L.date[ia]
        pre = L[(L.date >= athd - pd.Timedelta(days=730)) & (L.date <= athd)]
        jl = int(pre.low.idxmin())
        base, based = float(L.low[jl]), L.date[jl]
        out["long"] = {"low": round(base, 2), "low_date": str(pd.Timestamp(based).date()), "high": round(ath, 2),
                       "high_date": str(pd.Timestamp(athd).date()),
                       "levels": {f"{r:.1%}": round(ath - r * (ath - base), 2) for r in (0.382, 0.5, 0.618, 0.786)}}
    return out


def volume_read(d):
    c, v = d.close.values, d.volume.values.astype(float)
    out = {}
    for n in (10, 20, 60):
        if len(d) > n:
            dirn = np.sign(c[-n:] - c[-n - 1:-1])
            dv, uv = v[-n:][dirn < 0].sum(), v[-n:][dirn > 0].sum()
            out[f"down_up_{n}"] = round(float(dv / uv), 2) if uv else None
    t = d.iloc[-1]
    out["today_vs_avg"] = round(float(t.vr), 2)
    out["v20"] = int(t.v20)
    out["spikes"] = [{"date": str(r.date.date()), "x": round(float(r.vr), 2), "dir": "up" if r.close >= r.open else "down"}
                     for r in d.tail(15).itertuples() if r.vr >= 1.5]
    obv = d.obv
    out["obv_change_20"] = float(obv.iloc[-1] - obv.iloc[-21]) if len(d) > 21 else None
    return out


def volume_profile(d, days=126, nbins=40):
    y = d.tail(days)
    tp = (y.high + y.low + y.close) / 3
    lo, hi = float(y.low.min()), float(y.high.max())
    step = max(0.01, round((hi - lo) / nbins, 2))
    bins = np.arange(np.floor(lo / step) * step, hi + step, step)
    h, _ = np.histogram(tp, bins=bins, weights=y.volume)
    i = int(h.argmax())
    order = np.argsort(h)[::-1]
    tot, acc, va = h.sum(), 0.0, []
    for j in order:
        acc += h[j]
        va.append(j)
        if acc >= 0.7 * tot:
            break
    c = float(d.close.iloc[-1])
    below = h[bins[:-1] < c]
    return {"bins": [[round(float(b), 2), round(float(x) / 1e6, 2)] for b, x in zip(bins[:-1], h) if x > 0],
            "step": step, "poc": [round(float(bins[i]), 2), round(float(bins[i] + step), 2)],
            "value_area": [round(float(bins[min(va)]), 2), round(float(bins[max(va)] + step), 2)],
            "thin_below": bool(below[-3:].sum() < 0.03 * tot) if len(below) >= 3 else True}


# ---------------------------------------------------------------- intraday, options, peers

def intraday_read(bars, at="13:15"):
    """bars: DataFrame time (HH:MM), open, high, low, close, volume for ONE session."""
    b = bars.copy()
    tp = (b.high + b.low + b.close) / 3
    b["vwap"] = (tp * b.volume).cumsum() / b.volume.cumsum()
    lo_i, hi_i = b.low.idxmin(), b.high.idxmax()
    last_hour = b[b.time >= "14:30"].volume.sum() / b.volume.sum() if len(b) else None
    row = b[b.time <= at].iloc[-1] if (b.time <= at).any() else None
    return {"vwap": round(float(b.vwap.iloc[-1]), 2), "close": round(float(b.close.iloc[-1]), 2),
            "close_vs_vwap": "below" if b.close.iloc[-1] < b.vwap.iloc[-1] else "above",
            "low": round(float(b.low[lo_i]), 2), "low_time": b.time[lo_i], "high": round(float(b.high[hi_i]), 2),
            "high_time": b.time[hi_i], "last_hour_share": round(float(last_hour), 2) if last_hour is not None else None,
            "first_bar_vol_m": round(float(b.volume.iloc[0]) / 1e6, 2), f"price_at_{at}": round(float(row.close), 2) if row is not None else None}


def options_read(chain, spot, days, lot=None):
    """chain: DataFrame strike, call_oi, put_oi, call_bid, call_ask, put_bid, put_ask, iv (ATM-ish IV in %)."""
    ch = chain.sort_values("strike").reset_index(drop=True)
    cw = ch.loc[ch.call_oi.idxmax()]
    pw = ch.loc[ch.put_oi.idxmax()]
    pcr = ch.put_oi.sum() / ch.call_oi.sum() if ch.call_oi.sum() else None
    pain = min(((s, sum(r.call_oi * max(0, s - r.strike) + r.put_oi * max(0, r.strike - s) for r in ch.itertuples()))
                for s in ch.strike), key=lambda z: z[1])[0]
    atm = ch.iloc[(ch.strike - spot).abs().argsort()[:2]]
    iv = float(np.nanmean(atm.iv)) if "iv" in ch and atm.iv.notna().any() else None
    out = {"call_wall": float(cw.strike), "call_wall_oi": int(cw.call_oi), "put_wall": float(pw.strike),
           "put_wall_oi": int(pw.put_oi), "pcr": round(float(pcr), 2) if pcr else None, "max_pain": float(pain), "atm_iv": iv}
    if iv:
        from statistics import NormalDist
        s = iv / 100 * np.sqrt(days / 252)
        N = NormalDist()
        out["implied_range"] = {f"p{int(q * 100)}": round(float(spot * np.exp(-s * s / 2 + N.inv_cdf(q) * s)), 2)
                                for q in (0.1, 0.25, 0.5, 0.75, 0.9)}
        out["implied_sd_pct"] = round(float(s * 100), 1)
    return out


def rel_strength(d, nifty):
    """Returns over 1, 3, 6, 12 months for the stock and the Nifty (nifty: DataFrame date, close)."""
    x = d.set_index("date").close
    n = nifty.set_index("date").close
    out = {}
    for lab, days in (("1m", 21), ("3m", 63), ("6m", 126), ("1y", 250)):
        if len(x) > days and len(n) > days:
            out[lab] = {"stock": round(float(x.iloc[-1] / x.iloc[-1 - days] - 1) * 100, 1),
                        "nifty": round(float(n.iloc[-1] / n.iloc[-1 - days] - 1) * 100, 1)}
    lo = n.tail(252).min()
    out["nifty_to"] = str(n.index[-1].date())
    out["nifty_vs_52w_low_pct"] = round(float(n.iloc[-1] / lo - 1) * 100, 1)
    out["nifty_above_200d"] = bool(n.iloc[-1] > n.tail(200).mean())
    return out


def own_move(d, nifty, look=250, z_cut=1.5):
    """G16 (30 Oct 2026, after the IRFC switch): is the stock moving with the market or on its own today?
    Stock vs Nifty over 1 and 5 days, adjusted for the stock's beta; z = the stock's own move divided by the usual size
    of its own daily moves (both from the year before today). The Nifty must have today's close too (never a stale one)."""
    x = d.set_index("date").close
    n = nifty.set_index("date").close
    n = n[~n.index.duplicated(keep="last")]
    j = pd.concat([x.rename("s"), n.rename("n")], axis=1, join="inner").dropna()
    if len(j) < 60:
        return None
    if j.index[-1] != x.index[-1]:
        return {"read": "nifty_missing", "stock_to": str(x.index[-1].date()), "nifty_to": str(n.index[-1].date()),
                "note": f"G16 check not possible: the Nifty data ends {n.index[-1].date()}, the stock {x.index[-1].date()} – add today's Nifty close (G15)."}
    r = np.log(j).diff().dropna()
    h = r.iloc[-1 - look:-1]
    beta = float(np.cov(h.n, h.s)[0, 1] / np.var(h.n, ddof=1))
    sd = float(np.std(h.s - beta * h.n, ddof=1))
    out = {"beta": round(beta, 2), "own_sd_pct": round(sd * 100, 2)}
    for lab, k in (("1d", 1), ("5d", 5)):
        if len(j) <= k:
            continue
        rs, rn = float(j.s.iloc[-1] / j.s.iloc[-1 - k] - 1), float(j.n.iloc[-1] / j.n.iloc[-1 - k] - 1)
        own = np.log1p(rs) - beta * np.log1p(rn)
        out[lab] = {"stock": round(rs * 100, 2), "nifty": round(rn * 100, 2), "own": round(float(own) * 100, 2),
                    "z": round(float(own / (sd * np.sqrt(k))), 2)}
    t = d.iloc[-1]
    lo52 = float(d.low.iloc[-253:-1].min())
    out["new_52w_low"] = bool(t.low < lo52)
    out["prior_52w_low"] = round(lo52, 2)
    d1, d5 = out.get("1d", {}), out.get("5d", {})
    if d1 and d1["z"] <= -z_cut and d1["nifty"] >= -0.2:
        out["read"] = "own_selling"
    elif d1 and d1["z"] >= z_cut and d1["nifty"] <= 0.2:
        out["read"] = "own_buying"
    elif d5 and d5["z"] <= -z_cut:
        out["read"] = "own_selling_5d"
    elif d5 and d5["z"] >= z_cut:
        out["read"] = "own_buying_5d"
    else:
        out["read"] = "with_market"
    if out["read"] == "with_market":
        out["note"] = (f"Moving with the market: {d1.get('stock')}% vs the Nifty {d1.get('nifty')}% today "
                       f"(own move {d1.get('own')}%, z {d1.get('z')}).")
    else:
        k = "1d" if out["read"] in ("own_selling", "own_buying") else "5d"
        q = out[k]
        side = "falling" if out["read"].startswith("own_selling") else "rising"
        against = "bullish" if side == "falling" else "bearish"
        span = "today" if k == "1d" else "over 5 days"
        out["note"] = (f"G16 WARNING: the stock is {side} on its own {span} – {q['stock']}% while the Nifty moved {q['nifty']}% "
                       f"(own move {q['own']}%, {abs(q['z'])}x its usual size)" +
                       (f", to a new 52-week low (below {out['prior_52w_low']})" if out["new_52w_low"] and side == "falling" else "") +
                       f". Any reason that rests on the market (e.g. 'the Nifty is near its low, so stocks bounce') is not working "
                       f"for this stock {span}: do not switch to a {against} trade on that reason; keep the current plan and re-check at the close. "
                       f"(Tested on NSE 2024–26: such days did not predict the next 15 days either way – this stops market-based "
                       f"switches, it is not a signal on its own.)")
    return out
