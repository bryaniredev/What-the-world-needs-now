"""Encryption shared with the browser (docs/app.js).

Format: PBKDF2-SHA256 -> AES-256-GCM over gzip(JSON). The site's passphrase is
never stored in the repo; it comes from the SITE_PASSPHRASE secret at run time.
"""
import base64
import gzip
import json
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ITERATIONS = 310_000
CHECK_PLAINTEXT = "wtwn-ok"


def b64e(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def b64d(s: str) -> bytes:
    return base64.b64decode(s)


def derive_key(passphrase: str, salt: bytes, iterations: int = ITERATIONS) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations)
    return kdf.derive(passphrase.encode("utf-8"))


def encrypt_obj(key: bytes, obj) -> dict:
    raw = gzip.compress(json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8"), mtime=0)
    iv = os.urandom(12)
    ct = AESGCM(key).encrypt(iv, raw, None)
    return {"v": 1, "iv": b64e(iv), "ct": b64e(ct)}


def decrypt_obj(key: bytes, blob: dict):
    raw = AESGCM(key).decrypt(b64d(blob["iv"]), b64d(blob["ct"]), None)
    return json.loads(gzip.decompress(raw).decode("utf-8"))


def new_meta(key: bytes, salt: bytes) -> dict:
    """Public metadata the browser needs to derive the key and verify it."""
    iv = os.urandom(12)
    check = AESGCM(key).encrypt(iv, CHECK_PLAINTEXT.encode(), None)
    return {
        "v": 1,
        "kdf": "PBKDF2-SHA256",
        "iterations": ITERATIONS,
        "salt": b64e(salt),
        "check": {"iv": b64e(iv), "ct": b64e(check)},
    }


def verify_meta(key: bytes, meta: dict) -> bool:
    try:
        pt = AESGCM(key).decrypt(b64d(meta["check"]["iv"]), b64d(meta["check"]["ct"]), None)
        return pt.decode() == CHECK_PLAINTEXT
    except Exception:
        return False
