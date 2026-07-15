"""Pure-Python hashAB against the 100 test vectors from dstaley/hashab (fixed rnd)."""
import json
from pathlib import Path

from ipodsync.hashab import HashAB

VECTORS = json.loads((Path(__file__).parent / "data" / "hashab-vectors.json").read_text())
FIXED_RND = b"ABCDEFGHIJKLMNOPQRSTUVW"


def test_all_vectors():
    h = HashAB()
    assert VECTORS
    for i, c in enumerate(VECTORS):
        got = h.sign(bytes.fromhex(c["sha1"]), bytes.fromhex(c["uuid"]), FIXED_RND)
        assert got.hex() == c["target"].lower(), f"vector #{i}"
