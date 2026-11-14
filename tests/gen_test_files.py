"""Generate the fixed test files and record their SHA-256 hashes.

Run once from the repo root:
    python tests/gen_test_files.py

Creates tests/test_1MB.bin and tests/test_10MB.bin (random bytes, fixed seed so
they are the same on every machine) and writes tests/hashes.txt.
"""
import hashlib
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
FILES = {"test_1MB.bin": 1_000_000, "test_10MB.bin": 10_000_000}
SEED = 2026


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main():
    rng = random.Random(SEED)
    lines = []
    for name, size in FILES.items():
        path = HERE / name
        if not path.exists() or path.stat().st_size != size:
            path.write_bytes(rng.randbytes(size))
        else:
            rng.randbytes(size)  # keep the generator in step
        digest = sha256_file(path)
        lines.append(f"{name}  {size}  {digest}")
        print(lines[-1])
    (HERE / "hashes.txt").write_text("\n".join(lines) + "\n")
    print(f"Wrote {HERE / 'hashes.txt'}")


if __name__ == "__main__":
    main()
