"""Offline replay (no internet): a fake price feed and a fake Slack. Checks the hourly split into the positive and
negative channels, the instant 'crossed our level' message, Slack commands and the Trade Watch hand-over.
  python3 tests/test_offline.py        (add -v to print every message)"""
import datetime as dt
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tracker as T  # noqa: E402
from slackapi import Slack  # noqa: E402

IST = T.IST
V = "-v" in sys.argv


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def series(seed, start, drift, n, step, t0):
    random.seed(seed)
    out, p = [], start
    for i in range(n):
        o = p
        p = max(1, p * (1 + drift + random.gauss(0, 0.012)))
        h, l = max(o, p) * (1 + abs(random.gauss(0, 0.004))), min(o, p) * (1 - abs(random.gauss(0, 0.004)))
        out.append((t0 + i * step, o, h, l, p, 1e6))
    return out


class FakeFeed:
    def __init__(self, clock, prices):
        self.clock, self.prices = clock, prices  # symbol -> function(t) -> price

    def chart(self, ysym, rng="1d", interval="1m"):
        sym = ysym.replace(".NS", "")
        if sym not in self.prices:
            raise T.net.HttpError(404, "no data")
        p = self.prices[sym](self.clock())
        now = int(self.clock())
        if interval == "1d":
            base = p / 1.2
            cs = series(hash(sym) % 1000, base, 0.0008, 480, 86400, now - 480 * 86400)
            k = p / cs[-2][4] * 0.99
            cs = [(tt, o * k, h * k, l * k, c * k, v) for tt, o, h, l, c, v in cs]
            cs[-1] = (now, cs[-2][4], max(cs[-2][4], p), min(cs[-2][4], p), p, 1e6)
        elif interval == "60m":
            cs = series(hash(sym) % 777, p * 0.97, 0.0003, 140, 3600, now - 140 * 3600)
        else:
            cs = [(now - 300, p, p, p, p, 1e5)]
        if len(cs) > 5:  # end the made-up history at today's price
            k = p / cs[-1][4]
            cs = [(t, o * k, h * k, l * k, c * k, v) for t, o, h, l, c, v in cs]
        return {"price": p, "time": now, "prev_close": p / 1.01, "candles": cs, "age_s": 30}

    def second(self, tvsym):
        sym = tvsym.split(":")[1]
        return {"price": self.prices[sym](self.clock()), "time": None}


class FakeSlack(Slack):
    def __init__(self):
        super().__init__(token="x", dry=False)
        self.bot_user = "UBOT"
        self.inbox = {}  # channel -> [messages]
        self.n = 0

    def post(self, channel, text, thread_ts=None, broadcast=False):
        self.n += 1
        self.sent.append(("post", channel, text))
        if V:
            print(f"\n--- POST {channel}{' (thread)' if thread_ts else ''}\n{text}")
        return f"{1700000000 + self.n}.000"

    def upload_pngs(self, channel, files, comment, thread_ts=None):
        self.n += 1
        assert files and all(f[0][:4] == b"\x89PNG" for f in files), "chart must be a PNG"
        self.sent.append(("upload", channel, comment))
        if V:
            print(f"\n--- UPLOAD {channel} ({len(files)} charts)\n{comment}")
        return f"{1700000000 + self.n}.000"

    def history(self, channel, oldest, limit=200):
        return [m for m in self.inbox.get(channel, []) if float(m["ts"]) > oldest]

    def replies(self, channel, ts, oldest=None, limit=200):
        return []


