"""hashAB — anti-tamper signature for the iPod nano 6G/7G SQLite database.

Pure-Python (no native lib): the algorithm (white-box AES, reverse-engineered
from dstaley/hashab, public domain) is ported into `_hashab_py`/`_hashab_gen*`.
Verified against 100/100 test vectors. API preserved: HashAB().sign(sha1, uuid, rnd).
"""
from __future__ import annotations

import os

from ._hashab_py import calc_hashab

SHA1_LEN = 20
UUID_LEN = 8
RND_LEN = 23
OUTPUT_LEN = 57  # signature, starts with 03 00


class HashABError(RuntimeError):
    pass


class HashAB:
    """Pure-Python hashAB. lib_path is ignored (kept for compatibility)."""

    def __init__(self, lib_path: str | os.PathLike | None = None):
        pass

    def sign(self, sha1: bytes, uuid: bytes, rnd_bytes: bytes | None = None) -> bytes:
        """Return the 57-byte hashAB signature.

        sha1  — 20 bytes (SHA1 of the hash-protected region).
        uuid  — 8 bytes, the device's FirewireGuid.
        rnd_bytes — 23 random bytes (embedded in the signature); defaults to os.urandom.
        """
        if len(sha1) != SHA1_LEN:
            raise HashABError(f"sha1 must be {SHA1_LEN} bytes, not {len(sha1)}")
        if len(uuid) != UUID_LEN:
            raise HashABError(f"uuid must be {UUID_LEN} bytes, not {len(uuid)}")
        if rnd_bytes is None:
            rnd_bytes = os.urandom(RND_LEN)
        if len(rnd_bytes) != RND_LEN:
            raise HashABError(f"rnd_bytes must be {RND_LEN} bytes, not {len(rnd_bytes)}")
        return calc_hashab(sha1, uuid, rnd_bytes)
