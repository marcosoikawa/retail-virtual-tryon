"""Configuracao da aplicacao e credenciais do Microsoft Foundry."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Awaitable, Callable, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
FOUNDRY_TOKEN_SCOPE = "https://ai.azure.com/.default"

_HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_SIZE = re.compile(r"^\d{3,4}x\d{3,4}$")

LOGO_CANDIDATES: tuple[str, ...] = ("logo.svg", "logo.png", "logo.jpg", "logo.webp")
IMAGE_MODEL_CHOICES: tuple[str, ...] = (
    "gpt-image-2",
)
FLUX_MODEL_PATHS: dict[str, str] = {
    "FLUX.2-pro": "flux-2-pro",
    "FLUX.2-flex": "flux-2-flex",
}

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ImageTokenPrices:
    input_text_per_1m: float
    input_image_per_1m: float
    output_image_per_1m: float


class ConfigurationError(RuntimeError):
    """Configuracao ausente ou invalida."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    azure_openai_endpoint: str = ""
    azure_openai_api_version: str = "2025-04-01-preview"
    azure_flux_endpoint: str = ""
    azure_flux_api_version: str = "preview"
    azure_openai_api_key: str = ""

    image_model_deployment: str = "gpt-image-2"
    image_mini_model_deployment: str = "gpt-image-1-mini"
    flux_2_pro_deployment: str = "FLUX.2-pro"
    flux_2_flex_deployment: str = "FLUX.2-flex"

    gpt_image_2_size: str = "1024x1536"
    gpt_image_1_mini_size: str = "1024x1536"
    flux_image_size: str = "300x400"
    image_quality: Literal["low", "medium", "high"] = "low"
    image_output_format: Literal["jpeg", "png", "webp"] = "jpeg"
    image_output_compression: int = Field(default=80, ge=0, le=100)
    image_timeout_seconds: int = 180

    brand_name: str = "Virtual Try-On"
    brand_accent_color: str = "#eb0a1e"

    max_garments: int = Field(default=5, ge=1, le=8)
    max_upload_mb: int = Field(default=10, ge=1, le=50)
    rate_limit_image_per_minute: int = Field(default=6, ge=1)

    # Precos globais estimados em USD por 1M tokens (ajuste conforme o contrato Foundry).
    gpt_image_2_input_text_price_per_1m: float = Field(default=5.0, ge=0)
    gpt_image_2_input_image_price_per_1m: float = Field(default=8.0, ge=0)
    gpt_image_2_output_image_price_per_1m: float = Field(default=30.0, ge=0)
    gpt_image_1_mini_input_text_price_per_1m: float = Field(default=2.0, ge=0)
    gpt_image_1_mini_input_image_price_per_1m: float = Field(default=2.50, ge=0)
    gpt_image_1_mini_output_image_price_per_1m: float = Field(default=8.0, ge=0)
    flux_2_pro_initial_mp_price: float = Field(default=0.03, ge=0)
    flux_2_pro_mp_price: float = Field(default=0.015, ge=0)
    flux_2_pro_ref_mp_price: float = Field(default=0.015, ge=0)
    flux_2_flex_mp_price: float = Field(default=0.05, ge=0)
    flux_2_flex_ref_mp_price: float = Field(default=0.05, ge=0)

    def image_deployment(self, model: str) -> str:
        if model == "FLUX.2-flex":
            return self.flux_2_flex_deployment
        if model == "FLUX.2-pro":
            return self.flux_2_pro_deployment
        if model == "gpt-image-1-mini":
            return self.image_mini_model_deployment
        if model == "gpt-image-2":
            return self.image_model_deployment
        raise ValueError(f"Modelo de imagem invalido: {model}")

    def image_request_size(self, model: str) -> str:
        if model == "gpt-image-2":
            return self.gpt_image_2_size
        if model == "gpt-image-1-mini":
            return self.gpt_image_1_mini_size
        if model in FLUX_MODEL_PATHS:
            return self.flux_image_size
        raise ValueError(f"Modelo de imagem invalido: {model}")

    def image_token_prices(self, model: str) -> ImageTokenPrices:
        if model == "gpt-image-1-mini":
            return ImageTokenPrices(
                self.gpt_image_1_mini_input_text_price_per_1m,
                self.gpt_image_1_mini_input_image_price_per_1m,
                self.gpt_image_1_mini_output_image_price_per_1m,
            )
        if model == "gpt-image-2":
            return ImageTokenPrices(
                self.gpt_image_2_input_text_price_per_1m,
                self.gpt_image_2_input_image_price_per_1m,
                self.gpt_image_2_output_image_price_per_1m,
            )
        raise ValueError(f"Modelo de imagem invalido: {model}")

    def image_generation_cost(
        self,
        model: str,
        input_text_tokens: int,
        input_image_tokens: int,
        output_image_tokens: int,
        input_megapixels: float = 0.0,
        output_megapixels: float = 0.0,
    ) -> float:
        if model == "FLUX.2-pro":
            initial_output = min(output_megapixels, 1.0)
            additional_output = max(output_megapixels - 1.0, 0.0)
            return (
                initial_output * self.flux_2_pro_initial_mp_price
                + additional_output * self.flux_2_pro_mp_price
                + input_megapixels * self.flux_2_pro_ref_mp_price
            )
        if model == "FLUX.2-flex":
            return (
                output_megapixels * self.flux_2_flex_mp_price
                + input_megapixels * self.flux_2_flex_ref_mp_price
            )
        prices = self.image_token_prices(model)
        return (
            input_text_tokens * prices.input_text_per_1m
            + input_image_tokens * prices.input_image_per_1m
            + output_image_tokens * prices.output_image_per_1m
        ) / 1_000_000

    def flux_model_path(self, model: str) -> str:
        try:
            return FLUX_MODEL_PATHS[model]
        except KeyError as exc:
            raise ValueError(f"Modelo FLUX invalido: {model}") from exc

    @property
    def flux_endpoint(self) -> str:
        return (self.azure_flux_endpoint or self.azure_openai_endpoint).rstrip("/")

    allowed_origins: str = "http://localhost:8000,http://127.0.0.1:8000"
    log_level: str = "INFO"

    @field_validator("azure_openai_endpoint", "azure_flux_endpoint")
    @classmethod
    def _strip_endpoint(cls, value: str) -> str:
        endpoint = value.strip().rstrip("/")
        # Aceita colagens do portal (endpoint de projeto ou com a rota ja embutida).
        endpoint = re.sub(r"/api/projects/[^/]+$", "", endpoint)
        endpoint = re.sub(r"/openai(/v1)?$", "", endpoint)
        return endpoint.rstrip("/")

    @field_validator("brand_accent_color")
    @classmethod
    def _validate_accent(cls, value: str) -> str:
        candidate = value.strip()
        if not _HEX_COLOR.match(candidate):
            logger.warning("BRAND_ACCENT_COLOR invalido (%r); usando padrao.", value)
            return "#eb0a1e"
        return candidate.lower()

    @field_validator(
        "gpt_image_2_size",
        "gpt_image_1_mini_size",
        "flux_image_size",
    )
    @classmethod
    def _validate_size(cls, value: str) -> str:
        candidate = value.strip().lower()
        if not _SIZE.match(candidate):
            raise ValueError(f"Resolucao invalida: {value!r}. Use o formato LARGURAxALTURA.")
        return candidate

    # --- Caminhos ---------------------------------------------------------
    @property
    def base_dir(self) -> Path:
        return BASE_DIR

    @property
    def outputs_dir(self) -> Path:
        return BASE_DIR / "outputs"

    @property
    def static_dir(self) -> Path:
        return BASE_DIR / "static"

    @property
    def templates_dir(self) -> Path:
        return Path(__file__).resolve().parent / "templates"

    # --- Derivados --------------------------------------------------------
    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @property
    def uses_api_key(self) -> bool:
        return bool(self.azure_openai_api_key.strip())

    @property
    def is_foundry_configured(self) -> bool:
        return bool(self.azure_openai_endpoint)

    def logo_url(self) -> str | None:
        """Primeiro logo encontrado em static/img, na ordem de preferencia."""
        for candidate in LOGO_CANDIDATES:
            if (self.static_dir / "img" / candidate).is_file():
                return f"/static/img/{candidate}"
        return None

    def require_endpoint(self) -> str:
        if not self.azure_openai_endpoint:
            raise ConfigurationError(
                "AZURE_OPENAI_ENDPOINT nao esta configurado. Copie .env.example para .env."
            )
        return self.azure_openai_endpoint


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


