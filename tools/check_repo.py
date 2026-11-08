#!/usr/bin/env python3
"""Pre-publication check of the repository contents.

    python tools/check_repo.py              # scan every file git would commit
    python tools/check_repo.py --message F  # also scan a commit message file
    python tools/check_repo.py --hash WORD  # print the hash to add WORD to the list

It looks for:

* words that must not appear in the project (product names, real substance names and
  similar).  The list is stored only as truncated SHA-256 hashes, so the check itself
  does not publish the words it guards against.  Extra private words can be listed, one
  per line, in ``.repo-check-terms.txt`` (ignored by git);
* e-mail addresses, absolute home-directory paths and common token formats;
* files larger than 1 MB, and binary files outside ``assets/``.

Exit status 1 if anything is found.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_TERMS = ROOT / ".repo-check-terms.txt"
MAX_BYTES = 1_000_000
BINARY_OK = {".png", ".jpg", ".jpeg", ".gif", ".ico"}

HASHED_TERMS = {
    "099f00917bc1afb4",
    "0e364c206974b5d9",
    "11b4e8389f1e31cd",
    "128a570bb5b8fcc4",
    "17ad2542900e2065",
    "196f8d5a6b2c431b",
    "24fa74107107be23",
    "2552a9843c49f92b",
    "26d705c13f4e3e7d",
    "2863229379aa76de",
    "31817d49b7a19287",
    "32bcba2242820d07",
    "3a3b8b6d6187c9f8",
    "43f7c210bd0cc1b8",
    "44c1ca33495ec83d",
    "46c5eff0c85b54bc",
    "4978c1d21cf6803f",
    "52a1ed2b9aa943e3",
    "59c1de0763e8bdc6",
    "5c8411654c2cacac",
    "5e8b96c70a3a5341",
    "5f3bcd125e89c868",
    "621391a126b6b417",
    "63c19a56decbecc0",
    "6910dd86e5e374cc",
    "6919ef3b7ee71565",
    "69cdcc7eb4b306e3",
    "6a780680a34fd0aa",
    "6ed9d6a4241b358e",
    "77604c1de5776604",
    "79776e274499f6f3",
    "835dac95bd5bec82",
    "837246b0a01af625",
    "84a33a9382b0102c",
    "868645a03af59110",
    "872d183b85dbc03b",
    "88a2f109b13da155",
    "913822278e279804",
    "934f5873687909f4",
    "99c632369210a007",
    "b47d0768b141fa11",
    "b55ac8822fb0ce94",
    "b5b0a575159553a7",
    "bffe42c79eb4aabf",
    "c0f27a65b1206839",
    "c12502295544e34e",
    "c6131333dd32d284",
    "c6af8303ff46455a",
    "c74a66242143ede0",
    "d42741845745036d",
    "d47c177149c49a68",
    "d9411c44d8f08a20",
    "dbbae1b99a4c320e",
    "e224e66fb84c63ed",
    "e905ac9625c5d81e",
    "ebfd8396e9cacde7",
    "fe4334dfa89e000c",
    "fe8001858c58a8f7",
    "ff2f5af8e933c3a5",
    "ffddc8fe4bc9ed88",
}

PATTERNS = {
    "e-mail address": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z0-9.-]*[A-Za-z]{2,}"),
    "home-directory path": re.compile(r"(/Users/[A-Za-z0-9_.-]+|/home/[A-Za-z0-9_.-]+|[A-Za-z]:\\\\?Users\\\\?)"),
    "access token": re.compile(
        r"(ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9_-]{20,}|xox[abp]-[A-Za-z0-9-]{10,})"
    ),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}
WORD = re.compile(r"[a-z][a-z0-9]*")


def term_hash(word: str) -> str:
    """Truncated SHA-256 of a lower-case word, as stored in ``HASHED_TERMS``."""
    return hashlib.sha256(word.strip().lower().encode()).hexdigest()[:16]


def private_hashes() -> set[str]:
    if not PRIVATE_TERMS.is_file():
        return set()
    return {term_hash(w) for w in PRIVATE_TERMS.read_text(encoding="utf-8").splitlines() if w.strip()}


def candidate_files() -> list[Path]:
    """Every file git would commit: tracked and staged files plus untracked, non-ignored ones."""
    out = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout.decode()
    return sorted({ROOT / p for p in out.split("\0") if p and (ROOT / p).is_file()})


def scan_text(label: str, text: str, hashes: set[str]) -> list[str]:
    problems = []
    for n, line in enumerate(text.splitlines(), 1):
        for word in set(WORD.findall(line.lower())):
            if term_hash(word) in hashes:
                problems.append(f"{label}:{n}: listed word '{word}'")
        for kind, rx in PATTERNS.items():
            for m in rx.finditer(line):
                problems.append(f"{label}:{n}: {kind} '{m.group(0)}'")
    return problems


def scan(message: Path | None = None) -> list[str]:
    hashes = HASHED_TERMS | private_hashes()
    problems = []
    for f in candidate_files():
        rel = f.relative_to(ROOT).as_posix()
        size = f.stat().st_size
        if size > MAX_BYTES:
            problems.append(f"{rel}: file is {size / 1e6:.1f} MB (limit {MAX_BYTES / 1e6:.0f} MB)")
        data = f.read_bytes()
        if b"\0" in data[:8192]:
            if f.suffix.lower() not in BINARY_OK or not rel.startswith("assets/"):
                problems.append(f"{rel}: binary file outside assets/")
            continue
        if rel == "tools/check_repo.py":
            continue  # contains the patterns themselves
        problems += scan_text(rel, data.decode("utf-8", errors="replace"), hashes)
    if message is not None:
        text = "\n".join(
            l
            for l in message.read_text(encoding="utf-8").splitlines()
            if not l.startswith("#") and not l.startswith("Co-Authored-By:")
        )
        problems += scan_text("commit message", text, hashes)
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Check the repository for content that must not be published.")
    ap.add_argument("--message", type=Path, help="also scan this commit message file")
    ap.add_argument("--hash", metavar="WORD", help="print the hash of WORD and exit")
    a = ap.parse_args(argv)
    if a.hash:
        print(term_hash(a.hash))
        return 0
    problems = scan(a.message)
    for p in problems:
        print(p)
    if problems:
        print(f"\n{len(problems)} problem(s) found.")
        return 1
    print("Repository check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
