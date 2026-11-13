#!/usr/bin/env python3
"""The watch list is kept ENCRYPTED in this public repository (watchlist.enc), so anyone can read the code but nobody
can read Nitin's trades, levels or Slack IDs (his rule, 11 Oct 2026: no trade data in repository files).

Key: the GitHub secret WATCHLIST_KEY (44 characters, base64 of 32 random bytes). Without it the file is useless.
Scheme (standard library only): HMAC-SHA256 in counter mode for the key stream + HMAC-SHA256 tag over nonce and
ciphertext (encrypt-then-MAC); separate keys for encryption and the tag, derived from WATCHLIST_KEY.

Command line (used from the Claude chat to add or change a watch):
  WATCHLIST_KEY=... python3 vault.py decrypt watchlist.enc  > wl.json
  WATCHLIST_KEY=... python3 vault.py encrypt wl.json        > watchlist.enc
  python3 vault.py newkey
"""
import base64
import hashlib
import hmac
import json
import os
import struct
import sys

MAGIC = b"ATW1"


class VaultError(Exception):
    pass


def _keys(key_b64=None):
    raw = (key_b64 if key_b64 is not None else os.environ.get("WATCHLIST_KEY", "")).strip()
    if not raw:
        raise VaultError("WATCHLIST_KEY is not set")
    try:
        k = base64.b64decode(raw + "=" * (-len(raw) % 4))
    except Exception:
        raise VaultError("WATCHLIST_KEY is not valid base64")
    if len(k) < 32:
        raise VaultError("WATCHLIST_KEY is too short")
    root = hashlib.sha256(b"potential-trade-alerts watchlist v1|" + k).digest()
    return hmac.new(root, b"enc", hashlib.sha256).digest(), hmac.new(root, b"mac", hashlib.sha256).digest()


def _stream(key, nonce, n):
    out, i = bytearray(), 0
    while len(out) < n:
        out += hmac.new(key, nonce + struct.pack(">Q", i), hashlib.sha256).digest()
        i += 1
    return bytes(out[:n])


def seal(obj, key_b64=None):
    ek, mk = _keys(key_b64)
    nonce = os.urandom(16)
    pt = json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=1).encode()
    ct = bytes(a ^ b for a, b in zip(pt, _stream(ek, nonce, len(pt))))
    tag = hmac.new(mk, MAGIC + nonce + ct, hashlib.sha256).digest()
    return base64.b64encode(MAGIC + nonce + tag + ct)


def unseal(blob, key_b64=None):
    try:
        raw = base64.b64decode(blob.strip())
    except Exception:
        raise VaultError("watch list file is damaged (not base64)")
    if raw[:4] != MAGIC or len(raw) < 4 + 16 + 32:
        raise VaultError("watch list file is damaged (bad header)")
    nonce, tag, ct = raw[4:20], raw[20:52], raw[52:]
    ek, mk = _keys(key_b64)
    if not hmac.compare_digest(tag, hmac.new(mk, MAGIC + nonce + ct, hashlib.sha256).digest()):
        raise VaultError("wrong WATCHLIST_KEY or the file was changed")
    return json.loads(bytes(a ^ b for a, b in zip(ct, _stream(ek, nonce, len(ct)))).decode())


def load(path):
    with open(path, "rb") as fh:
        return unseal(fh.read())


def main(argv):
    if len(argv) >= 2 and argv[1] == "newkey":
        print(base64.b64encode(os.urandom(32)).decode())
        return 0
    if len(argv) != 3 or argv[1] not in ("encrypt", "decrypt"):
        print(__doc__)
        return 2
    with open(argv[2], "rb") as fh:
        data = fh.read()
    if argv[1] == "encrypt":
        sys.stdout.write(seal(json.loads(data.decode())).decode() + "\n")
    else:
        sys.stdout.write(json.dumps(unseal(data), ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
