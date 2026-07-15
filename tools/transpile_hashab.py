#!/usr/bin/env python3
"""Transpiler for decompiled C (dstaley/hashab) -> Python on top of the U32 runtime.

Handles a regular subset: declarations/assignments `TYPE v = expr;`, `v |= expr;`,
`arr[i] = f(...);`, a single seed-initialization for loop, `return;`. 32-bit casts
are dropped (in the U32 model they are identity), numeric literals are wrapped in U32(...),
the rest is carried over verbatim; the semantics of 32-bit overflow and logical
shifts are handled by the runtime (_hashab_gen_rt.U32).

    python tools/transpile_hashab.py <src.c> <func_name> > out.py
Validated by comparison against instrumented C — see tests/test_hashab_port.py.
"""
from __future__ import annotations

import re
import sys

# 32-bit casts — identity in the U32 model (dropped)
CAST = re.compile(r"\((?:int|int32_t|uint32_t|unsigned int|unsigned|size_t)\)")
# narrow casts — NOT identity: truncation/sign -> wrappers u8c/i8c/u16c/i16c
NARROW = {"uint8_t": "u8c", "int8_t": "i8c", "uint16_t": "u16c", "int16_t": "i16c"}
NARROW_RE = re.compile(r"\((uint8_t|int8_t|uint16_t|int16_t)\)")
HEX = re.compile(r"(?<![\w.])0[xX][0-9a-fA-F]+[uUlL]*(?![\w])")
DEC = re.compile(r"(?<![\w.])\d+[uUlL]*(?![\w.])")
TYPES = ("int32_t", "uint32_t", "int8_t", "uint8_t", "int16_t", "uint16_t",
         "unsigned int", "unsigned", "size_t", "int")


def _wrap_num(m: re.Match) -> str:
    tok = m.group(0).rstrip("uUlL")
    return f"U32({tok})"


DEREF = re.compile(r"\*\s*(param_[12])\b")


def _match_bracket(s: str, i: int) -> int:
    """Index right after the bracket matching the opening s[i] ('(' or '[')."""
    close = ")" if s[i] == "(" else "]"
    depth = 0
    while i < len(s):
        if s[i] in "([":
            depth += 1
        elif s[i] in ")]":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return i


def _grab_operand(s: str, i: int) -> int:
    """End of the cast's unary operand, starting from position i."""
    while i < len(s) and s[i] in "-~ ":
        i += 1
    if i < len(s) and s[i] in "(":
        return _match_bracket(s, i)
    while i < len(s) and (s[i].isalnum() or s[i] == "_"):
        i += 1
    while i < len(s) and s[i] in "[(.":       # indices/calls/fields
        if s[i] in "([":
            i = _match_bracket(s, i)
        else:  # .field
            i += 1
            while i < len(s) and (s[i].isalnum() or s[i] == "_"):
                i += 1
    return i


def _apply_narrow_casts(s: str) -> str:
    m = NARROW_RE.search(s)
    while m:
        fn = NARROW[m.group(1)]
        opstart = m.end()
        while opstart < len(s) and s[opstart] == " ":
            opstart += 1
        opend = _grab_operand(s, opstart)
        s = s[:m.start()] + f"{fn}({s[opstart:opend]})" + s[opend:]
        m = NARROW_RE.search(s)
    return s


def transpile_expr(e: str) -> str:
    e = DEREF.sub(r"\1[0]", e)            # *param_2 == param_2[0]
    e = _apply_narrow_casts(e)           # (uint8_t)x -> u8c(x) etc.
    e = CAST.sub("", e)                  # (int)/(uint32_t) — identity, remove
    e = HEX.sub(_wrap_num, e)
    e = DEC.sub(_wrap_num, e)
    return e.strip()


def split_type(s: str):
    """(type|None, remainder) — strips the leading declaration type."""
    s = s.strip()
    for t in (*NARROW, *TYPES):
        if s.startswith(t + " "):
            return t, s[len(t) + 1:].lstrip()
    return None, s


def strip_type(s: str) -> str:
    return split_type(s)[1]


SET_MACRO = {"SET_LOBYTE": (0xFFFFFF00, 0), "SET_BYTE1": (0xFFFF00FF, 8),
             "SET_BYTE2": (0xFF00FFFF, 16), "SET_HIBYTE": (0x00FFFFFF, 24)}
CALL_STMT = re.compile(r"^[A-Za-z_]\w*\s*\(")


