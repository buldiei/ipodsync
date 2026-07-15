"""Generate Locations.itdb.cbk — the anti-tamper signature of the nano 7G SQLite DB.

The format was worked out from the tunesreloaded code (modules/hashAB.js) and
verified byte-for-byte against the reference in native/fixtures/:

    cbk = signature(57) + master_sha1(20) + block_sha1[i](20) * N

  where Locations.itdb is split into 1024-byte blocks (the last one padded with
  zeros to 1024), each block -> SHA1; the concatenation of all block-SHA1s -> SHA1 =
  master; signature = calcHashAB(master, FirewireGuid, rnd=FIXED_RND).

tunesreloaded/libgpod use the fixed rnd b"ABCDEFGHIJKLMNOPQRSTUVW"
(the same one used in the hashab test vectors) — so cbk is fully deterministic.
Only Locations.itdb is hash-protected; the other .itdb files are plain SQLite.
"""
from __future__ import annotations

import hashlib

from .hashab import HashAB

CBK_BLOCK_SIZE = 1024
FIXED_RND = b"ABCDEFGHIJKLMNOPQRSTUVW"   # 23 bytes, as in tunesreloaded/test vectors


def build_cbk(locations_itdb: bytes, firewire_guid: bytes,
              hasher: HashAB | None = None) -> bytes:
    """Build the contents of Locations.itdb.cbk for a given Locations.itdb.

    firewire_guid — 8 bytes (big-endian, as from sysinfo.read_firewire_guid).
    """
    h = hasher or HashAB()

    digests = []
    for i in range(0, len(locations_itdb), CBK_BLOCK_SIZE):
        block = locations_itdb[i:i + CBK_BLOCK_SIZE]
        if len(block) < CBK_BLOCK_SIZE:
            block = block + b"\x00" * (CBK_BLOCK_SIZE - len(block))
        digests.append(hashlib.sha1(block).digest())

    concat = b"".join(digests)
    master = hashlib.sha1(concat).digest()
    signature = h.sign(master, firewire_guid, rnd_bytes=FIXED_RND)
    return signature + master + concat
