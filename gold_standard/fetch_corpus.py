#!/usr/bin/env python3
"""
fetch_corpus.py — download the gold-standard corpus and pin/verify checksums (trust-on-first-use).

Usage:
    python -m gold_standard.fetch_corpus            # download missing, verify pinned
    python -m gold_standard.fetch_corpus --force    # re-download all
    python -m gold_standard.fetch_corpus --repin    # re-compute and overwrite pinned checksums

Novice notes
------------
- Files land in gold_standard/corpus/files/. That directory is git-ignored (see .gitignore snippet
  in the package README) so you never commit large/copyrighted PDFs.
- On the FIRST run, each file's SHA-256 is computed and written back into corpus_manifest.yaml.
  Commit that manifest change so every later run (and every teammate) verifies the exact same bytes.
- If a download is blocked (some WHO/IRIS URLs rate-limit bots), the script tells you the mirror_url
  or asks you to download once in a browser into files/. The checksum step still protects you.
- Only dependency beyond the standard library is PyYAML and requests, both already in the backend.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import requests
import yaml

HERE = Path(__file__).resolve().parent
CORPUS_DIR = HERE / "corpus"
MANIFEST_PATH = CORPUS_DIR / "corpus_manifest.yaml"
FILES_DIR = CORPUS_DIR / "files"
CHUNK = 1 << 16
# A browser-like UA; some WHO hosts reject the default python-requests UA.
HEADERS = {"User-Agent": "Mozilla/5.0 (gold-standard-corpus-fetch)"}


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def is_pdf(path: Path) -> bool:
    """Cheap sanity check that we actually got a PDF, not an HTML error page."""
    try:
        with path.open("rb") as f:
            return f.read(5) == b"%PDF-"
    except OSError:
        return False


def download(url: str, dest: Path) -> bool:
    try:
        with requests.get(url, headers=HEADERS, stream=True, timeout=60, allow_redirects=True) as r:
            r.raise_for_status()
            tmp = dest.with_suffix(dest.suffix + ".part")
            with tmp.open("wb") as f:
                for block in r.iter_content(CHUNK):
                    f.write(block)
            tmp.replace(dest)
        return True
    except Exception as exc:  # noqa: BLE001 — surface the reason, keep going to the next doc
        print(f"    download failed: {exc}", file=sys.stderr)
        return False


def load_manifest() -> dict:
    return yaml.safe_load(MANIFEST_PATH.read_text())


def save_manifest(manifest: dict) -> None:
    MANIFEST_PATH.write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True))


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch and checksum-pin the gold corpus.")
    ap.add_argument("--force", action="store_true", help="re-download even if the file exists")
    ap.add_argument("--repin", action="store_true", help="recompute and overwrite pinned checksums")
    args = ap.parse_args()

    FILES_DIR.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()
    ok = True
    changed = False

    # A generated corpus (the default compact manifest) is built once from its committed,
    # deterministic generator rather than downloaded. Build all generated docs up front, then
    # the per-doc loop below just verifies each one's pinned checksum.
    if any(doc.get("source") == "generated" for doc in manifest["documents"]):
        print("Building generated corpus documents (deterministic)...")
        try:
            from gold_standard.corpus.build_compact_corpus import build_all

            build_all(FILES_DIR)
        except ImportError as exc:
            print(
                f"    !! cannot build generated corpus: {exc}. "
                "Install build deps with `pip install reportlab pillow`.",
                file=sys.stderr,
            )
            return 1

    for doc in manifest["documents"]:
        dest = FILES_DIR / doc["filename"]
        print(f"[{doc['id']}] {doc['title']}")

        if doc.get("source") == "generated":
            if not dest.exists():
                print(f"    !! generator did not produce {dest}", file=sys.stderr)
                ok = False
                continue
        elif args.force or not dest.exists():
            urls = [doc["url"]] + ([doc["mirror_url"]] if doc.get("mirror_url") else [])
            got = False
            for url in urls:
                print(f"    downloading: {url}")
                if download(url, dest) and is_pdf(dest):
                    got = True
                    break
                print("    (not a valid PDF or download failed; trying next source)")
            if not got:
                print(
                    f"    !! could not fetch {doc['filename']}.\n"
                    f"    Download it once in a browser from:\n"
                    f"      {doc.get('landing_page', doc['url'])}\n"
                    f"    and place it at: {dest}",
                    file=sys.stderr,
                )
                ok = False
                continue
        elif not is_pdf(dest):
            print(f"    !! existing file is not a valid PDF: {dest}", file=sys.stderr)
            ok = False
            continue

        digest = sha256_of(dest)
        pinned = doc.get("sha256")

        if pinned is None or args.repin:
            doc["sha256"] = digest
            changed = True
            print(f"    pinned sha256 = {digest}")
        elif digest != pinned:
            print(
                f"    !! CHECKSUM MISMATCH — the file changed since it was pinned.\n"
                f"       pinned:   {pinned}\n"
                f"       computed: {digest}\n"
                f"       Your gold answers may no longer match this file. Investigate before trusting scores.",
                file=sys.stderr,
            )
            ok = False
        else:
            print(f"    verified sha256 = {digest}")

    if changed:
        save_manifest(manifest)
        print("\nmanifest updated with newly pinned checksums — commit corpus_manifest.yaml.")

    if not ok:
        print("\nSome documents are missing or failed verification (see messages above).", file=sys.stderr)
        return 1
    print("\nAll corpus documents present and verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
