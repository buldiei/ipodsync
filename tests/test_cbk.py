"""cbk is reproduced byte-for-byte against the golden tests/data/Locations.itdb.

hashAB is pure-Python (no native lib), so this always runs.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ipodsync.cbk import build_cbk

GUID = bytes.fromhex("000a270024bd17a1")  # FirewireGuid of the reference device
FIX = Path(__file__).resolve().parent / "data"

CASES = [
    FIX / "Locations.itdb",   # 2-track database
]


@pytest.mark.parametrize("loc_path", CASES)
def test_cbk_byte_identical(loc_path):
    cbk_path = loc_path.with_suffix(".itdb.cbk")
    if not loc_path.exists() or not cbk_path.exists():
        pytest.skip(f"no golden file {loc_path}")
    loc = loc_path.read_bytes()
    expected = cbk_path.read_bytes()
    assert build_cbk(loc, GUID) == expected
