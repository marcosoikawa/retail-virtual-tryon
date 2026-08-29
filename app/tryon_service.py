"""Integracao com modelos GPT Image e FLUX.2 no Microsoft Foundry."""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import random
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncAzureOpenAI,
    BadRequestError,
    RateLimitError,
)
from PIL import Image

from .config import ConfigurationError, Settings, get_async_token_provider, get_auth_headers
from .image_utils import NormalizedImage, parse_size

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
_BASE_BACKOFF = 2.0

BACKGROUND_DIRECTIVES: dict[str, str] = {
    "studio": (
        "Place the subject in a clean seamless studio backdrop in a neutral light grey tone, "
        "with soft even fashion lighting and a subtle contact shadow on the floor."
    ),
    "urban": (
        "Place the subject in a tasteful urban street setting with shallow depth of field, "
        "the background softly blurred so the outfit stays the focus."
    ),
    "original": (
        "Keep the original background, framing and lighting of the first photo exactly as they are."
    ),
}

STYLE_DIRECTIVES: dict[str, str] = {
    "ecommerce": (
        "Shoot it as a catalogue e-commerce product photo: full body in frame, centred, "
        "crisp focus, neutral colour grading, garments clearly readable."
    ),
    "lookbook": (
        "Shoot it as an editorial lookbook frame: confident posture, refined colour grading, "
        "cinematic but natural lighting."
    ),
    "casual": (
        "Shoot it as a natural lifestyle photo: relaxed posture, candid feel, soft daylight."
    ),
}

_BASE_INSTRUCTION = (
    "Photorealistic virtual try-on. The FIRST image is the real person. Every following image is "
    "a garment or accessory reference. Produce a single photograph of that exact same person "
    "wearing the referenced garments together as one coherent outfit.\n"
    "Identity lock: keep the face, facial features, expression, hairstyle, hair colour, skin tone, "
    "body proportions, height, age, pose and camera framing of the first image unchanged. "
    "Only the clothing changes. Keep the generated image portrait-oriented."
)

_QUALITY_RULES = (
    "Quality rules: reproduce each garment's exact colour, print, pattern, logo placement, "
    "fabric texture, neckline, sleeve and hem length; realistic fabric drape with natural folds, "
    "wrinkles and contact shadows; lighting direction, intensity and colour temperature matching "
    "the original photo; anatomically correct hands and face with no distortion; no duplicated "
    "limbs; no extra garments that were not provided; no overlaid text, caption, logo of the app "
    "or watermark; no collage, no split frame, no mannequin."
)


class TryOnError(RuntimeError):
    """Falha ao gerar a imagem de try-on."""


class ContentPolicyError(TryOnError):
    """Requisicao bloqueada pelo filtro de conteudo do provedor."""


@dataclass(frozen=True, slots=True)
class ImageTokenUsage:
    input_text_tokens: int = 0
    input_image_tokens: int = 0
    output_image_tokens: int = 0
    input_megapixels: float = 0.0
    output_megapixels: float = 0.0

    @property
    def input_tokens(self) -> int:
        return self.input_text_tokens + self.input_image_tokens

    @property
    def output_tokens(self) -> int:
        return self.output_image_tokens

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(slots=True)
class TryOnResult:
    image_id: str
    filename: str
    path: Path
    data_url: str
    elapsed_ms: int
    model: str
    usage: ImageTokenUsage

    @property
    def input_tokens(self) -> int:
        return self.usage.input_tokens

    @property
    def output_tokens(self) -> int:
        return self.usage.output_tokens

    @property
    def total_tokens(self) -> int:
        return self.usage.total_tokens


def build_tryon_prompt(background: str, style: str, notes: str, garment_count: int) -> str:
    parts = [
        _BASE_INSTRUCTION,
        f"There are {garment_count} garment reference image(s); all of them must be worn.",
        BACKGROUND_DIRECTIVES.get(background, BACKGROUND_DIRECTIVES["original"]),
        STYLE_DIRECTIVES.get(style, STYLE_DIRECTIVES["ecommerce"]),
        _QUALITY_RULES,
    ]
    cleaned = notes.strip()
    if cleaned:
        parts.append(f"Additional client notes (respect them unless they break the rules above): {cleaned}")
    return "\n".join(parts)


