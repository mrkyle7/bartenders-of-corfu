#!/usr/bin/env python3
"""Generate or edit images with Gemini "Nano Banana" image models.

Stdlib only, so it runs with plain `python3` or `uv run` without new deps.

Examples:
    nano_banana.py "flat icon of a lemon wedge, transparent background" -o out/lemon.png
    nano_banana.py "restyle as a Greek taverna menu board" -i shot.png -o out/mock.png --aspect 16:9
    nano_banana.py "three variations of a karaoke card" -n 3 -o out/karaoke.png

API key is read from GEMINI_API_KEY or GOOGLE_API_KEY, falling back to the
repo's .env file. The key is never printed.
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_MODEL = os.environ.get("NANO_BANANA_MODEL", "gemini-2.5-flash-image")
API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
ASPECTS = ["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"]
KEY_VARS = ("GEMINI_API_KEY", "GOOGLE_API_KEY")


def find_api_key() -> str | None:
    for var in KEY_VARS:
        if os.environ.get(var):
            return os.environ[var]
    for parent in [Path.cwd(), *Path.cwd().parents]:
        env_file = parent / ".env"
        if env_file.is_file():
            for line in env_file.read_text().splitlines():
                name, _, value = line.partition("=")
                if name.strip() in KEY_VARS and value.strip():
                    return value.strip().strip("\"'")
            break
    return None


def ssl_context() -> ssl.SSLContext:
    """Default context, falling back to certifi or the macOS system bundle.

    python.org builds of Python on macOS ship without CA certs until
    "Install Certificates.command" is run.
    """
    ctx = ssl.create_default_context()
    if ctx.cert_store_stats()["x509_ca"]:
        return ctx
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    if Path("/etc/ssl/cert.pem").is_file():
        return ssl.create_default_context(cafile="/etc/ssl/cert.pem")
    return ctx


def image_part(path: Path) -> dict:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    data = base64.b64encode(path.read_bytes()).decode()
    return {"inline_data": {"mime_type": mime, "data": data}}


def generate(
    key: str, model: str, prompt: str, inputs: list[Path], aspect: str | None
) -> tuple[list[tuple[str, bytes]], str]:
    parts: list[dict] = [{"text": prompt}] + [image_part(p) for p in inputs]
    config: dict = {"responseModalities": ["TEXT", "IMAGE"]}
    if aspect:
        config["imageConfig"] = {"aspectRatio": aspect}
    body = json.dumps({"contents": [{"parts": parts}], "generationConfig": config})
    req = urllib.request.Request(
        API_URL.format(model=model),
        data=body.encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
    )
    try:
        with urllib.request.urlopen(req, timeout=180, context=ssl_context()) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as e:
        sys.exit(
            f"Gemini API error {e.code}: {e.read().decode(errors='replace')[:800]}"
        )

    images: list[tuple[str, bytes]] = []
    text: list[str] = []
    for cand in payload.get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            blob = part.get("inlineData") or part.get("inline_data")
            if blob:
                mime = blob.get("mimeType") or blob.get("mime_type") or "image/png"
                images.append((mime, base64.b64decode(blob["data"])))
            elif part.get("text"):
                text.append(part["text"])
    if not images:
        reason = payload.get("promptFeedback") or [
            c.get("finishReason") for c in payload.get("candidates", [])
        ]
        sys.exit(f"No image returned. Model said: {' '.join(text) or '-'} ({reason})")
    return images, " ".join(text)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "prompt", help="What to generate, or how to edit the input image(s)"
    )
    ap.add_argument(
        "-i",
        "--input",
        action="append",
        type=Path,
        default=[],
        help="Reference/source image (repeatable). Enables edit/restyle mode.",
    )
    ap.add_argument(
        "-o",
        "--out",
        type=Path,
        required=True,
        help="Output path. With -n > 1, a -1, -2... suffix is added.",
    )
    ap.add_argument(
        "-n",
        "--count",
        type=int,
        default=1,
        help="Number of variations (separate calls)",
    )
    ap.add_argument("--aspect", choices=ASPECTS, help="Aspect ratio of the output")
    ap.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Model id (default {DEFAULT_MODEL}; e.g. gemini-3-pro-image-preview for Nano Banana Pro)",
    )
    args = ap.parse_args()

    key = find_api_key()
    if not key:
        sys.exit(
            "No API key. Set GEMINI_API_KEY (get one at https://aistudio.google.com/apikey) "
            "or add GEMINI_API_KEY=... to the repo .env"
        )
    for p in args.input:
        if not p.is_file():
            sys.exit(f"Input image not found: {p}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for run in range(1, args.count + 1):
        images, text = generate(key, args.model, args.prompt, args.input, args.aspect)
        for idx, (mime, data) in enumerate(images, 1):
            ext = mimetypes.guess_extension(mime) or ".png"
            suffix = ""
            if args.count > 1:
                suffix += f"-{run}"
            if len(images) > 1:
                suffix += f"-{idx}"
            path = args.out.with_name(f"{args.out.stem}{suffix}{ext}")
            path.write_bytes(data)
            written.append(path)
        if text:
            print(f"[model note] {text}", file=sys.stderr)
    for path in written:
        print(path)


if __name__ == "__main__":
    main()
