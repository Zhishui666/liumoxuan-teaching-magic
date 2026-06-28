#!/usr/bin/env python3
"""Minimal Volcengine Doubao streaming ASR smoke test.

Usage:
  python3 scripts/volcengine_streaming_asr_mvp.py --audio path/to/audio.wav
  python3 scripts/volcengine_streaming_asr_mvp.py --make-sample

The script reads .env, converts audio to 16k mono WAV with ffmpeg, streams it to
the Volcengine bigmodel WebSocket endpoint, and writes Markdown output.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import inspect
import json
import os
import struct
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
OUTPUT_DIR = ROOT / "outputs" / "asr"

PROTOCOL_VERSION = 0x1
HEADER_SIZE_WORDS = 0x1
SERIALIZATION_JSON = 0x1
COMPRESSION_GZIP = 0x1

MSG_CLIENT_FULL_REQUEST = 0x1
MSG_CLIENT_AUDIO_ONLY_REQUEST = 0x2
MSG_SERVER_FULL_RESPONSE = 0x9
MSG_SERVER_ACK = 0xB
MSG_SERVER_ERROR = 0xF

FLAG_NO_SEQUENCE = 0x0
FLAG_POS_SEQUENCE = 0x1
FLAG_NEG_SEQUENCE = 0x2


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def mask_secret(value: str) -> str:
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def require_config() -> dict[str, str]:
    load_dotenv(ENV_FILE)

    config = {
        "api_key": env("VOLCENGINE_ASR_API_KEY"),
        "app_key": env("VOLCENGINE_ASR_APP_KEY"),
        "access_key": env("VOLCENGINE_ASR_ACCESS_KEY"),
        "ws_url": env("VOLCENGINE_ASR_WS_URL", "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"),
        "resource_id": env("VOLCENGINE_ASR_RESOURCE_ID", "volc.seedasr.sauc.duration"),
        "uid": env("VOLCENGINE_ASR_UID", "liumoxuan-teaching-magic"),
        "sample_rate": env("VOLCENGINE_ASR_SAMPLE_RATE", "16000"),
        "bits": env("VOLCENGINE_ASR_BITS", "16"),
        "channels": env("VOLCENGINE_ASR_CHANNELS", "1"),
        "chunk_ms": env("VOLCENGINE_ASR_CHUNK_MS", "200"),
    }

    if not config["api_key"] and not (config["app_key"] and config["access_key"]):
        raise SystemExit("Missing VOLCENGINE_ASR_API_KEY, or VOLCENGINE_ASR_APP_KEY + VOLCENGINE_ASR_ACCESS_KEY.")

    return config


def make_header(message_type: int, flags: int) -> bytes:
    return bytes(
        [
            (PROTOCOL_VERSION << 4) | HEADER_SIZE_WORDS,
            (message_type << 4) | flags,
            (SERIALIZATION_JSON << 4) | COMPRESSION_GZIP,
            0x00,
        ]
    )


def encode_packet(message_type: int, payload: bytes, sequence: int | None = None, last: bool = False) -> bytes:
    compressed = gzip.compress(payload)
    if sequence is None:
        flags = FLAG_NO_SEQUENCE
        sequence_bytes = b""
    elif last:
        flags = FLAG_NEG_SEQUENCE
        sequence_bytes = struct.pack(">i", -abs(sequence))
    else:
        flags = FLAG_POS_SEQUENCE
        sequence_bytes = struct.pack(">i", abs(sequence))

    return (
        make_header(message_type, flags)
        + sequence_bytes
        + struct.pack(">I", len(compressed))
        + compressed
    )


def decode_packet(data: bytes) -> dict[str, Any]:
    if len(data) < 4:
        return {"message_type": None, "payload": None, "raw": data}

    header_size = (data[0] & 0x0F) * 4
    message_type = data[1] >> 4
    flags = data[1] & 0x0F
    compression = data[2] & 0x0F
    offset = header_size
    sequence = None

    if flags in {FLAG_POS_SEQUENCE, FLAG_NEG_SEQUENCE} and len(data) >= offset + 4:
        sequence = struct.unpack(">i", data[offset : offset + 4])[0]
        offset += 4

    payload: bytes | None = None
    payload_size = None
    if len(data) >= offset + 4:
        payload_size = struct.unpack(">I", data[offset : offset + 4])[0]
        offset += 4
        payload = data[offset : offset + payload_size]
        if message_type == MSG_SERVER_ERROR and payload_size is not None and len(data) >= offset:
            # Error frames are: 4-byte code + 4-byte payload size + payload.
            error_offset = header_size
            if len(data) >= error_offset + 8:
                code = struct.unpack(">i", data[error_offset : error_offset + 4])[0]
                size = struct.unpack(">I", data[error_offset + 4 : error_offset + 8])[0]
                payload = data[error_offset + 8 : error_offset + 8 + size]
                parsed_error = payload.decode("utf-8", errors="replace")
                return {
                    "message_type": message_type,
                    "flags": flags,
                    "sequence": sequence,
                    "code": code,
                    "payload_size": size,
                    "payload": parsed_error,
                }
        if compression == COMPRESSION_GZIP and payload:
            payload = gzip.decompress(payload)

    parsed = None
    if payload:
        try:
            parsed = json.loads(payload.decode("utf-8"))
        except Exception:
            parsed = payload.decode("utf-8", errors="replace")

    return {
        "message_type": message_type,
        "flags": flags,
        "sequence": sequence,
        "payload_size": payload_size,
        "payload": parsed,
    }


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def make_sample_audio(out_path: Path) -> None:
    text = "这是一次豆包语音识别测试。我们正在验证一备多用适配器的课堂录音输入能力。"
    aiff = out_path.with_suffix(".aiff")
    try:
        run(["say", "-v", "Tingting", "-o", str(aiff), text])
    except Exception:
        run(["say", "-o", str(aiff), text])
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(aiff), str(out_path)])
    aiff.unlink(missing_ok=True)


def convert_to_wav(audio_path: Path, wav_path: Path, sample_rate: int, channels: int) -> None:
    run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(audio_path),
            "-ac",
            str(channels),
            "-ar",
            str(sample_rate),
            "-acodec",
            "pcm_s16le",
            "-f",
            "wav",
            str(wav_path),
        ]
    )


def iter_chunks(wav_path: Path, sample_rate: int, channels: int, chunk_ms: int) -> list[bytes]:
    bytes_per_sample = 2
    chunk_size = int(sample_rate * channels * bytes_per_sample * chunk_ms / 1000)
    data = wav_path.read_bytes()
    return [data[i : i + chunk_size] for i in range(0, len(data), chunk_size) if data[i : i + chunk_size]]


def extract_text(payload: Any) -> tuple[str, list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        return "", []

    result = payload.get("result") or payload.get("payload") or {}
    if not isinstance(result, dict):
        return "", []

    text = result.get("text") or ""
    utterances = result.get("utterances") or []
    return text, utterances if isinstance(utterances, list) else []


async def transcribe(audio_path: Path, config: dict[str, str]) -> dict[str, Any]:
    sample_rate = int(config["sample_rate"])
    channels = int(config["channels"])
    chunk_ms = int(config["chunk_ms"])

    with tempfile.TemporaryDirectory() as tmp:
        wav_path = Path(tmp) / "input.wav"
        convert_to_wav(audio_path, wav_path, sample_rate, channels)
        chunks = iter_chunks(wav_path, sample_rate, channels, chunk_ms)

    request_id = str(uuid.uuid4())
    headers = {
        "X-Api-Resource-Id": config["resource_id"],
        "X-Api-Connect-Id": str(uuid.uuid4()),
        "X-Api-Request-Id": request_id,
        "X-Api-Sequence": "-1",
    }
    if config["api_key"]:
        headers["X-Api-Key"] = config["api_key"]
    else:
        headers["X-Api-App-Key"] = config["app_key"]
        headers["X-Api-Access-Key"] = config["access_key"]

    init_payload = {
        "user": {"uid": config["uid"]},
        "audio": {
            "format": "wav",
            "rate": sample_rate,
            "bits": int(config["bits"]),
            "channel": channels,
            "codec": "raw",
        },
        "request": {
            "model_name": "bigmodel",
            "enable_itn": True,
            "enable_punc": True,
            "show_utterances": True,
        },
    }

    final_text = ""
    utterances: list[dict[str, Any]] = []
    raw_events: list[dict[str, Any]] = []

    connect_kwargs: dict[str, Any] = {"proxy": None}
    connect_params = inspect.signature(websockets.connect).parameters
    if "additional_headers" in connect_params:
        connect_kwargs["additional_headers"] = headers
    else:
        connect_kwargs["extra_headers"] = headers

    async with websockets.connect(config["ws_url"], ping_interval=None, **connect_kwargs) as ws:
        await ws.send(encode_packet(MSG_CLIENT_FULL_REQUEST, json.dumps(init_payload).encode("utf-8"), sequence=1))
        first = decode_packet(await ws.recv())
        raw_events.append(first)

        async def sender() -> None:
            seq = 2
            for index, chunk in enumerate(chunks):
                is_last = index == len(chunks) - 1
                await ws.send(encode_packet(MSG_CLIENT_AUDIO_ONLY_REQUEST, chunk, sequence=seq, last=is_last))
                seq += 1
                if not is_last:
                    await asyncio.sleep(chunk_ms / 1000)

        async def receiver(sender_task: asyncio.Task[None]) -> None:
            nonlocal final_text, utterances
            while True:
                if sender_task.done():
                    timeout = 3
                else:
                    timeout = 15
                try:
                    response = await asyncio.wait_for(ws.recv(), timeout=timeout)
                except asyncio.TimeoutError:
                    if sender_task.done():
                        break
                    continue
                except ConnectionClosed:
                    break

                decoded = decode_packet(response)
                raw_events.append(decoded)
                text, utt = extract_text(decoded.get("payload"))
                if text:
                    final_text = text
                if utt:
                    utterances = utt
                if decoded.get("message_type") == MSG_SERVER_ERROR:
                    break

        sender_task = asyncio.create_task(sender())
        await receiver(sender_task)
        await sender_task

    return {
        "request_id": request_id,
        "audio_path": str(audio_path),
        "final_text": final_text,
        "utterances": utterances,
        "raw_events": raw_events,
    }


def write_outputs(result: dict[str, Any]) -> tuple[Path, Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    json_path = OUTPUT_DIR / f"volcengine-asr-{stamp}.json"
    md_path = OUTPUT_DIR / f"volcengine-transcript-{stamp}.md"

    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    text = result.get("final_text") or ""
    lines = [
        "# 火山引擎豆包流式 ASR MVP 验证",
        "",
        f"- 音频：`{result.get('audio_path')}`",
        f"- Request ID：`{result.get('request_id')}`",
        "",
        "## 转写结果",
        "",
        text or "[未获得转写文本]",
        "",
    ]
    utterances = result.get("utterances") or []
    if utterances:
        lines.extend(["## 分句", ""])
        for item in utterances:
            start = item.get("start_time", "")
            end = item.get("end_time", "")
            line_text = item.get("text", "")
            lines.append(f"- `{start}-{end}` {line_text}")
        lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path, json_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a minimal Volcengine streaming ASR smoke test.")
    parser.add_argument("--audio", type=Path, help="Path to a local audio file.")
    parser.add_argument("--make-sample", action="store_true", help="Generate a short Chinese sample audio with macOS say.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    audio_path = args.audio
    if args.make_sample:
        audio_path = OUTPUT_DIR / "sample-zh.wav"
        make_sample_audio(audio_path)

    if not audio_path:
        test_audio = env("VOLCENGINE_ASR_TEST_AUDIO_PATH")
        audio_path = Path(test_audio) if test_audio else None

    if not audio_path:
        print("Provide --audio path/to/file.wav or use --make-sample.", file=sys.stderr)
        return 2
    if not audio_path.exists():
        print(f"Audio file not found: {audio_path}", file=sys.stderr)
        return 2

    config = require_config()
    auth = "api_key" if config["api_key"] else "app_key/access_key"
    print(f"Using {auth}; ws={config['ws_url']}; resource={config['resource_id']}")
    if config["api_key"]:
        print(f"API key: {mask_secret(config['api_key'])}")

    result = asyncio.run(transcribe(audio_path, config))
    md_path, json_path = write_outputs(result)
    print(f"Markdown: {md_path}")
    print(f"JSON: {json_path}")
    print(f"Text: {result.get('final_text') or '[empty]'}")
    return 0 if result.get("final_text") else 1


if __name__ == "__main__":
    raise SystemExit(main())
