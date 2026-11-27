"""Extrait les ressources (templates d'images, modèles EasyOCR) d'un exécutable Nuitka « onefile ».

Usage :
    python tools/extract_assets.py CoCoBot0.0.27.exe [--out assets] [--all]

Format observé (Nuitka onefile, Windows) :
    - la charge utile commence par l'en-tête  b"KA" + b"Y" (flux zstd) ou b"X" (non compressé) ;
    - le flux décompressé est une suite d'entrées :
        nom de fichier UTF-16LE terminé par \\0\\0, taille uint64 LE, CRC32 uint32 LE, données ;
    - un nom vide termine l'archive.

Par défaut seuls `img/` et `EasyOCR/` sont extraits (le reste = Python, torch, DLL…).
Les fichiers extraits restent ceux de TA copie du programme : ne les redistribue pas.
"""
from __future__ import annotations

import argparse
import mmap
import os
import struct
import sys
import zlib

KEEP_DEFAULT = ("img/", "EasyOCR/")


def find_payload(m: mmap.mmap) -> tuple[int, bool]:
    """Position du flux et s'il est compressé. Cherche b'KAY' suivi de la signature zstd."""
    zstd_magic = b"\x28\xb5\x2f\xfd"
    pos = 0
    while True:
        i = m.find(b"KA", pos)
        if i < 0:
            raise ValueError("en-tête Nuitka onefile 'KA' introuvable")
        flag = m[i + 2:i + 3]
        if flag == b"Y" and m[i + 3:i + 7] == zstd_magic:
            return i + 3, True
        if flag == b"X" and m[i + 3:i + 5] != b"\0\0":
            # nom UTF-16 du premier fichier : caractère ASCII suivi de \0
            if m[i + 4:i + 5] == b"\0" and 32 <= m[i + 3] < 127:
                return i + 3, False
        pos = i + 2


def decompressed_stream(path: str):
    f = open(path, "rb")
    m = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
    start, compressed = find_payload(m)
    if not compressed:
        return memoryview(m)[start:]
    try:
        import zstandard  # type: ignore
    except ImportError:
        zstandard = None
    if zstandard is not None:
        dctx = zstandard.ZstdDecompressor()
        reader = dctx.stream_reader(memoryview(m)[start:], read_across_frames=False)
        parts = []
        while True:
            try:
                chunk = reader.read(1 << 24)
            except zstandard.ZstdError:
                # zstandard >= 0.23 tente de lire au-delà de la trame (données de fin de l'exe)
                if parts:
                    break
                raise
            if not chunk:
                break
            parts.append(chunk)
        return b"".join(parts)
    import shutil
    import subprocess
    exe = shutil.which("zstd")
    if not exe:
        raise SystemExit("Installe le module 'zstandard' (pip install zstandard) ou l'outil 'zstd'.")
    out = subprocess.run([exe, "-d", "-c"], input=m[start:], capture_output=True)
    if not out.stdout:
        raise SystemExit("décompression zstd impossible : " + out.stderr.decode(errors="replace"))
    return out.stdout


def iter_entries(data):
    pos = 0
    n = len(data)
    while pos < n:
        end = pos
        while end + 1 < n and not (data[end] == 0 and data[end + 1] == 0):
            end += 2
        name = bytes(data[pos:end]).decode("utf-16-le")
        pos = end + 2
        if not name:
            return
        size = struct.unpack_from("<Q", data, pos)[0]
        crc = struct.unpack_from("<I", data, pos + 8)[0]
        pos += 12
        blob = bytes(data[pos:pos + size])
        pos += size
        yield name, blob, crc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("exe")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "assets"))
    ap.add_argument("--all", action="store_true", help="tout extraire (≈ 850 Mo)")
    args = ap.parse_args(argv)
    out = os.path.abspath(args.out)
    data = decompressed_stream(args.exe)
    count = bad = 0
    for name, blob, crc in iter_entries(data):
        rel = os.path.normpath(name.replace("\\", "/")).lstrip("/")
        if rel.startswith("..") or os.path.isabs(rel):
            continue
        if (zlib.crc32(blob) & 0xFFFFFFFF) != crc:
            bad += 1
        if not args.all and not rel.replace(os.sep, "/").startswith(KEEP_DEFAULT):
            continue
        dest = os.path.join(out, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(blob)
        count += 1
    print(f"{count} fichiers extraits dans {out} (CRC faux : {bad})")
    return 0 if count else 1


if __name__ == "__main__":
    sys.exit(main())
