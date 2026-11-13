"""Every web call of this job goes through guard(): only these hosts and paths are allowed. There is no broker in the
list at all, so nothing here can place, change or cancel an order or read an account."""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"

ALLOW = {
    # free market data (read only): Yahoo chart API (+ its session cookie and crumb), TradingView scanner
    ("GET", "query1.finance.yahoo.com"): ("/v8/finance/chart/",),
    ("GET", "query2.finance.yahoo.com"): ("/v8/finance/chart/", "/v1/test/getcrumb"),
    ("GET", "fc.yahoo.com"): ("/",),
    ("POST", "scanner.tradingview.com"): ("/india/scan",),
    # Slack: post, upload a chart, read the channel and threads, join the channel
    ("POST", "slack.com"): ("/api/chat.postMessage", "/api/files.getUploadURLExternal",
                            "/api/files.completeUploadExternal", "/api/conversations.join"),
    ("GET", "slack.com"): ("/api/conversations.history", "/api/conversations.replies", "/api/files.info",
                           "/api/auth.test", "/api/reactions.get"),
    ("POST", "files.slack.com"): ("/upload/",),
    # the Claude 360-degree check (routine /fire only)
    ("POST", "api.anthropic.com"): ("/v1/claude_code/routines/",),
    # this repository's own runs (see whether another watcher is running; start the afternoon hand-over run)
    ("GET", "api.github.com"): ("/repos/",),
    ("POST", "api.github.com"): ("/repos/",),
}


class GuardError(Exception):
    pass


class HttpError(Exception):
    def __init__(self, status, msg):
        super().__init__(f"HTTP {status}: {msg}")
        self.status = status


def guard(method, url):
    u = urllib.parse.urlparse(url)
    if u.scheme != "https":
        raise GuardError("https only")
    prefixes = ALLOW.get((method, u.netloc))
    if not prefixes or not any(u.path.startswith(p) for p in prefixes):
        raise GuardError(f"blocked {method} {u.netloc}{u.path[:40]}")
    if u.netloc == "api.anthropic.com" and not u.path.endswith("/fire"):
        raise GuardError("Claude: /fire only")
    if u.netloc == "api.github.com":
        p = u.path
        if method == "POST" and not p.endswith("/dispatches"):
            raise GuardError("GitHub: dispatch only")
        if method == "GET" and "/actions/" not in p:
            raise GuardError("GitHub: runs only")


def request(method, url, headers=None, body=None, raw=None, timeout=25, as_json=True):
    """body = JSON object; raw = bytes (sent as is). Returns parsed JSON (as_json) or bytes."""
    guard(method, url)
    hdrs = {"User-Agent": UA, "Accept": "application/json, text/html;q=0.9, */*;q=0.5"}
    hdrs.update(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        hdrs.setdefault("Content-Type", "application/json; charset=utf-8")
    elif raw is not None:
        data = raw
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = r.read()
    except urllib.error.HTTPError as e:
        raise HttpError(e.code, e.read()[:200].decode("utf-8", "replace"))
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise HttpError(0, str(e)[:120])
    if not as_json:
        return out
    return json.loads(out.decode("utf-8")) if out else {}


def retry(fn, tries=3, wait=4):
    last = None
    for i in range(tries):
        try:
            return fn()
        except HttpError as e:
            last = e
            if e.status in (400, 401, 403, 404):
                break
            time.sleep(wait * (i + 1))
    raise last
