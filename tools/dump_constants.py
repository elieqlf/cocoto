"""Décode le « blob » de constantes Nuitka du module __main__ de CoCoBot (noms de fonctions,
paramètres, numéros de ligne, docstrings, chaînes, nombres) — c'est la source de docs/ANALYSE.md.

    python tools/dump_constants.py CoCoBot0.0.27.exe --out re_notes

Écrit re_notes/main_consts.txt (constantes dans l'ordre du source) et re_notes/defs_sorted.txt
(fonctions triées par ligne). Accepte l'exe onefile (l'exe interne est extrait en mémoire) ou l'exe
interne directement.

Format observé (Nuitka 2.x) : entrée de module = nom\\0 + taille uint32 + données ; données =
nombre uint16 puis constantes typées (a/u = str terminée par \\0, w = 1 caractère, s = '', l/q =
entier varint +/-, f = float64, T/L/P/S = tuple/list/set/frozenset, D = dict, n/t/F = None/True/False,
C = code de fonction, W = corps de classe, Y = genexpr, p = constante précédente…)."""
from __future__ import annotations

import argparse
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def inner_exe(path: str) -> bytes:
    data = open(path, "rb").read()
    if b"NUITKA_ONEFILE_PARENT" not in data[-2_000_000:] and b"KAY" not in data[:1_000_000]:
        return data
    import extract_assets
    stream = extract_assets.decompressed_stream(path)
    for name, blob, _crc in extract_assets.iter_entries(stream):
        if "\\" not in name and "/" not in name and name.lower().endswith(".exe"):
            return blob
    return data


def find_main_blob(data: bytes) -> tuple[int, int]:
    """(début des données, taille) du module __main__ : nom suivi d'une taille dont la fin tombe
    sur une autre entrée de module valide."""
    for m in re.finditer(rb"__main__\x00", data):
        e = m.end() - 1
        size = struct.unpack_from("<I", data, e + 1)[0]
        nxt = e + 5 + size
        if 1000 < size < 50_000_000 and nxt < len(data):
            name_end = data.find(b"\x00", nxt, nxt + 200)
            name = data[nxt:name_end]
            if name and re.fullmatch(rb"[A-Za-z0-9_.\-]+", name):
                return e + 5, size
    raise SystemExit("module __main__ introuvable dans le blob de constantes")


class Decoder:
    def __init__(self, data: bytes):
        self.d, self.pos = data, 0

    def varlen(self) -> int:
        r = sh = 0
        while True:
            b = self.d[self.pos]
            self.pos += 1
            r |= (b & 0x7F) << sh
            sh += 7
            if not b & 0x80:
                return r

    def cstr(self) -> bytes:
        j = self.d.index(b"\0", self.pos)
        s = self.d[self.pos:j]
        self.pos = j + 1
        return s

    def code(self, kind: str):
        fl = self.varlen()
        name = self.item()[1] if kind == "C" or kind == "W" else "<genexpr>"
        line = self.varlen()
        varnames = [x[1] for x in self.item()[1]]
        if kind == "C":
            self.varlen()                    # nombre d'arguments
        qual = self.item()[1] if fl & 1 else None
        free = [x[1] for x in self.item()[1]] if fl & 2 else None
        if kind == "C" and fl & 4:
            self.varlen()
        if kind == "C" and fl & 8:
            self.varlen()
        return ("CODE", dict(name=name, line=line, varnames=varnames, qual=qual, free=free, flags=fl))

    def item(self):
        c = chr(self.d[self.pos])
        self.pos += 1
        if c in "au":
            return ("S", self.cstr().decode("utf-8", "replace"))
        if c == "w":
            b = self.d[self.pos]
            n = 1 if b < 0x80 else 2 if b < 0xE0 else 3 if b < 0xF0 else 4
            s = self.d[self.pos:self.pos + n].decode("utf-8", "replace")
            self.pos += n
            return ("S", s)
        if c == "s":
            return ("S", "")
        if c in "vbX":
            n = self.varlen()
            s = self.d[self.pos:self.pos + n]
            self.pos += n
            return ("S", s.decode("utf-8", "replace")) if c == "v" else ("B", bytes(s))
        if c == "c":
            return ("B", self.cstr())
        if c == "d":
            self.pos += 1
            return ("B", self.d[self.pos - 1:self.pos])
        if c == "l":
            return ("I", self.varlen())
        if c == "q":
            return ("I", -self.varlen())
        if c in "gG":
            n = self.varlen()
            for _ in range(n):
                self.varlen()
            return ("I", "<grand entier>")
        if c == "f":
            v = struct.unpack_from("<d", self.d, self.pos)[0]
            self.pos += 8
            return ("F", v)
        if c == "j":
            v = struct.unpack_from("<dd", self.d, self.pos)
            self.pos += 16
            return ("F", complex(*v))
        if c in "TLPSK":
            n = self.varlen()
            return ({"T": "T", "L": "L", "P": "P", "S": "S*", "K": "K"}[c], [self.item() for _ in range(n)])
        if c == "D":
            n = self.varlen()
            return ("D", [(self.item(), self.item()) for _ in range(n)])
        if c in "ntFE":
            return ("N", {"n": None, "t": True, "F": False, "E": "..."}[c])
        if c == "O":
            return ("builtin", self.cstr().decode())
        if c in "MQZ":
            self.pos += 1
            return ("special", self.d[self.pos - 1])
        if c == "p":
            return ("prev", None)
        if c in ":;":
            return ("slice", [self.item(), self.item(), self.item()])
        if c in "CWY":
            return self.code(c)
        raise ValueError(f"type inconnu {c!r} à {self.pos - 1}")


def fmt(it) -> str:
    t, v = it
    if t == "S":
        return repr(v)
    if t in ("T", "L", "P", "S*", "K"):
        return t + "(" + ", ".join(fmt(x) for x in v) + ")"
    if t == "D":
        return "{" + ", ".join(fmt(a) + ": " + fmt(b) for a, b in v) + "}"
    if t == "CODE":
        q = f" qual={v['qual']}" if v["qual"] else ""
        return f"#### DEF {v['name']}({', '.join(map(str, v['varnames']))}) line={v['line']}{q}"
    return f"{t}:{v!r}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("exe")
    ap.add_argument("--out", default="re_notes")
    args = ap.parse_args(argv)
    data = inner_exe(args.exe)
    start, size = find_main_blob(data)
    dec = Decoder(data[start:start + size])
    os.makedirs(args.out, exist_ok=True)
    defs, i = [], 0
    with open(os.path.join(args.out, "main_consts.txt"), "w", encoding="utf-8") as out:
        while dec.pos < size - 1:
            count = struct.unpack_from("<H", dec.d, dec.pos)[0]
            dec.pos += 2
            for _ in range(count):
                it = dec.item()
                out.write(f"{i:05d} {fmt(it)}\n")
                if it[0] == "CODE":
                    defs.append(it[1])
                i += 1
    with open(os.path.join(args.out, "defs_sorted.txt"), "w", encoding="utf-8") as out:
        for d in sorted(defs, key=lambda d: d["line"]):
            q = (d["qual"] + ".") if d["qual"] else ""
            out.write(f"{d['line']} {q}{d['name']} ({', '.join(map(str, d['varnames']))})\n")
    print(f"{i} constantes, {len(defs)} fonctions/classes → {os.path.abspath(args.out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
