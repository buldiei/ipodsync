"""Pure-Python port of hashAB (white-box AES) — WITHOUT a native lib.

Ported from dstaley/hashab (public domain). The tables (433 KB) live in
`_hashab_tables.bin` (see tools/gen_hashab_tables.py); the logic is here.
C overflow semantics are reproduced exactly: everything is computed in Python int
and masked (u32/u8); signed shifts/divisions are marked explicitly.

The port is validated against instrumented C and 100/100 test vectors
(tests/test_hashab*.py). The orchestrator (phase1/round_state/phase2/final) is here;
generate_key_material/generate_initial_buffer are in _hashab_gen2 (built by
tools/build_gen2.py); generate_buffer_from_state_mixing is in _hashab_gen.
"""
from __future__ import annotations

import struct
from importlib import resources

from ._hashab_tables import TABLES

# --- table loading ---------------------------------------------------------------
_BLOB = resources.files(__package__).joinpath("_hashab_tables.bin").read_bytes()


def _t(name: str) -> bytes:
    off, ln = TABLES[name]
    return _BLOB[off:off + ln]


INPUT_SBOX = _t("INPUT_SBOX")
NIBBLE_SBOX_EVEN = _t("NIBBLE_SBOX_EVEN")
NIBBLE_SBOX_ODD = _t("NIBBLE_SBOX_ODD")
NIBBLE_SBOX_MAIN = _t("NIBBLE_SBOX_MAIN")
FINAL_SBOX = _t("FINAL_SBOX")
OUTPUT_SBOX = _t("OUTPUT_SBOX")
ROUND_KEYS = _t("ROUND_KEYS")
MIXCOL_STATE = _t("MIXCOL_STATE")
MIXCOL_MULT = _t("MIXCOL_MULT")
FINAL_PERM = _t("FINAL_PERM")
WB_STATE_EXTRACT = _t("WB_STATE_EXTRACT")
WB_INPUT_A = _t("WB_INPUT_A")
WB_INPUT_B = _t("WB_INPUT_B")
WB_MIX_A = _t("WB_MIX_A")
WB_MIX_B = _t("WB_MIX_B")
WB_T_TABLES = _t("WB_T_TABLES")
WB_T_MIX = _t("WB_T_MIX")
WB_FINAL_SBOX = _t("WB_FINAL_SBOX")

# inline phase 2 tables (from calcHashAB.c)
LOW_SUB = bytes.fromhex("06030c09020f08050e0b04010a07000d")
NIBBLE_LO_TABLE = bytes.fromhex(
    "cec0c2c4c7c9cbcacccec1c3c5c4c6c8cbcdcfc1c0c2c4c7c9cbcacccec1c3c5c4c6c8cacd"
    "cfc1c0c2c4c7c9cbcacccec1c3c5c7c6c8cacdcfc1c0c2c4c7c9cbcacccec0c3c5c7c6c8ca"
    "cdcfc1c0c2c4c7c9cbcdcccec0c3c5c7c6c8cacdcfc1c0c2c4c6c9cbcdcccec0c3c5c7c6c8"
    "cacdcfc1c3c2c4c6c9cbcdcccec0c3c5c7c6c8cacccfc1c3c2c4c6c9cbcdcccec0c3c5c7c9"
    "c8cacccfc1c3c2c4c6c9cbcdcccec0c2c5c7c9c8cacccfc1c3c2c4c6c9cbcdcfcec0c2c5c7"
    "c9c8cacccfc1c3c2c4c6c8cbcdcfcec0c2c5c7c9c8cacccfc1c3c5c4c6c8cbcdcfcec0c2c5"
    "c7c9c8cacccec1c3c5c4c6c8cbcdcfcec0c2c5c7c9cbcacccec1c3c5c4c6c8cbcdcf")
