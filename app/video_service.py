"""Integracao com a Video API do Microsoft Foundry (sora-2, image-to-video)."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from pathlib import Path

import httpx

from .config import ConfigurationError, Settings, get_auth_headers
from .image_utils import build_reference_frame
from .jobs import JobRegistry, VideoJob

logger = logging.getLogger(__name__)

_POLL_START = 3.0
_POLL_MAX = 10.0
_POLL_GROWTH = 1.35

CAMERA_DIRECTIVES: dict[str, str] = {
    "runway": (
        "Runway walk: the subject walks slowly and confidently straight towards a static camera, "
        "natural gait and arm swing, garments moving with the steps."
    ),
    "spin": (
        "Slow 360 degree turn: the subject rotates smoothly on the spot so the full outfit and the "
        "back of the garments become visible, camera stays locked off."
    ),
    "fabric": (
        "Fabric detail: the camera pushes in gently towards the garments to reveal texture, weave "
        "and stitching, while the subject makes a small natural movement."
    ),
    "still": (
        "Elegant still: locked-off camera, the subject holds the pose with subtle breathing and "
        "micro movements, fabric settling naturally."
    ),
}

_BASE_INSTRUCTION = (
    "Animate the person in the reference image as the first frame of the shot. "
    "Keep the identity locked: same face, same facial features, same hairstyle and hair colour, "
    "same skin tone, same body proportions. Keep the outfit identical: same colours, prints, "
    "logos, cut and fit on every garment."
)

_QUALITY_RULES = (
    "Quality rules: natural, physically plausible human motion; fabric with realistic drape, "
    "weight and inertia; stable lighting and colour grading consistent with the reference image; "
    "no face or hand morphing; no identity drift; no wardrobe change; no on-screen text, subtitle "
    "or watermark; no hard cuts, a single continuous shot."
)


class VideoError(RuntimeError):
    """Falha na geracao do video."""


class VideoContentPolicyError(VideoError):
    """Requisicao de video bloqueada pelo filtro de conteudo do provedor."""


def build_video_prompt(camera_motion: str, notes: str) -> str:
    parts = [
        _BASE_INSTRUCTION,
        CAMERA_DIRECTIVES.get(camera_motion, CAMERA_DIRECTIVES["runway"]),
        _QUALITY_RULES,
    ]
    cleaned = notes.strip()
    if cleaned:
        parts.append(f"Additional client notes: {cleaned}")
    return "\n".join(parts)


class VideoService:
    """Cria, acompanha e baixa jobs de video do sora-2."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=15.0))

    @property
    def is_configured(self) -> bool:
        return self._settings.is_foundry_configured and bool(self._settings.video_model_deployment)

    async def close(self) -> None:
        await self._client.aclose()

    async def run_job(
        self,
        job: VideoJob,
        registry: JobRegistry,
        image_path: Path,
        notes: str,
        metrics: object | None = None,
    ) -> None:
        """Executa o ciclo criar -> polling -> download em background."""
        remote_id: str | None = None
        try:
            if not self.is_configured:
                raise ConfigurationError(
                    "O deployment de video nao esta configurado. Defina AZURE_OPENAI_ENDPOINT e "
                    "VIDEO_MODEL_DEPLOYMENT no arquivo .env."
                )

            await registry.update(job.id, status="queued", stage="uploading", progress=5)
            prompt = build_video_prompt(job.camera_motion, notes)
            reference = await asyncio.to_thread(build_reference_frame, image_path, job.size)

            remote_id = await self._create_remote_job(prompt, job.duration, job.size, reference)
            await registry.update(job.id, remote_id=remote_id, stage="queued", progress=10)

            await self._poll_until_done(job, registry, remote_id)
            await registry.update(job.id, stage="finalizing", progress=95)

            filename = await self._download(remote_id)
            await registry.update(
                job.id,
                status="completed",
                stage="done",
                progress=100,
                video_filename=filename,
            )
            if metrics is not None:
                await metrics.record_video_generation(job.duration, job.image_id)
            logger.info("Video %s concluido para a imagem %s", filename, job.image_id)

        except asyncio.CancelledError:
            if remote_id:
                await self._delete_remote_job(remote_id)
            raise
        except (VideoError, ConfigurationError) as exc:
            await registry.update(job.id, status="failed", stage="done", error=str(exc))
            logger.warning("Job de video %s falhou: %s", job.id, exc)
        except Exception:  # noqa: BLE001 - protege a task de background
            await registry.update(
                job.id,
                status="failed",
                stage="done",
                error="Erro inesperado ao gerar o video. Tente novamente.",
            )
            logger.exception("Job de video %s falhou de forma inesperada.", job.id)

    # --- Chamadas REST ----------------------------------------------------

    def _url(self, suffix: str = "") -> str:
        base = f"{self._settings.require_endpoint()}/openai/v1/videos"
        return f"{base}{suffix}"

    def _params(self) -> dict[str, str]:
        return {"api-version": self._settings.azure_video_api_version}

    async def _create_remote_job(
        self, prompt: str, seconds: int, size: str, reference: bytes
    ) -> str:
        data = {
            "model": self._settings.video_model_deployment,
            "prompt": prompt,
            "seconds": str(seconds),
            "size": size,
        }
        files = {"input_reference": ("reference.png", reference, "image/png")}
        response = await self._client.post(
            self._url(),
            params=self._params(),
            headers=await get_auth_headers(),
            data=data,
            files=files,
        )
        payload = self._decode(response, "criar o job de video")
        remote_id = payload.get("id")
        if not isinstance(remote_id, str):
            raise VideoError("O provedor nao retornou um identificador de video.")
        return remote_id

    async def _retrieve(self, remote_id: str) -> dict[str, object]:
        response = await self._client.get(
            self._url(f"/{remote_id}"),
            params=self._params(),
            headers=await get_auth_headers(),
        )
        return self._decode(response, "consultar o job de video")

    async def _poll_until_done(
        self, job: VideoJob, registry: JobRegistry, remote_id: str
    ) -> None:
        deadline = time.monotonic() + self._settings.video_timeout_seconds
        interval = _POLL_START

        while True:
            if time.monotonic() > deadline:
                await self._delete_remote_job(remote_id)
                raise VideoError(
                    "Tempo limite excedido ao renderizar o video. Tente uma duracao menor."
                )

            await asyncio.sleep(interval)
            interval = min(interval * _POLL_GROWTH, _POLL_MAX)

            payload = await self._retrieve(remote_id)
            status = str(payload.get("status", "")).lower()
            remote_progress = payload.get("progress")
            progress = 10
            if isinstance(remote_progress, (int, float)):
                progress = 10 + int(max(0.0, min(100.0, float(remote_progress))) * 0.8)

            if status in {"queued", "preprocessing"}:
                await registry.update(job.id, status="queued", stage="queued", progress=progress)
            elif status in {"in_progress", "running", "processing"}:
                await registry.update(
                    job.id, status="in_progress", stage="rendering", progress=max(progress, 15)
                )
            elif status in {"completed", "succeeded"}:
                return
            elif status == "failed":
                raise VideoError(_failure_message(payload))
            elif status == "cancelled":
                raise VideoError("O job de video foi cancelado pelo provedor.")
            else:
                logger.debug("Status desconhecido do provedor: %r", status)

    async def _download(self, remote_id: str) -> str:
        filename = f"{uuid.uuid4()}.mp4"
        target = self._settings.videos_dir / filename
        partial = target.with_suffix(".part")

        try:
            async with self._client.stream(
                "GET",
                self._url(f"/{remote_id}/content"),
                params={**self._params(), "variant": "video"},
                headers=await get_auth_headers(),
            ) as response:
                if response.status_code >= 400:
                    await response.aread()
                    self._decode(response, "baixar o video gerado")
                with partial.open("wb") as handle:
                    async for chunk in response.aiter_bytes(chunk_size=1 << 18):
                        handle.write(chunk)
        except httpx.HTTPError as exc:
            partial.unlink(missing_ok=True)
            raise VideoError(f"Falha ao baixar o video gerado: {exc}") from exc

        if partial.stat().st_size == 0:
            partial.unlink(missing_ok=True)
            raise VideoError("O provedor retornou um arquivo de video vazio.")

        partial.replace(target)
        return filename

    async def _delete_remote_job(self, remote_id: str) -> None:
        try:
            await self._client.delete(
                self._url(f"/{remote_id}"),
                params=self._params(),
                headers=await get_auth_headers(),
            )
        except Exception:  # noqa: BLE001 - melhor esforco na limpeza remota
            logger.debug("Nao foi possivel remover o job remoto %s", remote_id)

    # --- Utilitarios ------------------------------------------------------

    @staticmethod
    def _decode(response: httpx.Response, action: str) -> dict[str, object]:
        if response.status_code >= 400:
            detail = _error_message(response)
            if response.status_code == 400 and _is_content_policy(detail):
                raise VideoContentPolicyError(
                    "O provedor bloqueou a geracao por politica de conteudo. Sora 2 recusa "
                    "imagens com rostos reais e conteudo protegido por direitos autorais."
                )
            if response.status_code in {401, 403}:
                raise VideoError(
                    "Credenciais sem permissao para a Video API. Verifique a role "
                    "'Cognitive Services User' ou a API key."
                )
            if response.status_code == 410:
                raise VideoError(
                    "A versao do deployment de video foi descontinuada pelo provedor. "
                    "Atualize o deployment sora-2 para uma versao suportada no Foundry. "
                    f"Detalhe: {detail}"
                )
            if response.status_code == 429:
                raise VideoError(
                    "Cota de video esgotada no momento. Tente novamente em alguns minutos."
                )
            raise VideoError(f"Erro {response.status_code} ao {action}: {detail}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise VideoError(f"Resposta invalida do provedor ao {action}.") from exc
        if not isinstance(payload, dict):
            raise VideoError(f"Resposta inesperada do provedor ao {action}.")
        return payload


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:300]
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error.get("code") or body)[:400]
        return str(body)[:400]
    return str(body)[:300]


def _failure_message(payload: dict[str, object]) -> str:
    error = payload.get("error")
    reason = ""
    if isinstance(error, dict):
        reason = str(error.get("message") or error.get("code") or "")
    reason = reason or str(payload.get("failure_reason") or "")
    if _is_content_policy(reason):
        return (
            "O provedor bloqueou a geracao por politica de conteudo. Sora 2 recusa imagens com "
            "rostos reais e conteudo protegido por direitos autorais."
        )
    return f"A renderizacao falhou: {reason or 'motivo nao informado pelo provedor'}."


def _is_content_policy(text: str) -> bool:
    marker = text.lower()
    return any(
        token in marker
        for token in ("content_policy", "moderation", "safety", "content filter", "blocked")
    )