# ---------------------------------------------------------------------------
# Credenciais Entra ID (com cache de token e fallback para API key)
# ---------------------------------------------------------------------------

_credential = None  # type: ignore[var-annotated]
_token_lock: asyncio.Lock | None = None
_cached_token: str = ""
_cached_expiry: float = 0.0


def _lock() -> asyncio.Lock:
    global _token_lock
    if _token_lock is None:
        _token_lock = asyncio.Lock()
    return _token_lock


def _get_credential():
    global _credential
    if _credential is None:
        try:
            from azure.identity.aio import DefaultAzureCredential
        except ImportError as exc:  # pragma: no cover - dependencia obrigatoria
            raise ConfigurationError("azure-identity nao esta instalado.") from exc
        _credential = DefaultAzureCredential()
    return _credential


async def get_bearer_token() -> str:
    """Token do Entra ID com cache em memoria e renovacao antecipada."""
    global _cached_token, _cached_expiry

    if _cached_token and _cached_expiry - time.time() > 120:
        return _cached_token

    async with _lock():
        if _cached_token and _cached_expiry - time.time() > 120:
            return _cached_token
        try:
            token = await _get_credential().get_token(FOUNDRY_TOKEN_SCOPE)
        except Exception as exc:  # noqa: BLE001 - erro de credencial vira erro de config
            raise ConfigurationError(
                "Falha ao obter token do Entra ID. Execute 'az login' ou defina "
                "AZURE_OPENAI_API_KEY."
            ) from exc
        _cached_token = token.token
        _cached_expiry = float(token.expires_on)
        return _cached_token


def get_async_token_provider() -> Callable[[], Awaitable[str]] | None:
    """Provider usado pelo cliente AzureOpenAI quando nao ha API key."""
    if get_settings().uses_api_key:
        return None
    return get_bearer_token


async def get_auth_headers() -> dict[str, str]:
    """Cabecalhos de autenticacao para chamadas REST do Microsoft Foundry."""
    settings = get_settings()
    if settings.uses_api_key:
        return {"api-key": settings.azure_openai_api_key.strip()}
    return {"Authorization": f"Bearer {await get_bearer_token()}"}


async def close_credential() -> None:
    global _credential, _cached_token, _cached_expiry
    if _credential is not None:
        await _credential.close()
        _credential = None
    _cached_token = ""
    _cached_expiry = 0.0


def configure_logging() -> None:
    level = getattr(logging, get_settings().log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s :: %(message)s",
        datefmt="%H:%M:%S",
    )