NIBBLE_HI_TABLE = bytes.fromhex(
    "9d78573209e4c3deb5906f4a213c1bf6cda887627954330ee5c0dfba916c4b263d18f7d2a9"
    "84637e55300feac1dcbb966d48270219f4d3ae85607f5a310cebc6ddb897724924031ef5d0"
    "af8a617c5b360de8c7a2b994734e25001ffad1ac8b667d583712e9c4a3be95704f2a011cfb"
    "d6ad886742593413eec5a0bf9a714c2b061df8d7b28964435e3510efcaa1bc9b764d2807e2"
    "f9d4b38e65405f3a11eccba6bd9877522904e3fed5b08f6a415c3b16edc8a7829974532e05"
    "e0ffdab18c6b465d3817f2c9a4839e75502f0ae1fcdbb68d6847223914f3cea5809f7a512c"
    "0be6fdd8b7926944233e15f0cfaa819c7b562d08e7c2d9b4936e45203f1af1ccab86")
PERMUTATION_TABLE = bytes.fromhex(
    "06181107130d0e09151d021f01041c1a10140b1e030a1b19050f16001217080c")

# --- inline constants (from calcHashAB.c) --------------------------------------
AES_SHIFT_ROWS = (0, 5, 10, 15, 4, 9, 14, 3, 8, 13, 2, 7, 12, 1, 6, 11)
MIXCOL_OFFSETS = (0, 1024, 2048, 3072)
KEY_STATE_INIT = (0xC9, 0xA1, 0x5C, 0x44, 0x17, 0x4B, 0xFA, 0xCD,
                  0xF3, 0x32, 0x85, 0x94, 0x00, 0x5C, 0x0E, 0x5E)


# --- helpers: exact C uint semantics ---------------------------------------------
def u8(x: int) -> int:
    return x & 0xFF


def u32(x: int) -> int:
    return x & 0xFFFFFFFF


# --- phase 1: CBC-MAC-like compression (5 blocks of 16 bytes) -------------------
def _apply_sbox_pair(table: bytes, inp: int, key: int) -> int:
    high = table[(inp & 0xF0) + (key >> 4)]
    low = table[256 + u8((key & 0xF) + 16 * inp)]
    return u8((high << 4) | low)


def _mix_column_byte(ms: bytes, idx0: int, idx1: int, idx2: int, idx3: int, j: int) -> int:
    base = j * 1536
    a = ms[idx0 + j]
    b = ms[idx1 + j]
    c = ms[idx2 + j]
    d = ms[idx3 + j]
    t1 = MIXCOL_MULT[(d & 0xF) + base + 768 + u8(c * 16)] & 0xF
    t2 = MIXCOL_MULT[(b & 0xF) + base + 256 + u8(a * 16)]
    low = MIXCOL_MULT[t1 + base + 1280 + u8(t2 * 16)] & 0xF
    u1 = MIXCOL_MULT[(b >> 4) + (a & 0xF0) + base]
    u2 = MIXCOL_MULT[(c & 0xF0) + base + 512 + (d >> 4)] & 0xF
    high = MIXCOL_MULT[u8(u1 * 16) + base + 1024 + u2]
    return u8(low + 16 * high)


def phase1(input_data: bytes) -> bytes:
    """input_data — 80 bytes (uuid8+sha20+rnd23+padding29). -> phase1_output[80]."""
    key_state = list(KEY_STATE_INIT)
    round_key = ROUND_KEYS
    out = bytearray(80)

    for block in range(5):
        boff = block * 16
        first_sbox = NIBBLE_SBOX_ODD if block else NIBBLE_SBOX_EVEN

        cipher_state = [0] * 16
        for i in range(16):
            ti = INPUT_SBOX[input_data[boff + i]]
            cipher_state[i] = _apply_sbox_pair(first_sbox, ti, key_state[i])

        round_output = [_apply_sbox_pair(NIBBLE_SBOX_MAIN, cipher_state[i], round_key[i])
                        for i in range(16)]

        for rnd in range(1, 10):
            rk = round_key[rnd * 16:]
            perm = [4 * round_output[AES_SHIFT_ROWS[i]] + MIXCOL_OFFSETS[i % 4]
                    for i in range(16)]
            for col in range(4):
                idx0 = perm[col * 4 + 0]
                idx1 = perm[col * 4 + 1]
                idx2 = perm[col * 4 + 2]
                idx3 = perm[col * 4 + 3]
                for j in range(4):
                    cipher_state[col * 4 + j] = _mix_column_byte(
                        MIXCOL_STATE, idx0, idx1, idx2, idx3, j)
            round_output = [_apply_sbox_pair(NIBBLE_SBOX_MAIN, cipher_state[i], rk[i])
                            for i in range(16)]

        permuted = [round_output[AES_SHIFT_ROWS[i]] for i in range(16)]
        for i in range(16):
            cipher_state[i] = _apply_sbox_pair(
                NIBBLE_SBOX_MAIN, FINAL_SBOX[permuted[i]], round_key[160 + i])

        key_state = cipher_state[:]
        for i in range(16):
            out[boff + i] = OUTPUT_SBOX[cipher_state[i]]

    return bytes(out)


