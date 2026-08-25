"""Shared utilities: throttled + cached EDGAR HTTP client, paths, logging.

Every byte fetched from EDGAR lands in data/raw/ and is never refetched.
SEC fair-access rules: descriptive User-Agent with a contact, <= 10 req/sec.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from datetime import date, datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
INTERIM = ROOT / "data" / "interim"
OUTPUT = ROOT / "output"
NOTE = ROOT / "note"

USER_AGENT = "Yale MAM BootCamp research project"
MIN_INTERVAL = 0.15  # seconds between requests; well under the 10 req/sec cap

_last_request = 0.0

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("bdc")


def cache_name(url: str) -> str:
    """Readable, collision-free cache filename for a URL."""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", url.split("//", 1)[-1])[-120:]
    return f"{hashlib.sha256(url.encode()).hexdigest()[:10]}_{slug}"


def fetch(url: str, subdir: str = "") -> bytes:
    """Fetch a URL through the on-disk cache. Returns raw bytes."""
    global _last_request
    target_dir = RAW / subdir if subdir else RAW
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / cache_name(url)
    if path.exists():
        log.info("cache hit  %s", url)
        return path.read_bytes()

    wait = MIN_INTERVAL - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    log.info("fetching   %s", url)
    resp = requests.get(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"}, timeout=60)
    _last_request = time.monotonic()
    resp.raise_for_status()
    path.write_bytes(resp.content)
    return resp.content


def fetch_json(url: str, subdir: str = "") -> dict:
    return json.loads(fetch(url, subdir))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_date(text: str) -> date | None:
    """Parse a filing-style date. Returns None when nothing date-like is found.

    Handles prose headers: 'As of June 30, 2026', 'December 31, 2025 (audited)',
    non-breaking spaces, and ISO dates.
    """
    if not text:
        return None
    clean = text.replace("\xa0", " ").replace("’", "'")
    clean = re.sub(r"\s+", " ", clean).strip()
    iso = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", clean)
    if iso:
        return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
    m = re.search(
        r"\b(January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+(\d{1,2})\s*,?\s*(\d{4})\b",
        clean,
        re.I,
    )
    if m:
        return datetime.strptime(f"{m.group(1).title()} {m.group(2)} {m.group(3)}", "%B %d %Y").date()
    return None


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str))
