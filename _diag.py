"""Diagnostico temporario: valida endpoint, escopo do token e rotas de imagem."""

from __future__ import annotations

import io
import json
import subprocess
import sys

import httpx
from PIL import Image

RESOURCE = "https://hiro-foundry-resource.services.ai.azure.com"
IMAGE_DEPLOYMENT = "gpt-image-2"


def token(scope: str) -> str:
    out = subprocess.run(
        ["az", "account", "get-access-token", "--resource", scope, "-o", "json"],
        capture_output=True,
        text=True,
        shell=True,
    )
    if out.returncode != 0:
        print(f"  !! falha ao obter token para {scope}: {out.stderr.strip()[:200]}")
        return ""
    return json.loads(out.stdout)["accessToken"]


def png(color: tuple[int, int, int], size: tuple[int, int]) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def show(label: str, response: httpx.Response) -> None:
    body = response.text[:300].replace("\n", " ")
    print(f"  {label}: {response.status_code} :: {body}")


def main() -> None:
    scopes = {
        "foundry": "https://ai.azure.com",
    }
    tokens = {name: token(scope) for name, scope in scopes.items()}

    client = httpx.Client(timeout=120.0)

    for base in (RESOURCE,):
        print(f"\n=== BASE {base} ===")
        for name, tok in tokens.items():
            if not tok:
                continue
            headers = {"Authorization": f"Bearer {tok}"}
            print(f"-- escopo {name}")
            show(
                "GET /openai/models (v1)",
                client.get(f"{base}/openai/v1/models", params={"api-version": "preview"}, headers=headers),
            )

    tok = tokens.get("foundry")
    headers = {"Authorization": f"Bearer {tok}"}
    person = png((180, 150, 130), (512, 768))
    garment = png((30, 60, 200), (512, 512))

    print("\n=== IMAGES EDIT (classico: /openai/deployments/{dep}/images/edits) ===")
    r = client.post(
        f"{RESOURCE}/openai/deployments/{IMAGE_DEPLOYMENT}/images/edits",
        params={"api-version": "2025-04-01-preview"},
        headers=headers,
        data={"prompt": "Put the blue shirt on the person.", "n": "1", "size": "1024x1536", "quality": "low"},
        files=[
            ("image[]", ("person.png", person, "image/png")),
            ("image[]", ("garment.png", garment, "image/png")),
        ],
    )
    print(f"  status {r.status_code} :: {r.text[:400]}")

    print("\n=== IMAGES EDIT (v1: /openai/v1/images/edits) ===")
    r = client.post(
        f"{RESOURCE}/openai/v1/images/edits",
        params={"api-version": "preview"},
        headers=headers,
        data={
            "model": IMAGE_DEPLOYMENT,
            "prompt": "Put the blue shirt on the person.",
            "n": "1",
            "size": "1024x1536",
            "quality": "low",
        },
        files=[
            ("image[]", ("person.png", person, "image/png")),
            ("image[]", ("garment.png", garment, "image/png")),
        ],
    )
    print(f"  status {r.status_code} :: {r.text[:400]}")

    client.close()


if __name__ == "__main__":
    sys.exit(main())
