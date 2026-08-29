"""Teste bruto da Video API: imagem sem pessoas, para isolar politica de conteudo."""

from __future__ import annotations

import io
import json
import subprocess
import time

import httpx
from PIL import Image, ImageDraw

BASE = "https://hiro-foundry-resource.services.ai.azure.com/openai/v1/videos"
PARAMS = {"api-version": "preview"}


def token() -> str:
    out = subprocess.run(
        ["az", "account", "get-access-token", "--resource", "https://cognitiveservices.azure.com", "-o", "json"],
        capture_output=True,
        text=True,
        shell=True,
        check=True,
    )
    return json.loads(out.stdout)["accessToken"]


def scene() -> bytes:
    image = Image.new("RGB", (720, 1280), (222, 216, 206))
    draw = ImageDraw.Draw(image)
    draw.rectangle([120, 700, 600, 1180], fill=(58, 74, 120))
    draw.ellipse([200, 200, 520, 520], fill=(196, 120, 84))
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def main() -> None:
    headers = {"Authorization": f"Bearer {token()}"}
    client = httpx.Client(timeout=120.0)

    created = client.post(
        BASE,
        params=PARAMS,
        headers=headers,
        data={
            "model": "sora-2",
            "prompt": "Static camera. Soft studio light slowly shifts across a plain fabric backdrop.",
            "seconds": "4",
            "size": "720x1280",
        },
        files={"input_reference": ("ref.png", scene(), "image/png")},
    )
    print("create:", created.status_code, created.text[:400])
    created.raise_for_status()
    video_id = created.json()["id"]

    status = ""
    for _ in range(60):
        time.sleep(5)
        payload = client.get(f"{BASE}/{video_id}", params=PARAMS, headers=headers).json()
        status = payload.get("status", "")
        print("  status:", status, payload.get("progress"))
        if status in {"completed", "failed", "cancelled"}:
            print("  payload:", json.dumps(payload)[:600])
            break

    if status == "completed":
        content = client.get(f"{BASE}/{video_id}/content", params={**PARAMS, "variant": "video"}, headers=headers)
        print("download:", content.status_code, len(content.content), "bytes")
        with open("videos/_probe.mp4", "wb") as handle:
            handle.write(content.content)
        print("salvo em videos/_probe.mp4")

    client.close()


if __name__ == "__main__":
    main()
