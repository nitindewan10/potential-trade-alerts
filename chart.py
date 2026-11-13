"""The chart picture for each tracked stock, drawn with the Trade Analyzer / Stock Deep Check logic:
- Daily (about 7 months): candles, 50- and 200-day averages, rising and falling trendlines (3+ touches only, touches
  marked), support/resistance with their touch counts, floor/ceiling zones, decision points (a trendline meeting a
  horizontal level, Nitin's rule), and the WEEKLY lines and levels carried down (dashes, marked W).
- RSI(14) with 30/70.
- Hourly (last ~10 sessions): hourly trendlines (3+ touches) plus the daily and weekly levels carried down.
- On every panel: the price when we added the stock (grey), OUR LEVEL (purple, thick), stop/target if set.
Every line has a plain-language label on the right (what it is, the price, what it means)."""
import datetime as dt
import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

UP, DOWN, LVL, CMP = "#1a9850", "#d73027", "#6a3d9a", "#7f7f7f"


def rs(x):
    return f"₹{x:,.2f}" if abs(x) < 10000 else f"₹{x:,.0f}"


def _candles(ax, d, width=0.6):
    for x, (o, h, l, c) in enumerate(zip(d.open, d.high, d.low, d.close)):
        col = UP if c >= o else DOWN
        ax.vlines(x, l, h, color=col, linewidth=0.7)
        ax.add_patch(Rectangle((x - width / 2, min(o, c)), width, max(abs(c - o), (h - l) * 0.02 or 1e-6),
                               facecolor=col, edgecolor=col, linewidth=0.5))


def _labels(ax, items, x_text, fontsize=7.3):
    """items = [(y, text, colour)]: right-hand labels pushed apart so they never overlap."""
    lo, hi = ax.get_ylim()
    span = hi - lo
    items = sorted([it for it in items if lo <= it[0] <= hi], key=lambda t: t[0])
    if not items:
        return
    gap = span * 0.05
    placed = []
    for y, _, _ in items:
        placed.append(max(y, placed[-1] + gap) if placed else y)
    over = placed[-1] - (hi - span * 0.02)
    if over > 0:
        placed = [p - over for p in placed]
        for k in range(1, len(placed)):  # keep the gap after shifting down
            placed[k] = max(placed[k], placed[k - 1] + gap)
    for (y, txt, col), yy in zip(items, placed):
        ax.annotate(txt, xy=(x_text, y), xytext=(x_text + 1, yy), fontsize=fontsize, color=col, va="center",
                    annotation_clip=False,
                    arrowprops=dict(arrowstyle="-", color=col, lw=0.5, alpha=0.6) if abs(yy - y) > gap * 0.3 else None,
                    bbox=dict(boxstyle="round,pad=0.15", facecolor="white", edgecolor=col, linewidth=0.4, alpha=0.92))


def our_lines(item):
    out = []
    cmp_ = item.get("cmp_at_add")
    if cmp_:
        out.append((float(cmp_), f"Price when added {rs(float(cmp_))} ({item.get('added', '')[:10]})", CMP, 1.1, "--"))
    lvl = item.get("level")
    if lvl:
        word = "invest if it goes above" if item.get("dir", "up") == "up" else "act if it goes below"
        out.append((float(lvl), f"OUR LEVEL {rs(float(lvl))} – {word}", LVL, 2.2, "-"))
    for k, name, col, word in (("stop", "Stop / wrong-way level", DOWN, "idea fails beyond it"),
                               ("target", "Target", UP, "expected move")):
        v = item.get(k)
        if v:
            out.append((float(v), f"{name} {rs(float(v))} – {word}", col, 1.1, "--"))
    return out


def near(levels, price, k=3, within=0.15):
    """Only the nearest k levels below and above the price (a readable chart, not every level)."""
    lv = [x for x in levels if abs(x["price"] / price - 1) <= within]
    below = sorted([x for x in lv if x["price"] < price], key=lambda x: -x["price"])[:k]
    above = sorted([x for x in lv if x["price"] >= price], key=lambda x: x["price"])[:k]
    return below + above


