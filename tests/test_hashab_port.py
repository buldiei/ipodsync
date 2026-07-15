"""Validation of the pure-Python hashAB port against reference traces from C.

tests/data/hashab-traces.json — intermediate buffers (phase1_output, round_state,
expanded_buffer, ibuff_result, pre_final_target, final_target), captured from an
instrumented dstaley/hashab on 3 vectors. The port proceeds phase by phase; the tests
check each completed phase. The generate_key_material/generate_initial_buffer phases
are still in progress — their tests are marked xfail until finished.
"""
import json
from pathlib import Path

import pytest

from ipodsync import _hashab_py as h

TRACES = json.loads((Path(__file__).parent / "data" / "hashab-traces.json").read_text())
RND = b"ABCDEFGHIJKLMNOPQRSTUVW"


def _inputs(tr):
    return bytes.fromhex(tr["sha1"]), bytes.fromhex(tr["uuid"])


@pytest.mark.parametrize("tr", TRACES, ids=lambda t: t["sha1"][:8])
def test_phase1(tr):
    sha1, uuid = _inputs(tr)
    got = h.phase1(h.build_input_data(sha1, uuid, RND))
    assert got.hex() == tr["phase1_output"]


@pytest.mark.parametrize("tr", TRACES, ids=lambda t: t["sha1"][:8])
def test_round_state(tr):
    sha1, uuid = _inputs(tr)
    p1 = h.phase1(h.build_input_data(sha1, uuid, RND))
    _rs, cb = h.derive_round_state(p1)
    assert cb.hex() == tr["round_state"]


@pytest.mark.parametrize("tr", TRACES, ids=lambda t: t["sha1"][:8])
def test_phase2_and_final(tr):
    """phase2 + final on the REFERENCE ibuff_result (generate_* not yet ported)."""
    sha1, uuid = _inputs(tr)
    p1 = h.phase1(h.build_input_data(sha1, uuid, RND))
    rs, cb = h.derive_round_state(p1)
    target = h.init_target_rnd(RND)
    target[25:57] = h.phase2(rs, bytes.fromhex(tr["ibuff_result"]), cb)
    assert target.hex() == tr["pre_final_target"]
    h.final_permute(target)
    assert target.hex() == tr["final_target"]


@pytest.mark.parametrize("tr", TRACES, ids=lambda t: t["sha1"][:8])
def test_generate_key_material(tr):
    from ipodsync._hashab_gen2 import generate_key_material
    got = generate_key_material(bytes.fromhex(tr["phase1_output"]))
    assert got.hex() == tr["expanded_buffer"]


@pytest.mark.parametrize("tr", TRACES, ids=lambda t: t["sha1"][:8])
def test_generate_initial_buffer(tr):
    from ipodsync._hashab_gen2 import generate_initial_buffer
    got = generate_initial_buffer(bytes.fromhex(tr["expanded_buffer"]))
    assert got.hex() == tr["ibuff_result"]


def test_generate_buffer_from_state_mixing():
    """Reference captured from the C harness (tools) on fixed inputs (data-independent function)."""
    from ipodsync._hashab_gen import generate_buffer_from_state_mixing as g
    from ipodsync._hashab_gen_rt import U32
    p1 = [U32(i * 0x11111111 + 7) for i in range(16)]
    p2 = [U32(i * 0x01010101 + 3) for i in range(16)]
    got = "".join(f"{int(x):08x}" for x in g(p1, p2))
    exp = ("cefd5df3b66e0526a0a53cb9006f87abde74280dce88891a1274de17c746324f"
           "d7441f8db951f9541eb02af05191a0b3f7315ac2840dc4faaf1b4a26252da9fd")
    assert got == exp
