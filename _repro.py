"""Reproduz a chamada real do TryOnService com as settings do .env."""

from __future__ import annotations

import asyncio
import io

from PIL import Image

from app.config import get_settings
from app.image_utils import normalize_upload
from app.tryon_service import TryOnService


def png(color, size) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", color=color, size=size).save(buf, format="PNG")
    return buf.getvalue()


async def main() -> None:
    settings = get_settings()
    print("endpoint      :", settings.azure_openai_endpoint)
    print("api_version   :", settings.azure_openai_api_version)
    print("deployment    :", settings.image_model_deployment)
    print("uses_api_key  :", settings.uses_api_key)
    print("token_scope   :", settings.azure_token_scope)

    service = TryOnService(settings)
    person = normalize_upload(png((190, 160, 140), (512, 768)), settings.max_upload_bytes, "pessoa")
    garment = normalize_upload(png((40, 70, 200), (512, 512)), settings.max_upload_bytes, "peca-1")

    try:
        result = await service.generate(person, [garment], "studio", "ecommerce", "")
        print("OK ->", result.filename, result.elapsed_ms, "ms")
    except Exception as exc:  # noqa: BLE001
        print("FALHOU:", type(exc).__name__, "->", str(exc)[:600])
    finally:
        await service.close()


if __name__ == "__main__":
    asyncio.run(main())