def _split_args(s: str) -> list[str]:
    """Split arguments on top-level commas."""
    args, depth, cur = [], 0, ""
    for ch in s:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == "," and depth == 0:
            args.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        args.append(cur)
    return args


def _wrap_byte_write(plhs: str, prhs: str, byte_arrays) -> str:
    m = re.match(r"(\w+)\[", plhs)
    if m and m.group(1) in byte_arrays:
        return f"int(u8c({prhs})) & 0xFF"
    return prhs


def emit_statements(text: str, indent: str = "    ", narrow=None, byte_arrays=()) -> list[str]:
    """Transpile a sequence of straight-line C assignments.

    Tracks narrow types (truncation), expands SET_LOBYTE/SET_BYTEn,
    preserves statement calls (gbsm/mix/…), truncates writes into byte arrays
    (byte_arrays). narrow — shared var->fn dict.
    """
    if narrow is None:
        narrow = {}
    COMPOUND = re.compile(r"^([^=<>!]*?)\s*(<<|>>|[&|+\-*^])=\s*(.*)$", re.DOTALL)
    PTRDECL = re.compile(r"^(const\s+)?(int|int32_t|uint32_t|uint8_t|int8_t|"
                         r"uint16_t|int16_t|unsigned int|unsigned|size_t)\s*\*")
    out = []
    for raw in text.split(";"):
        stmt = raw.strip().strip("{}").strip()   # strip scope braces
        if not stmt or stmt == "return":
            continue
        if PTRDECL.match(stmt):                  # alias pointer (usage already substituted)
            continue
        setm = re.match(r"(SET_\w+)\((.*)\)$", stmt, re.DOTALL)
        if setm and setm.group(1) in SET_MACRO:
            mask, sh = SET_MACRO[setm.group(1)]
            var, val = _split_args(setm.group(2))
            pvar = transpile_expr(var.strip())
            pval = f"u8c({transpile_expr(val.strip())})"
            if sh:
                pval = f"({pval} << U32({sh}))"
            out.append(f"{indent}{pvar} = ({pvar} & U32({hex(mask)})) | {pval}")
            continue
        cop = None
        cm = COMPOUND.match(stmt)
        if cm:
            lhs, cop, rhs = cm.group(1), cm.group(2), cm.group(3)
        elif "=" in stmt:
            lhs, rhs = stmt.split("=", 1)
        else:
            typ, name = split_type(stmt)
            if typ in NARROW:
                narrow[name.strip()] = NARROW[typ]
            elif CALL_STMT.match(stmt):        # statement call (side-effect)
                out.append(f"{indent}{transpile_expr(stmt)}")
            continue
        typ, lhs_name = split_type(lhs)
        if typ in NARROW:
            narrow[lhs_name.strip()] = NARROW[typ]
        rhs = rhs.strip()
        if rhs == "":
            continue
        plhs = transpile_expr(lhs_name)
        prhs = transpile_expr(rhs)
        if cop:
            prhs = f"{plhs} {cop} ({prhs})"
        if re.fullmatch(r"\w+", plhs) and plhs in narrow:
            prhs = f"{narrow[plhs]}({prhs})"
        prhs = _wrap_byte_write(plhs, prhs, byte_arrays)
        out.append(f"{indent}{plhs} = {prhs}")
    return out


def extract_body(src: str, func: str) -> str:
    m = re.search(r"\b" + re.escape(func) + r"\s*\([^)]*\)\s*\{", src)
    if not m:
        raise SystemExit(f"function {func} not found")
    i = m.end()
    depth = 1
    start = i
    while depth:
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
        i += 1
    return src[start:i - 1]


def transpile(src: str, func: str) -> str:
    body = extract_body(src, func)
    # drop comments
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL)
    body = re.sub(r"//[^\n]*", "", body)
    # drop the seed array decl and the init for loop -> replace with Python
    body = re.sub(r"InputSeed\s+seed\s*\[\s*16\s*\]\s*;", "", body)
    body = re.sub(r"for\s*\([^)]*\)\s*\{\s*seed\[\w+\]\s*=\s*make_seed\([^)]*\)\s*;\s*\}",
                  "", body)

    out = ["    seed = [make_seed(param_1[i]) for i in range(16)]"]
    out += emit_statements(body)
    return "\n".join(out)


def main() -> int:
    src = open(sys.argv[1]).read()
    func = sys.argv[2]
    print(transpile(src, func))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
