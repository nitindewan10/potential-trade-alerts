"""Slack calls of the Potential Trade Alerts bot (its own Slack app, separate from Trade Watch). Allowed: post a
message, upload chart pictures, read its two channels and their threads, read #trade-watch (only to see that a trade
was entered), join a channel. Nothing else."""
import json
import os
import time
import urllib.parse

import net

API = "https://slack.com/api/"


class SlackError(Exception):
    pass


class Slack:
    def __init__(self, token=None, http=net.request, dry=False):
        self.token = (token if token is not None else os.environ.get("SLACK_BOT_TOKEN", "")).strip()
        self.http, self.dry = http, dry
        self.bot_user = None
        self.sent = []  # (kind, channel, text) - for tests and dry runs

    def ready(self):
        return bool(self.token) or self.dry

    def _h(self, form=False):
        h = {"Authorization": "Bearer " + self.token}
        if form:
            h["Content-Type"] = "application/x-www-form-urlencoded"
        return h

    def _ok(self, j, what):
        if not j.get("ok"):
            raise SlackError(f"{what}: {j.get('error', 'not ok')}")
        return j

    def _get(self, method, params):
        url = API + method + "?" + urllib.parse.urlencode(params)
        return self._ok(net.retry(lambda: self.http("GET", url, headers=self._h())), method)

    def _post_json(self, method, body):
        return self._ok(net.retry(lambda: self.http("POST", API + method, headers=self._h(), body=body)), method)

    def _post_form(self, method, fields):
        raw = urllib.parse.urlencode(fields).encode()
        return self._ok(net.retry(lambda: self.http("POST", API + method, headers=self._h(True), raw=raw)), method)

    def whoami(self):
        if self.dry:
            self.bot_user = "UBOT"
            return self.bot_user
        self.bot_user = self._get("auth.test", {})["user_id"]
        return self.bot_user

    def join(self, channel):
        if self.dry:
            return
        try:
            self._post_json("conversations.join", {"channel": channel})
        except SlackError:
            pass  # private channel: the bot must be invited once (done at set-up)

    def post(self, channel, text, thread_ts=None, broadcast=False):
        self.sent.append(("post", channel, text))
        if self.dry:
            return f"dry-{len(self.sent)}"
        body = {"channel": channel, "text": text, "unfurl_links": False, "unfurl_media": False}
        if thread_ts:
            body["thread_ts"] = thread_ts
            if broadcast:
                body["reply_broadcast"] = True
        return self._post_json("chat.postMessage", body)["ts"]

    def upload_pngs(self, channel, files, comment, thread_ts=None):
        """Upload chart pictures [(png_bytes, filename, title)] as ONE message with `comment` as its text; returns
        the message ts (so the hourly message can be found again for replies)."""
        self.sent.append(("upload", channel, comment))
        if self.dry:
            return f"dry-{len(self.sent)}"
        ids = []
        for png, filename, title in files:
            j = self._post_form("files.getUploadURLExternal", {"filename": filename, "length": str(len(png))})
            net.retry(lambda: self.http("POST", j["upload_url"], raw=png,
                                        headers={"Content-Type": "application/octet-stream"}, as_json=False))
            ids.append({"id": j["file_id"], "title": title})
        fields = {"files": json.dumps(ids), "channel_id": channel, "initial_comment": comment}
        if thread_ts:
            fields["thread_ts"] = thread_ts
        self._post_form("files.completeUploadExternal", fields)
        for _ in range(8):  # the message ts appears in the file's shares a moment later
            time.sleep(1.5)
            try:
                info = self._get("files.info", {"file": ids[0]["id"]})["file"]
            except SlackError:
                continue
            shares = info.get("shares") or {}
            for kind in ("public", "private"):
                arr = (shares.get(kind) or {}).get(channel) or []
                if arr:
                    return arr[0].get("ts")
        return None

    def history(self, channel, oldest, limit=200):
        if self.dry:
            return []
        return self._get("conversations.history", {"channel": channel, "oldest": f"{oldest:.6f}", "limit": limit,
                                                   "inclusive": "false"}).get("messages", [])

    def replies(self, channel, ts, oldest=None, limit=200):
        if self.dry or not ts or str(ts).startswith("dry-"):
            return []
        p = {"channel": channel, "ts": ts, "limit": limit}
        if oldest:
            p["oldest"] = f"{oldest:.6f}"
        return self._get("conversations.replies", p).get("messages", [])[1:]  # skip the parent