def _weekly_on(dates, wk, ln):
    """A weekly trendline expressed on another time frame's dates (interpolated through the weekly bars)."""
    wd = wk["d"].date.values.astype("datetime64[D]").astype(float)
    vals = ln["p0"] + ln["slope"] * (np.arange(len(wd)) - ln["i0"])
    x = dates.values.astype("datetime64[D]").astype(float)
    step = (wd[-1] - wd[-2]) if len(wd) > 1 else 7
    wd2, v2 = np.append(wd, wd[-1] + step * 3), np.append(vals, vals[-1] + ln["slope"] * 3)
    return np.interp(x, wd2, v2, left=np.nan)


def render(item, f, now_price, headline, footer):
    daily, weekly, hourly = f.get("daily") or {}, f.get("weekly") or {}, f.get("hourly") or {}
    d = daily.get("d")
    fig = plt.figure(figsize=(13, 10.2), dpi=105)
    gs = fig.add_gridspec(3, 1, height_ratios=[5.2, 1.2, 3.6], hspace=0.3, left=0.055, right=0.72, top=0.93,
                          bottom=0.06)
    ax, axr, axh = fig.add_subplot(gs[0]), fig.add_subplot(gs[1]), fig.add_subplot(gs[2])
    fig.suptitle(headline, x=0.055, ha="left", fontsize=12.5, fontweight="bold")
    price = now_price
    ours = our_lines(item)

    # ---------------- daily
    if d is not None and len(d) >= 30:
        show = min(len(d), 140)
        s = len(d) - show
        v = d.iloc[s:].reset_index(drop=True)
        _candles(ax, v)
        ax.plot(len(v), price, marker="o", color="black", ms=5)
        lab = [(price, f"NOW {rs(price)}", "black")]
        for n, col in ((200, "#ff7f00"), (50, "#377eb8")):
            ma = d[f"ma{n}"].iloc[s:].values
            if not np.all(np.isnan(ma)):
                ax.plot(range(len(v)), ma, color=col, lw=1.1)
                last = ma[~np.isnan(ma)][-1]
                lab.append((last, f"{n}-day avg {rs(last)} ({'price above' if price >= last else 'price below'})", col))
        for ln in daily.get("lines", []):
            if abs(ln["today"] / price - 1) > 0.25:
                continue
            col = UP if ln["kind"] == "up" else DOWN
            x0 = max(ln["i0"], s)
            xs = np.array([x0, len(d)])
            ys = ln["p0"] + ln["slope"] * (xs - ln["i0"])
            ax.plot(xs - s, ys, color=col, lw=1.7)
            for t_date, t_px in ln["touches"]:
                idx = d.index[d.date.dt.strftime("%Y-%m-%d") == t_date]
                if len(idx) and idx[0] >= s:
                    ax.plot(idx[0] - s, t_px, "o", color=col, ms=3.5)
            what = "rising line – support while above" if ln["kind"] == "up" else "falling line – resistance until broken"
            lab.append((ys[-1], f"{what} {rs(ys[-1])} · {ln['n']} touches", col))
        if weekly.get("lines") and weekly.get("d") is not None and len(weekly["d"]) > 2:
            for ln in weekly["lines"]:
                col = UP if ln["kind"] == "up" else DOWN
                yv = _weekly_on(v.date, weekly, ln)
                ax.plot(range(len(v)), yv, color=col, lw=1.2, ls=(0, (6, 3)), alpha=0.8)
                if not np.isnan(yv[-1]):
                    lab.append((yv[-1], f"W {'rising' if ln['kind'] == 'up' else 'falling'} line {rs(yv[-1])} · "
                                        f"{ln['n']} weekly touches", col))
        for lv in near(daily.get("levels", []), price, 2):
            if True:
                ax.axhline(lv["price"], color="#7f7f7f", lw=0.8, ls=":")
                role = "support" if lv["price"] < price else "resistance"
                lab.append((lv["price"], f"{role} {rs(lv['price'])} · {lv['touches']} touches", "#555555"))
        for lv in near([x for x in weekly.get("levels", []) if x.get("touches", 0) >= 3], price, 1):
            if True:
                ax.axhline(lv["price"], color="#444444", lw=0.9, ls="-.")
                lab.append((lv["price"], f"W {'support' if lv['price'] < price else 'resistance'} "
                                         f"{rs(lv['price'])} · {lv['touches']} weekly touches", "#333333"))
        for key, col, word in (("floor", UP, "floor zone"), ("ceiling", DOWN, "ceiling zone")):
            z = daily.get(key)
            if z:
                ax.axhspan(z["lo"], z["hi"], color=col, alpha=0.07)
                lab.append(((z["lo"] + z["hi"]) / 2, f"{word} {rs(z['lo'])}–{rs(z['hi'])} · {z['tests']} tests", col))
        for y, txt, col, lw, ls in ours:
            ax.axhline(y, color=col, lw=lw, ls=ls)
            lab.append((y, txt, col))
        for dp in (daily.get("decision") or [])[:2]:
            x = len(d) - 1 + dp["bars_ahead"] - s
            ax.plot(x, dp["level"], marker="*", ms=13, color="#e7298a")
            lab.append((dp["level"], f"DECISION POINT {rs(dp['level'])} – {'rising' if dp['line'] == 'up' else 'falling'}"
                                     f" line meets level in {max(0, dp['bars_ahead']):.0f} days", "#e7298a"))
        if item.get("added"):
            try:
                ad = dt.datetime.fromisoformat(item["added"][:10])
                ix = np.searchsorted(v.date.values, np.datetime64(ad))
                ax.axvline(ix, color=CMP, lw=0.8, ls=":")
            except ValueError:
                pass
        ys = list(v.low) + list(v.high) + [y for y, _, _ in lab if abs(y / price - 1) <= 0.2]
        lo, hi = min(ys), max(ys)
        pad = (hi - lo) * 0.05 or price * 0.02
        ax.set_ylim(lo - pad, hi + pad)
        ax.set_xlim(-1, len(v) + 22)
        _labels(ax, lab, len(v) + 21)
        tk = list(range(0, len(v), max(1, len(v) // 8)))
        ax.set_xticks(tk)
        ax.set_xticklabels([v.date[i].strftime("%d %b") for i in tk], fontsize=8)
        ax.set_title("Daily · weekly lines carried down (W, dashes) · ★ = decision point", fontsize=9, loc="left")
        ax.grid(alpha=0.15)
        rsi = d.rsi.iloc[s:].values
        axr.plot(range(len(rsi)), rsi, color="#984ea3", lw=1)
        axr.axhline(70, color=DOWN, lw=0.6, ls="--")
        axr.axhline(30, color=UP, lw=0.6, ls="--")
        axr.set_ylim(10, 90)
        axr.set_xlim(-1, len(v) + 22)
        axr.set_xticks([])
        r_now = f.get("rsi")
        if r_now is not None and not np.isnan(r_now):
            state = "overbought (>70)" if r_now > 70 else "oversold (<30)" if r_now < 30 else "neutral (30–70)"
            axr.text(len(v) + 1, r_now, f"RSI now {r_now:.0f} – {state}", fontsize=7.5, color="#984ea3", va="center")
        axr.set_title("RSI(14)", fontsize=8.5, loc="left")
        axr.grid(alpha=0.15)
    else:
        ax.text(0.5, 0.5, "Not enough daily history", ha="center", transform=ax.transAxes)
        axr.set_axis_off()

    # ---------------- hourly
    ha = f.get("hourly_all")
    if ha is not None and len(ha) > 5:
        hv = ha.iloc[-70:].reset_index(drop=True)
        off = len(ha) - len(hv)
        _candles(axh, hv)
        lo, hi = float(hv.low.min()), float(hv.high.max())
        span = (hi - lo) or price * 0.01
        inr = lambda y: lo - span * 0.5 <= y <= hi + span * 0.5
        lab = [(price, f"NOW {rs(price)}", "black")]
        hd = hourly.get("d")
        for ln in hourly.get("lines", []):
            if not inr(ln["today"]) or abs(ln["today"] / price - 1) > 0.08:
                continue
            col = UP if ln["kind"] == "up" else DOWN
            xs = np.array([max(ln["i0"], off), len(ha)])
            ys = ln["p0"] + ln["slope"] * (xs - ln["i0"])
            axh.plot(xs - off, ys, color=col, lw=1.4)
            lab.append((ys[-1], f"H {'rising' if ln['kind'] == 'up' else 'falling'} line {rs(ys[-1])} · {ln['n']} touches",
                        col))
        for ln in daily.get("lines", []):
            y = ln["today"] + ln["slope"]
            if inr(y):
                axh.axhline(y, color=UP if ln["kind"] == "up" else DOWN, lw=1, ls="-.")
                lab.append((y, f"D {'rising' if ln['kind'] == 'up' else 'falling'} line today {rs(y)}",
                            UP if ln["kind"] == "up" else DOWN))
        pool = []
        for src, tag in ((weekly, "W"), (daily, "D"), (hourly, "H")):
            for lv in src.get("levels", []):
                if inr(lv["price"]) and (tag != "H" or lv["touches"] >= 3) and \
                        not any(abs(lv["price"] / q["price"] - 1) < 0.004 for q in pool):
                    pool.append(dict(lv, tag=tag))
        for lv in near(pool, price, 2, within=0.2):
            axh.axhline(lv["price"], color="#7f7f7f", lw=0.8, ls=":")
            lab.append((lv["price"], f"{lv['tag']} {'support' if lv['price'] < price else 'resistance'} "
                                     f"{rs(lv['price'])} · {lv['touches']}×", "#555555"))
        for y, txt, col, lw, ls in ours:
            if inr(y):
                axh.axhline(y, color=col, lw=lw, ls=ls)
                lab.append((y, txt.split(" – ")[0], col))
        if item.get("added"):
            try:
                ad = np.datetime64(dt.datetime.fromisoformat(item["added"][:16]))
                ix = int(np.searchsorted(hv.date.values, ad))
                if 0 < ix < len(hv):
                    axh.axvline(ix, color=CMP, lw=0.9, ls=":")
                    axh.text(ix + 0.3, hi + span * 0.02, "added", fontsize=7, color=CMP)
            except ValueError:
                pass
        ys = list(hv.low) + list(hv.high) + [y for y, _, _ in lab]
        axh.set_ylim(min(ys) - span * 0.06, max(ys) + span * 0.06)
        axh.set_xlim(-1, len(hv) + 12)
        _labels(axh, lab, len(hv) + 11, fontsize=7)
        days, last = [], None
        for i, t in enumerate(hv.date):
            if t.date() != last:
                days.append(i)
                last = t.date()
        axh.set_xticks(days)
        axh.set_xticklabels([hv.date[i].strftime("%d %b") for i in days], fontsize=7.5)
        for i in days[1:]:
            axh.axvline(i - 0.5, color="#cccccc", lw=0.6)
        axh.set_title("Hourly · last ~10 sessions · daily (D) and weekly (W) levels carried down", fontsize=9, loc="left")
        axh.grid(alpha=0.15)
    else:
        axh.text(0.5, 0.5, "No hourly candles", ha="center", transform=axh.transAxes)
        axh.set_axis_off()

    fig.text(0.055, 0.015, footer, fontsize=7.5, color="#555555")
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()