def build_input_data(sha1: bytes, uuid: bytes, rnd: bytes) -> bytes:
    """80 bytes: uuid(8)+sha1(20)+rnd(23)+padding(29 x 0xA5)."""
    return bytes(uuid) + bytes(sha1) + bytes(rnd) + b"\xa5" * 29


# --- round_state: permutation of phase1_output -> 8 uint32 ----------------------
def derive_round_state(phase1_output: bytes) -> tuple[list[int], bytes]:
    """-> (round_state[8 int], cipher_block[32 bytes])."""
    cb = bytes(phase1_output[PERMUTATION_TABLE[i] + 44] for i in range(32))
    rs = list(struct.unpack("<8I", cb))
    return rs, cb


def init_target_rnd(rnd: bytes) -> bytearray:
    """target[57]: 03 00 + rnd(23) with mixing + room for phase2."""
    target = bytearray(57)
    target[0] = 3
    target[1] = 0
    target[2:25] = rnd
    for i in range(23):
        x = target[i + 2]
        target[i + 2] = u8(69 * x + 118 * (x & 0x5D) + 17)
    return target


# --- phase 2: white-box AES (2 blocks of 16 bytes) ------------------------------
def _nibble_lo(x: int) -> int:
    return NIBBLE_LO_TABLE[x]


def _nibble_hi(x: int) -> int:
    return NIBBLE_HI_TABLE[x]


def _phase2_transform(rs: list[int], inp: bytes, tab_in: bytes, tab_mix: bytes) -> bytearray:
    rs_bytes = [0] * 16
    for w in range(4):
        for b in range(4):
            byte_val = (rs[w] >> (b * 8)) & 0xFF
            rs_bytes[w * 4 + b] = WB_STATE_EXTRACT[byte_val + (b << 8) + (w << 10)]
    input_trans = [tab_in[inp[i] + i * 256] for i in range(16)]
    out = bytearray(16)
    for i in range(16):
        base = i * 512
        rs_b = rs_bytes[i]
        in_b = input_trans[i]
        out[i] = u8(16 * tab_mix[(rs_b & 0xF0) + base + (in_b >> 4)]
                    + (tab_mix[u8(16 * rs_b + (in_b & 0xF)) + base + 256] & 0xF))
    return out


