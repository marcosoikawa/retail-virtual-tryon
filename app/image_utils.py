"""Validacao, normalizacao e conversao das imagens enviadas pelo usuario."""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

UUID_IMAGE = re.compile(
    r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\.(?:jpg|png)$"
)
UUID_RE = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")

PERSON_MAX_SIZE = (600, 800)
GARMENT_MAX_SIZE = (200, 232)
_ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp"}


class ImageValidationError(ValueError):
    """Arquivo enviado invalido ou nao suportado."""


@dataclass(slots=True)
class NormalizedImage:
    data: bytes
    filename: str
    mime_type: str
    width: int
    height: int


def sniff_mime_type(data: bytes) -> str | None:
    """Detecta o tipo real pelos magic bytes (ignora extensao e content-type)."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def normalize_upload(
    data: bytes, max_bytes: int, label: str, max_size: tuple[int, int]
) -> NormalizedImage:
    """Valida, remove EXIF, redimensiona e converte o upload para PNG."""
    if not data:
        raise ImageValidationError(f"O arquivo de {label} esta vazio.")
    if len(data) > max_bytes:
        limit_mb = max_bytes // (1024 * 1024)
        raise ImageValidationError(
            f"O arquivo de {label} excede o limite de {limit_mb} MB."
        )

    mime = sniff_mime_type(data)
    if mime not in _ALLOWED_MIME:
        raise ImageValidationError(
            f"Formato nao suportado em {label}. Use JPG, PNG ou WEBP."
        )

    try:
        with Image.open(io.BytesIO(data)) as source:
            source.load()
            # exif_transpose aplica a orientacao e descarta o restante dos metadados.
            oriented = ImageOps.exif_transpose(source) or source
            image = oriented.convert("RGB")
    except ImageValidationError:
        raise
    except Exception as exc:  # noqa: BLE001 - Pillow lanca varios tipos
        raise ImageValidationError(f"Nao foi possivel ler a imagem de {label}.") from exc

    image.thumbnail(max_size, Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return NormalizedImage(
        data=buffer.getvalue(),
        filename=f"{label}.png",
        mime_type="image/png",
        width=image.width,
        height=image.height,
    )
def parse_size(size: str) -> tuple[int, int]:
    width, _, height = size.lower().partition("x")
    return int(width), int(height)


def suggest_orientation(path: Path) -> str:
    """Orientacao que melhor respeita a proporcao da imagem gerada."""
    try:
        with Image.open(path) as image:
            return "landscape" if image.width > image.height else "portrait"
    except Exception:  # noqa: BLE001 - fallback seguro
        logger.warning("Nao foi possivel inferir orientacao de %s", path.name)
        return "portrait"
def safe_output_path(directory: Path, filename: str, pattern: re.Pattern[str]) -> Path:
    """Resolve o caminho apenas para nomes UUID validos dentro do diretorio."""
    if not pattern.match(filename):
        raise ImageValidationError("Nome de arquivo invalido.")
    resolved = (directory / filename).resolve()
    if resolved.parent != directory.resolve():
        raise ImageValidationError("Nome de arquivo invalido.")
    return resolved
