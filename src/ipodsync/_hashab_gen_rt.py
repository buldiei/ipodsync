"""Runtime for the transpiled generate_* functions of hashAB.

`U32` reproduces the semantics of C's 32-bit unsigned arithmetic: every operation
is masked to 2^32, `>>` is a logical shift (in the source all shifts are unsigned),
and `__index__` lets a value be used as a list index. The transpiler
(tools/transpile_hashab.py) emits nearly literal Python where every literal is
U32(...), and this class holds the semantics. The generate_buffer_from_state_mixing
helpers are ported by hand (they're short).
"""
from __future__ import annotations

MASK = 0xFFFFFFFF


def _v(x) -> int:
    return x.v if isinstance(x, U32) else (x & MASK)


# --- narrow C casts (NOT identity: truncation/sign extension) --------------------
def u8c(x): return U32(_v(x) & 0xFF)
def u16c(x): return U32(_v(x) & 0xFFFF)


def i8c(x):
    b = _v(x) & 0xFF
    return U32(b - 0x100 if b & 0x80 else b)


def i16c(x):
    w = _v(x) & 0xFFFF
    return U32(w - 0x10000 if w & 0x8000 else w)


# --- byte_helpers.h macros ------------------------------------------------------
def LOBYTE(x): return U32(_v(x) & 0xFF)
def BYTE1(x): return U32((_v(x) >> 8) & 0xFF)
def BYTE2(x): return U32((_v(x) >> 16) & 0xFF)
def HIBYTE(x): return U32((_v(x) >> 24) & 0xFF)
def LOWORD(x): return U32(_v(x) & 0xFFFF)
def HIWORD(x): return U32((_v(x) >> 16) & 0xFFFF)


class U32:
    __slots__ = ("v",)

    def __init__(self, v: int):
        self.v = (v.v if type(v) is U32 else v) & MASK

    # arithmetic (all results mod 2^32; sign doesn't matter for + - * ^ & | ~ <<)
    def __add__(s, o): return U32(s.v + _v(o))
    def __radd__(s, o): return U32(_v(o) + s.v)
    def __sub__(s, o): return U32(s.v - _v(o))
    def __rsub__(s, o): return U32(_v(o) - s.v)
    def __mul__(s, o): return U32(s.v * _v(o))
    def __rmul__(s, o): return U32(_v(o) * s.v)
    def __and__(s, o): return U32(s.v & _v(o))
    def __rand__(s, o): return U32(s.v & _v(o))
    def __or__(s, o): return U32(s.v | _v(o))
    def __ror__(s, o): return U32(s.v | _v(o))
    def __xor__(s, o): return U32(s.v ^ _v(o))
    def __rxor__(s, o): return U32(s.v ^ _v(o))
    def __lshift__(s, o): return U32(s.v << _v(o))
    def __rlshift__(s, o): return U32(_v(o) << s.v)
    def __rshift__(s, o): return U32(s.v >> _v(o))   # logical (s.v >= 0)
    def __rrshift__(s, o): return U32(_v(o) >> s.v)
    def __floordiv__(s, o): return U32(s.v // _v(o))  # unsigned division
    def __rfloordiv__(s, o): return U32(_v(o) // s.v)
    def __truediv__(s, o): return U32(s.v // _v(o))
    def __rtruediv__(s, o): return U32(_v(o) // s.v)
    def __mod__(s, o): return U32(s.v % _v(o))
    def __rmod__(s, o): return U32(_v(o) % s.v)
    def __neg__(s): return U32(-s.v)
    def __invert__(s): return U32(~s.v)

    def __index__(s): return s.v
    def __int__(s): return s.v
    def __eq__(s, o): return s.v == _v(o)
    def __hash__(s): return hash(s.v)
    def __repr__(s): return f"U32(0x{s.v:08x})"


# --- InputSeed + make_seed (from generate_buffer_from_state_mixing.c) ------------
class InputSeed:
    __slots__ = ("raw", "doubled", "masked_and", "masked_or", "init")


def make_seed(value) -> InputSeed:
    value = U32(value)
    doubled = value * 2 + U32(0xD1EB870E)
    s = InputSeed()
    s.raw = value
    s.doubled = doubled
    s.masked_and = doubled & U32(0xA50FF288)
    s.masked_or = doubled | U32(0xA50FF288)
    s.init = U32(0x44824335) + (U32(-0x2D7806BC) ^ (U32(-0x170A3C79) + value))
    return s


# --- helper functions (ported by hand; they contain no shifts/divisions) --------
_SLOT_MUL = U32(-0x362C9C11)
_SLOT_INV = U32(0x362C9C11)
_COEFF_XOR = U32(0x49D363EF)
_SLOT_INNER_MUL = U32(-0x1E6C2B0F)
_COEFF_AND = U32(0x6C593822)
_INNER_CONST_AND = U32(-0x2E079947)


def slot_mix_add(slot_value, mix_value, mix_mask, offset, tweak):
    diff = (mix_mask - mix_value) * 2 + tweak
    gate = diff & (slot_value * U32(0x3CD8561E) + U32(0x5C0F3290))
    return (offset - slot_value) + mix_value * _SLOT_MUL + mix_mask * _SLOT_INV + gate * _SLOT_MUL


def slot_mix_or(slot_value, term1, term2, offset):
    return slot_value + offset + term1 + (term2 | (slot_value * U32(-0x3CD8561E) + U32(0xA3F0CD6F))) * _SLOT_MUL


def slot_mix_xor(slot_value, term1, term2, offset, xor_const, inner_const):
    return offset - _COEFF_XOR * (xor_const ^ (inner_const + term1 + slot_value * _SLOT_INNER_MUL + term2 * 2))


def slot_mix_and(slot_value, term1_outer, term1_inner, term2, offset, mask):
    return (offset + slot_value + term1_outer + (_COEFF_AND * term2)
            - _COEFF_AND * (mask & (_INNER_CONST_AND + term1_inner + slot_value * _SLOT_INNER_MUL + term2 * 2)))


def masked_step(value, addend, bias, mask):
    nxt = value + addend
    gated = (value * 2 + bias) & mask
    return nxt - gated


def masked_gate(value, gate_bias, mask):
    return (value * 2 + gate_bias) & mask