def main():
    day = dt.datetime(2026, 11, 16, 9, 20, tzinfo=IST)  # a Monday
    clock = Clock(day.timestamp())
    # IRFC: added at 100, our level 102 (up) - it rises to 105 by 11:00. TCS: added 3000, expect up, falls to 2940.
    prices = {
        "IRFC": lambda t: 100 + min(5.0, max(0.0, (t - day.timestamp()) / 3600 * 3.0)),
        "TCS": lambda t: 3000 - min(60, (t - day.timestamp()) / 3600 * 40),
        "PFC": lambda t: 400 - min(12, (t - day.timestamp()) / 3600 * 8),  # we expect DOWN: falling = our way
        "NEWCO": lambda t: 250.0,
    }
    wl = {"settings": {"positive_channel": "CPOS", "negative_channel": "CNEG", "tradewatch_channel": "CTW",
                       "nitin": "UNITIN", "friends": [{"name": "Sarthak", "id": "USAR"}, {"name": "Friend2", "id": "UF2"}]},
          "items": [
              {"id": "P01", "symbol": "IRFC", "dir": "up", "cmp_at_add": 100, "level": 102, "added": "2026-11-13T15:20",
               "status": "watching", "why": "rising 3-touch line + ₹99 floor"},
              {"id": "P02", "symbol": "TCS", "dir": "up", "cmp_at_add": 3000, "level": 3060, "stop": 2950,
               "added": "2026-11-13T15:25", "status": "watching"},
              {"id": "P03", "symbol": "PFC", "dir": "down", "cmp_at_add": 400, "level": 392, "added": "2026-11-13T15:30",
               "status": "watching"}]}
    commits = []

    def fake_commit(mutate, msg, current):
        commits.append(msg)
        return mutate(current)

    slack = FakeSlack()
    tr = T.Tracker(wl, {}, slack, FakeFeed(clock, prices), clock=clock, sleep=lambda s: None, log=lambda *a: None,
                   commit=fake_commit)
    # 9:20 -> 15:30 every 3 minutes
    while dt.datetime.fromtimestamp(clock(), IST).time() <= dt.time(15, 30):
        t = dt.datetime.fromtimestamp(clock(), IST)
        if t.strftime("%H:%M") == "10:41":
            slack.inbox["CPOS"] = [{"ts": f"{clock():.3f}", "user": "USAR", "text": "track NEWCO up 255 sl 240 why breakout"}]
        if t.strftime("%H:%M") == "12:05":
            slack.inbox["CTW"] = [{"ts": f"{clock():.3f}", "bot_id": "B1",
                                   "text": "*Your trades · 12:05*\n🆕 *New:* IRFC 25 Nov FUT · long 1 @ 104.2"}]
        if t.strftime("%H:%M") == "13:02":
            slack.inbox["CNEG"] = [{"ts": f"{clock():.3f}", "user": "UNITIN", "text": "remove TCS"}]
        if t.strftime("%H:%M") == "13:30":
            slack.inbox["CNEG"] = [{"ts": f"{clock():.3f}", "user": "UNKNOWN", "text": "remove PFC"}]
        tr.tick()
        clock.t += 180
    ups = [s for s in slack.sent if s[1] == "CPOS"]
    downs = [s for s in slack.sent if s[1] == "CNEG"]
    hourly_pos = [s for s in ups if "Going our way" in s[2]]
    hourly_neg = [s for s in downs if "Going against us" in s[2]]
    cross = [s for s in ups if "crossed OUR LEVEL" in s[2]]
    wrong = [s for s in downs if "wrong-way level" in s[2] and "crossed" in s[2]]
    checks = {
        "6 hourly positive messages (10:15-15:15)": len(hourly_pos) == 6,
        "TCS appears in the negative channel": any("TCS" in s[2] for s in hourly_neg),
        "PFC (expected down, falling) is on the positive side": any("PFC" in s[2] for s in hourly_pos),
        "IRFC crossed our level once (instant)": len([s for s in cross if "IRFC" in s[2]]) == 1,
        "TCS wrong-way level message once": len([s for s in wrong if "TCS" in s[2]]) == 1,
        "NEWCO added from Slack by a friend": any("Now tracking" in s[2] and "NEWCO" in s[2] for s in slack.sent),
        "IRFC moved to Trade Watch after its trade appeared": any(x["symbol"] == "IRFC" and x["status"] == "entered"
                                                                 for x in tr.wl["items"]),
        "IRFC not in updates after 12:05": not any("IRFC" in s[2] for s in hourly_pos if "13:15" in s[2]),
        "TCS removed by Nitin": any(x["symbol"] == "TCS" and x["status"] == "removed" for x in tr.wl["items"]),
        "stranger's command ignored": any(x["symbol"] == "PFC" and x["status"] == "watching" for x in tr.wl["items"]),
        "Nitin and friends tagged": all(u in hourly_pos[0][2] for u in ("<@UNITIN>", "<@USAR>", "<@UF2>")),
        "Trade Analyzer link in each block": "H2WXRTxJ7UaF86ZD5Fu1HG#IRFC" in hourly_pos[0][2],
        "no line starts with '1.' (Slack list bug)": not any(ln.strip()[:2] in ("1.", "2.") for s in slack.sent
                                                              for ln in s[2].splitlines()),
        "commits for add/entered/remove": len(commits) == 3,
    }
    for k, ok in checks.items():
        print(("PASS " if ok else "FAIL ") + k)
    print(f"messages: {len(slack.sent)} · counts {tr.counts}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
