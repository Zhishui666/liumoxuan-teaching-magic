#!/usr/bin/env python3
"""Check local Volcengine Doubao streaming ASR configuration without calling the API."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"

PLACEHOLDERS = {"", "...", "your_api_key", "your_app_key", "your_access_key"}

REQUIRED_API_KEY = [
    "VOLCENGINE_ASR_API_KEY",
]

REQUIRED_APP_ACCESS = [
    "VOLCENGINE_ASR_APP_KEY",
    "VOLCENGINE_ASR_ACCESS_KEY",
]

RECOMMENDED = [
    "VOLCENGINE_ASR_RESOURCE_ID",
    "VOLCENGINE_ASR_WS_URL",
    "VOLCENGINE_ASR_UID",
    "VOLCENGINE_ASR_AUDIO_FORMAT",
    "VOLCENGINE_ASR_SAMPLE_RATE",
    "VOLCENGINE_ASR_BITS",
    "VOLCENGINE_ASR_CHANNELS",
    "VOLCENGINE_ASR_CHUNK_MS",
]

OPTIONAL = [
    "VOLCENGINE_ASR_TEST_AUDIO_PATH",
]


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def value_is_set(name: str) -> bool:
    value = os.environ.get(name, "").strip()
    return bool(value) and value.lower() not in PLACEHOLDERS


def mask(value: str) -> str:
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def check_url(name: str, url: str) -> list[str]:
    warnings: list[str] = []
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        warnings.append(f"{name} should be an HTTP/HTTPS URL.")
    if any(ch.isspace() for ch in url):
        warnings.append(f"{name} contains whitespace.")
    if any(ord(ch) > 127 for ch in url):
        warnings.append(f"{name} contains non-ASCII characters; avoid Chinese paths in signed URLs.")
    return warnings


def print_var(name: str, secret: bool = False) -> None:
    value = os.environ.get(name, "")
    state = "OK" if value_is_set(name) else "MISSING"
    if not value_is_set(name):
        shown = "-"
    elif secret:
        shown = mask(value)
    else:
        shown = value
    print(f"  {state:7} {name} {shown}")


def main() -> int:
    load_dotenv(ENV_FILE)

    print(f"Project: {ROOT}")
    print(f".env: {'found' if ENV_FILE.exists() else 'not found'}")
    print()

    print("Authentication")
    print_var("VOLCENGINE_ASR_API_KEY", secret=True)
    print_var("VOLCENGINE_ASR_APP_KEY", secret=True)
    print_var("VOLCENGINE_ASR_ACCESS_KEY", secret=True)

    print("\nRecommended")
    for name in RECOMMENDED:
        print_var(name)

    print("\nOptional")
    for name in OPTIONAL:
        print_var(name)

    warnings: list[str] = []
    ws_url = os.environ.get("VOLCENGINE_ASR_WS_URL", "").strip()
    if ws_url:
        parsed = urlparse(ws_url)
        if parsed.scheme != "wss":
            warnings.append("VOLCENGINE_ASR_WS_URL should use wss://.")
    resource_id = os.environ.get("VOLCENGINE_ASR_RESOURCE_ID", "").strip()
    if resource_id and resource_id != "volc.seedasr.sauc.duration":
        warnings.append("VOLCENGINE_ASR_RESOURCE_ID is not the MVP default volc.seedasr.sauc.duration.")

    audio_format = os.environ.get("VOLCENGINE_ASR_AUDIO_FORMAT", "").strip()
    if audio_format and audio_format != "wav":
        warnings.append("Streaming ASR MVP expects wav; convert source audio to 16k mono WAV before sending.")
    bits = os.environ.get("VOLCENGINE_ASR_BITS", "").strip()
    if bits and bits != "16":
        warnings.append("VOLCENGINE_ASR_BITS should be 16 for the streaming MVP.")
    channels = os.environ.get("VOLCENGINE_ASR_CHANNELS", "").strip()
    if channels and channels not in {"1", "2"}:
        warnings.append("VOLCENGINE_ASR_CHANNELS should be 1 or 2.")
    sample_rate = os.environ.get("VOLCENGINE_ASR_SAMPLE_RATE", "").strip()
    if sample_rate and sample_rate != "16000":
        warnings.append("VOLCENGINE_ASR_SAMPLE_RATE maps to API audio.rate and should be 16000.")

    has_api_key = all(value_is_set(name) for name in REQUIRED_API_KEY)
    has_app_access = all(value_is_set(name) for name in REQUIRED_APP_ACCESS)
    missing_recommended = [name for name in RECOMMENDED if not value_is_set(name)]

    print("\nResult")
    if has_api_key:
        print("  PASS: Streaming ASR API Key is present.")
    elif has_app_access:
        print("  PASS: Streaming ASR App Key + Access Key are present.")
    else:
        print("  FAIL: Set VOLCENGINE_ASR_API_KEY, or set both VOLCENGINE_ASR_APP_KEY and VOLCENGINE_ASR_ACCESS_KEY.")

    if missing_recommended:
        print("  WARN: Missing recommended variables:")
        for name in missing_recommended:
            print(f"    - {name}")

    if warnings:
        print("  WARN: Additional checks:")
        for item in warnings:
            print(f"    - {item}")

    print("\nReminder")
    print("  Keep .env local; .gitignore already excludes .env and .env.*.")
    print("  Streaming MVP expects 16kHz mono 16-bit WAV chunks, usually 100-200ms each.")

    return 0 if (has_api_key or has_app_access) else 1


if __name__ == "__main__":
    sys.exit(main())