def phase2(round_state: list[int], ibuff_result: bytes, cipher_block0: bytes) -> bytes:
    """2 iterations of WB-AES. cipher_block0 — the round_state bytes (input to the 2nd iteration).
    -> 32 bytes (into target[25:57])."""
    output = bytearray(32)
    cipher_block = bytearray(cipher_block0)
    for it in range(2):
        inp = ibuff_result if it == 0 else bytes(cipher_block)
        tab_in = WB_INPUT_A if it == 0 else WB_INPUT_B
        tab_mix = WB_MIX_A if it == 0 else WB_MIX_B
        rs = round_state[it * 4: it * 4 + 4]

        phase2_out = _phase2_transform(rs, inp, tab_in, tab_mix)
        cipher_block[:16] = phase2_out
        mix_state = bytearray(phase2_out)

        for rnd in range(9):
            round_offset = rnd * 4096
            perm = [4 * (round_offset + mix_state[AES_SHIFT_ROWS[i]] + i * 256)
                    for i in range(16)]
            for col in range(4):
                co = col * 4
                idx0 = perm[co + 1]
                idx1 = perm[co + 2]
                idx2 = perm[co + 3]
                idx3 = perm[co]
                for bi in range(4):
                    block = rnd * 16 + col * 4 + bi
                    t0 = WB_T_TABLES[idx1 + bi]
                    t1 = WB_T_TABLES[idx3 + bi]
                    t2 = WB_T_TABLES[idx0 + bi]
                    t3 = WB_T_TABLES[idx2 + bi]
                    hi_nib_t0 = _nibble_hi(t0)
                    hi_nib_t1 = _nibble_hi(t1)
                    lo_nib_t2 = _nibble_lo(t2)
                    lo_nib_t3 = _nibble_lo(t3)
                    t0_x27 = u8(27 * t0)
                    mixed_t1 = u8(128 + (122 ^ u8(-27 * t1)))
                    i1 = block * 1536 + 0 * 256 + ((((hi_nib_t1 >> 4) ^ 0x09) & 0x0F) << 4) | ((lo_nib_t2 ^ 0x0E) & 0x0F)
                    i3 = block * 1536 + 1 * 256 + ((((mixed_t1 & 0x0F) ^ 0x0C) << 4) | (((5 * t2 & 0x0F) ^ 0x06) & 0x0F))
                    i2 = block * 1536 + 2 * 256 + ((((hi_nib_t0 >> 4) ^ 0x09) & 0x0F) << 4) | ((lo_nib_t3 ^ 0x0E) & 0x0F)
                    i0 = block * 1536 + 3 * 256 + (((((t0_x27 & 0x0F) + 7) & 0x0F) ^ 0x1) << 4) | LOW_SUB[t3 & 0x0F]
                    i4 = block * 1536 + 4 * 256 + ((WB_T_MIX[i1] & 0x0F) << 4) | (WB_T_MIX[i2] & 0x0F)
                    i5 = block * 1536 + 5 * 256 + ((WB_T_MIX[i3] & 0x0F) << 4) | (WB_T_MIX[i0] & 0x0F)
                    cipher_block[co + bi] = u8(16 * WB_T_MIX[i4] + (WB_T_MIX[i5] & 0xF))
            if rnd < 8:
                mix_state = bytearray(cipher_block[:16])

        temp = bytearray(16)
        for i in range(16):
            temp[i] = WB_FINAL_SBOX[cipher_block[AES_SHIFT_ROWS[i]] + i * 256]
        cipher_block[:16] = temp
        output[it * 16: it * 16 + 16] = cipher_block[:16]
    return bytes(output)


def final_permute(target: bytearray) -> bytearray:
    """Final permutation (FINAL_PERM) + nonlinear mixing of bytes 2..56."""
    perm = struct.unpack("<55I", FINAL_PERM)
    for i in range(55):
        p = perm[i] + 2
        target[p], target[i + 2] = target[i + 2], target[p]
    for i in range(55):
        x = target[i + 2]
        y = u8(93 ^ u8(13 * x))
        if x % 2 == 1:
            y ^= 0x80
        target[i + 2] = y
    return target


# --- full pure-Python hashAB -----------------------------------------------------
def calc_hashab(sha1: bytes, uuid: bytes, rnd: bytes) -> bytes:
    """Pure-Python calcHashAB: SHA1(20)+FirewireGuid(8)+rnd(23) -> 57-byte signature."""
    from ._hashab_gen2 import generate_initial_buffer, generate_key_material

    p1 = phase1(build_input_data(sha1, uuid, rnd))
    round_state, cipher_block = derive_round_state(p1)
    target = init_target_rnd(rnd)
    expanded = generate_key_material(p1)
    ibuff = generate_initial_buffer(expanded)
    target[25:57] = phase2(round_state, ibuff, cipher_block)
    final_permute(target)
    return bytes(target)