class TryOnService:
    """Cliente assincrono dos modelos GPT Image hospedados no Microsoft Foundry."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: AsyncAzureOpenAI | None = None
        self._flux_client = httpx.AsyncClient(
            timeout=httpx.Timeout(float(settings.image_timeout_seconds), connect=15.0),
            follow_redirects=True,
        )
        self._lock = asyncio.Lock()

    @property
    def is_configured(self) -> bool:
        return self._settings.is_foundry_configured and bool(self._settings.image_model_deployment)

    async def _get_client(self) -> AsyncAzureOpenAI:
        if self._client is not None:
            return self._client
        async with self._lock:
            if self._client is None:
                endpoint = self._settings.require_endpoint()
                token_provider = get_async_token_provider()
                self._client = AsyncAzureOpenAI(
                    azure_endpoint=endpoint,
                    api_version=self._settings.azure_openai_api_version,
                    api_key=self._settings.azure_openai_api_key.strip() or None,
                    azure_ad_token_provider=token_provider,
                    timeout=float(self._settings.image_timeout_seconds),
                    max_retries=0,
                )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None
        await self._flux_client.aclose()

    async def generate(
        self,
        person: NormalizedImage,
        garments: list[NormalizedImage],
        background: str,
        style: str,
        notes: str,
        model: str,
    ) -> TryOnResult:
        deployment = self._settings.image_deployment(model)
        if not self._settings.is_foundry_configured or not deployment:
            raise ConfigurationError(
                "O deployment de imagem nao esta configurado. Defina AZURE_OPENAI_ENDPOINT e "
                "os deployments de imagem no arquivo .env."
            )

        prompt = build_tryon_prompt(background, style, notes, len(garments))
        files = [(item.filename, item.data, item.mime_type) for item in [person, *garments]]
        started = time.perf_counter()

        if model.startswith("FLUX.2-"):
            payload, usage = await self._call_flux(files, prompt, model, deployment)
            usage = ImageTokenUsage(
                input_megapixels=round(
                    sum(item.width * item.height for item in [person, *garments]) / 1_000_000,
                    6,
                ),
                output_megapixels=_image_megapixels(payload),
            )
        else:
            client = await self._get_client()
            payload, usage = await self._call_with_retry(
                client, files, prompt, model, deployment
            )
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        image_id = str(uuid.uuid4())
        filename = f"{image_id}.jpg"
        path = self._settings.outputs_dir / filename
        path.write_bytes(payload)

        logger.info("Imagem de try-on gerada em %sms -> %s", elapsed_ms, filename)
        return TryOnResult(
            image_id=image_id,
            filename=filename,
            path=path,
            data_url=f"data:image/jpeg;base64,{base64.b64encode(payload).decode('ascii')}",
            elapsed_ms=elapsed_ms,
            model=model,
            usage=usage,
        )

    async def _call_with_retry(
        self,
        client: AsyncAzureOpenAI,
        files: list[tuple[str, bytes, str]],
        prompt: str,
        model: str,
        deployment: str,
    ) -> tuple[bytes, ImageTokenUsage]:
        last_error: Exception | None = None

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = await client.images.edit(
                    model=deployment,
                    image=list(files),
                    prompt=prompt,
                    n=1,
                    size=self._settings.image_request_size(model),  # type: ignore[arg-type]
                    quality=self._settings.image_quality,  # type: ignore[arg-type]
                    output_format=self._settings.image_output_format,
                    output_compression=self._settings.image_output_compression,
                    extra_body={"input_fidelity": "high"} if model == "gpt-image-2" else None,
                )
            except BadRequestError as exc:
                if _is_content_policy(exc):
                    raise ContentPolicyError(
                        "As imagens ou as observacoes foram bloqueadas pelo filtro de conteudo do "
                        "Foundry. Tente outra foto ou ajuste o texto."
                    ) from exc
                raise TryOnError(f"Requisicao rejeitada pelo provedor: {_message(exc)}") from exc
            except (RateLimitError, APITimeoutError, APIConnectionError) as exc:
                last_error = exc
            except APIStatusError as exc:
                if exc.status_code < 500:
                    raise TryOnError(
                        f"O provedor retornou erro {exc.status_code}: {_message(exc)}"
                    ) from exc
                last_error = exc
            else:
                data = getattr(response, "data", None)
                if not data or not getattr(data[0], "b64_json", None):
                    raise TryOnError("O provedor nao retornou nenhuma imagem.")
                usage = _extract_usage(response)
                return base64.b64decode(data[0].b64_json), usage  # type: ignore[arg-type]

            if attempt < MAX_ATTEMPTS:
                delay = _BASE_BACKOFF ** attempt + random.uniform(0, 0.5)
                logger.warning(
                    "Tentativa %s/%s falhou (%s). Novo envio em %.1fs.",
                    attempt,
                    MAX_ATTEMPTS,
                    type(last_error).__name__,
                    delay,
                )
                await asyncio.sleep(delay)

        raise TryOnError(
            "O servico de imagem esta indisponivel ou saturado. Tente novamente em instantes."
        ) from last_error

    async def _call_flux(
        self,
        files: list[tuple[str, bytes, str]],
        prompt: str,
        model: str,
        deployment: str,
    ) -> tuple[bytes, ImageTokenUsage]:
        max_images = 8 if model == "FLUX.2-pro" else 10
        if len(files) > max_images:
            raise TryOnError(f"{model} aceita no maximo {max_images} imagens de referencia.")

        width, height = parse_size(self._settings.image_request_size(model))
        request_body: dict[str, object] = {
            "model": deployment,
            "prompt": prompt,
            "width": width,
            "height": height,
            "output_format": self._settings.image_output_format,
            "num_images": 1,
        }
        for index, (_, content, _) in enumerate(files, start=1):
            field = "input_image" if index == 1 else f"input_image_{index}"
            request_body[field] = base64.b64encode(content).decode("ascii")

        path = self._settings.flux_model_path(model)
        url = f"{self._settings.flux_endpoint}/providers/blackforestlabs/v1/{path}"
        if self._settings.uses_api_key:
            auth_headers = {
                "Authorization": f"Bearer {self._settings.azure_openai_api_key.strip()}"
            }
        else:
            auth_headers = await get_auth_headers()
        try:
            response = await self._flux_client.post(
                url,
                params={"api-version": self._settings.azure_flux_api_version},
                headers={"Content-Type": "application/json", **auth_headers},
                json=request_body,
            )
        except httpx.HTTPError as exc:
            raise TryOnError(f"Falha de conexao com {model}: {exc}") from exc

        if response.status_code >= 400:
            message = _flux_error_message(response)
            if response.status_code in {400, 422} and _is_flux_content_policy(message):
                raise ContentPolicyError(message)
            raise TryOnError(f"Requisicao rejeitada pelo provedor ({response.status_code}): {message}")

        try:
            response_body = response.json()
        except ValueError as exc:
            raise TryOnError("O provedor FLUX retornou uma resposta invalida.") from exc

        image_data = await self._extract_flux_image(response_body)
        return image_data, ImageTokenUsage()

    async def _extract_flux_image(self, response_body: object) -> bytes:
        if not isinstance(response_body, dict):
            raise TryOnError("O provedor FLUX nao retornou uma imagem.")

        candidates: list[object] = [response_body]
        data = response_body.get("data")
        if isinstance(data, list) and data:
            candidates.insert(0, data[0])
        result = response_body.get("result")
        if isinstance(result, dict):
            candidates.insert(0, result)

        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            encoded = candidate.get("b64_json") or candidate.get("image")
            if isinstance(encoded, str) and encoded:
                try:
                    return base64.b64decode(encoded, validate=True)
                except ValueError:
                    pass
            image_url = candidate.get("url") or candidate.get("sample")
            if isinstance(image_url, str) and image_url:
                if urlparse(image_url).scheme != "https":
                    raise TryOnError("O provedor FLUX retornou uma URL de imagem insegura.")
                download = await self._flux_client.get(image_url)
                if download.status_code >= 400:
                    raise TryOnError("Nao foi possivel baixar a imagem gerada pelo FLUX.")
                if not download.content:
                    raise TryOnError("O provedor FLUX retornou uma imagem vazia.")
                return download.content

        raise TryOnError("O provedor FLUX nao retornou uma imagem reconhecivel.")


def _extract_usage(response: object) -> ImageTokenUsage:
    """Extrai tokens de texto e imagem da resposta do GPT Image."""
    usage = _usage_field(response, "usage")
    if usage is None:
        return ImageTokenUsage()

    input_tokens = int(_usage_field(usage, "input_tokens") or 0)
    output_tokens = int(_usage_field(usage, "output_tokens") or 0)
    details = _usage_field(usage, "input_tokens_details")
    text_tokens = int(_usage_field(details, "text_tokens") or 0)
    image_tokens = int(_usage_field(details, "image_tokens") or 0)

    if text_tokens == 0 and image_tokens == 0:
        image_tokens = input_tokens

    return ImageTokenUsage(
        input_text_tokens=text_tokens,
        input_image_tokens=image_tokens,
        output_image_tokens=output_tokens,
    )


def _usage_field(value: object, name: str) -> object | None:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _image_megapixels(data: bytes) -> float:
    try:
        with Image.open(io.BytesIO(data)) as image:
            return round(image.width * image.height / 1_000_000, 6)
    except Exception as exc:  # noqa: BLE001 - resposta invalida do provedor
        raise TryOnError("O provedor retornou uma imagem que nao pode ser lida.") from exc


def _flux_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:400] or "Erro desconhecido do provedor FLUX."
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error)[:400]
        if isinstance(error, str):
            return error[:400]
        return str(payload.get("message") or payload)[:400]
    return str(payload)[:400]


def _is_flux_content_policy(message: str) -> bool:
    marker = message.lower()
    return any(token in marker for token in ("content", "moderation", "safety"))


def _message(exc: APIStatusError) -> str:
    body = exc.body if isinstance(exc.body, dict) else {}
    error = body.get("error") if isinstance(body.get("error"), dict) else {}
    return str(error.get("message") or exc.message)[:400]


def _is_content_policy(exc: APIStatusError) -> bool:
    body = exc.body if isinstance(exc.body, dict) else {}
    error = body.get("error") if isinstance(body.get("error"), dict) else {}
    marker = f"{error.get('code', '')} {error.get('message', '')} {exc.message}".lower()
    return any(token in marker for token in ("content_policy", "moderation", "safety", "content filter"))
