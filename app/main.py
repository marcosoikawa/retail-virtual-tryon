"""FastAPI: rotas, ciclo de vida e servico de arquivos gerados."""

from __future__ import annotations

import asyncio
import logging
import math
import re
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Iterator, Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from . import __version__
from .config import (
    ALLOWED_VIDEO_DURATIONS,
    ALLOWED_VIDEO_SIZES,
    IMAGE_MODEL_CHOICES,
    ConfigurationError,
    Settings,
    close_credential,
    configure_logging,
    get_settings,
)
from .image_utils import (
    UUID_MP4,
    UUID_IMAGE,
    UUID_RE,
    ImageValidationError,
    NormalizedImage,
    normalize_upload,
    orientation_to_size,
    safe_output_path,
    suggest_orientation,
)
from .jobs import CapacityError, JobRegistry
from .tryon_service import ContentPolicyError, TryOnError, TryOnService
from .video_service import VideoService

logger = logging.getLogger(__name__)

BACKGROUND_CHOICES = ("studio", "urban", "original")
STYLE_CHOICES = ("ecommerce", "lookbook", "casual")
CAMERA_CHOICES = ("runway", "spin", "fabric", "still")
MAX_NOTES_LENGTH = 600
_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


class MetricsStore:
    """Métricas operacionais em memória para a instância atual da aplicação."""

    def __init__(self, settings: Settings, max_samples: int = 2000) -> None:
        self.started_at = time.time()
        self._settings = settings
        self._samples: deque[tuple[str, str, int, float]] = deque(maxlen=max_samples)
        self._lock = asyncio.Lock()
        # Contadores de geração (imagem e vídeo) para o dashboard e o painel de custos.
        self._image_count = 0
        self._image_tokens_in = 0
        self._image_text_tokens_in = 0
        self._image_image_tokens_in = 0
        self._image_tokens_out = 0
        self._image_ms_total = 0
        self._image_durations: deque[float] = deque(maxlen=max_samples)
        self._image_cost = 0.0
        self._priced_image_count = 0
        self._unpriced_image_count = 0
        self._video_count = 0
        self._video_seconds = 0
        self._video_cost = 0.0
        self._recent: deque[dict[str, object]] = deque(maxlen=12)
        self._executions: deque[dict[str, object]] = deque(maxlen=max_samples)

    async def record(self, method: str, route: str, status_code: int, elapsed_ms: float) -> None:
        async with self._lock:
            self._samples.append((method, route, status_code, elapsed_ms))

    async def record_image_generation(
        self,
        model: str,
        input_text_tokens: int,
        input_image_tokens: int,
        output_image_tokens: int,
        elapsed_ms: int,
        image_id: str,
        *,
        input_megapixels: float = 0.0,
        output_megapixels: float = 0.0,
    ) -> None:
        cost = self._settings.image_generation_cost(
            model,
            input_text_tokens,
            input_image_tokens,
            output_image_tokens,
            input_megapixels,
            output_megapixels,
        )
        cost_configured = True
        input_tokens = input_text_tokens + input_image_tokens
        async with self._lock:
            self._image_count += 1
            self._image_tokens_in += input_tokens
            self._image_text_tokens_in += input_text_tokens
            self._image_image_tokens_in += input_image_tokens
            self._image_tokens_out += output_image_tokens
            self._image_ms_total += elapsed_ms
            self._image_durations.append(float(elapsed_ms))
            self._image_cost += cost
            if cost_configured:
                self._priced_image_count += 1
            else:
                self._unpriced_image_count += 1
            execution = {
                "execution_id": str(uuid.uuid4()),
                "type": "image",
                "id": image_id,
                "model": model,
                "input_text_tokens": input_text_tokens,
                "input_image_tokens": input_image_tokens,
                "output_image_tokens": output_image_tokens,
                "input_megapixels": round(input_megapixels, 6),
                "output_megapixels": round(output_megapixels, 6),
                "tokens": input_tokens + output_image_tokens,
                "cost": round(cost, 6),
                "cost_configured": cost_configured,
                "elapsed_ms": elapsed_ms,
                "at": int(time.time()),
            }
            self._recent.appendleft(execution)
            self._executions.appendleft(execution)

    async def record_video_generation(self, seconds: int, image_id: str) -> None:
        cost = seconds * self._settings.video_price_per_second
        async with self._lock:
            self._video_count += 1
            self._video_seconds += seconds
            self._video_cost += cost
            execution = {
                "execution_id": str(uuid.uuid4()),
                "type": "video",
                "id": image_id,
                "model": self._settings.video_model_deployment,
                "seconds": seconds,
                "tokens": 0,
                "cost": round(cost, 6),
                "cost_configured": True,
                "elapsed_ms": seconds * 1000,
                "at": int(time.time()),
            }
            self._recent.appendleft(execution)
            self._executions.appendleft(execution)

    async def snapshot(self) -> dict[str, object]:
        async with self._lock:
            samples = list(self._samples)
            image_count = self._image_count
            tokens_in = self._image_tokens_in
            text_tokens_in = self._image_text_tokens_in
            image_tokens_in = self._image_image_tokens_in
            tokens_out = self._image_tokens_out
            image_ms_total = self._image_ms_total
            image_durations = sorted(self._image_durations)
            image_cost = self._image_cost
            priced_image_count = self._priced_image_count
            unpriced_image_count = self._unpriced_image_count
            video_count = self._video_count
            video_seconds = self._video_seconds
            video_cost = self._video_cost
            recent = list(self._recent)
            executions = list(self._executions)

        durations = sorted(sample[3] for sample in samples)
        total = len(samples)
        successes = sum(1 for sample in samples if sample[2] < 400)
        errors = total - successes
        routes: dict[str, dict[str, object]] = {}
        for method, route, status_code, elapsed_ms in samples:
            key = f"{method} {route}"
            item = routes.setdefault(key, {"requests": 0, "errors": 0, "durations": []})
            item["requests"] = int(item["requests"]) + 1
            if status_code >= 400:
                item["errors"] = int(item["errors"]) + 1
            route_durations = item["durations"]
            assert isinstance(route_durations, list)
            route_durations.append(elapsed_ms)

        route_stats = []
        for name, item in routes.items():
            route_durations = item.pop("durations")
            assert isinstance(route_durations, list)
            route_stats.append(
                {
                    "route": name,
                    **item,
                    "average_response_ms": round(sum(route_durations) / len(route_durations), 1),
                }
            )

        total_tokens = tokens_in + tokens_out
        total_cost = image_cost + video_cost
        return {
            "uptime_seconds": int(time.time() - self.started_at),
            "requests": total,
            "errors": errors,
            "success_rate": round((successes / total * 100) if total else 100.0, 1),
            "average_response_ms": round(sum(durations) / total, 1) if total else 0.0,
            "p95_response_ms": round(_percentile(durations, 0.95), 1),
            "image_generations": image_count,
            "video_requests": video_count,
            "image_average_ms": round(image_ms_total / image_count) if image_count else 0,
            "image_p95_ms": round(_percentile(image_durations, 0.95), 1),
            "tokens": {
                "input": tokens_in,
                "input_text": text_tokens_in,
                "input_image": image_tokens_in,
                "output": tokens_out,
                "output_image": tokens_out,
                "total": total_tokens,
            },
            "cost": {
                "image": round(image_cost, 6),
                "video": round(video_cost, 6),
                "total": round(total_cost, 6),
                "per_image": (
                    round(image_cost / priced_image_count, 6) if priced_image_count else 0.0
                ),
                "per_video": round(video_cost / video_count, 6) if video_count else 0.0,
                "complete": unpriced_image_count == 0,
                "unpriced_images": unpriced_image_count,
                "currency": "USD",
            },
            "video_seconds": video_seconds,
            "recent": recent,
            "executions": executions,
            "routes": sorted(route_stats, key=lambda item: int(item["requests"]), reverse=True),
            "sample_limit": self._samples.maxlen,
        }


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    index = max(0, math.ceil(len(values) * percentile) - 1)
    return values[index]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    settings = get_settings()
    settings.outputs_dir.mkdir(parents=True, exist_ok=True)
    settings.videos_dir.mkdir(parents=True, exist_ok=True)

    app.state.settings = settings
    app.state.tryon_service = TryOnService(settings)
    app.state.video_service = VideoService(settings)
    app.state.jobs = JobRegistry(settings.max_concurrent_video_jobs)
    app.state.rate_limiter = RateLimiter()
    app.state.metrics = MetricsStore(settings)

    if not settings.is_foundry_configured:
        logger.warning("AZURE_OPENAI_ENDPOINT nao configurado: a geracao ficara indisponivel.")
    logger.info("Virtual Try-On %s pronto (marca: %s).", __version__, settings.brand_name)

    try:
        yield
    finally:
        await app.state.jobs.cancel_all()
        await app.state.tryon_service.close()
        await app.state.video_service.close()
        await close_credential()


app = FastAPI(title="Virtual Try-On", version=__version__, lifespan=lifespan)

_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)
app.mount("/static", StaticFiles(directory=_settings.static_dir), name="static")
templates = Jinja2Templates(directory=str(_settings.templates_dir))


# ---------------------------------------------------------------------------
# Infra: limite de tamanho, rate limiting e dependencias
# ---------------------------------------------------------------------------


@app.middleware("http")
async def limit_request_size(request: Request, call_next):  # type: ignore[no-untyped-def]
    settings: Settings = get_settings()
    max_body = settings.max_upload_bytes * (settings.max_garments + 2)
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_body:
        return JSONResponse(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            content={"detail": "Requisicao maior que o limite permitido."},
        )
    return await call_next(request)


@app.middleware("http")
async def collect_api_metrics(request: Request, call_next):  # type: ignore[no-untyped-def]
    started_at = time.perf_counter()
    response = await call_next(request)
    route = request.scope.get("route")
    route_path = getattr(route, "path", request.url.path)
    if route_path.startswith("/api/") and route_path != "/api/metrics":
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        await request.app.state.metrics.record(
            request.method, route_path, response.status_code, elapsed_ms
        )
    return response


class RateLimiter:
    """Janela deslizante simples por IP, suficiente para uma demo single-node."""

    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def check(self, bucket: str, client_ip: str, limit: int, window: float = 60.0) -> None:
        key = (bucket, client_ip)
        now = time.monotonic()
        async with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > window:
                hits.popleft()
            if len(hits) >= limit:
                retry_after = int(window - (now - hits[0])) + 1
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Muitas requisicoes. Aguarde alguns instantes.",
                    headers={"Retry-After": str(retry_after)},
                )
            hits.append(now)


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_tryon_service(request: Request) -> TryOnService:
    return request.app.state.tryon_service


def get_video_service(request: Request) -> VideoService:
    return request.app.state.video_service


def get_registry(request: Request) -> JobRegistry:
    return request.app.state.jobs


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@app.exception_handler(ConfigurationError)
async def _configuration_error_handler(_: Request, exc: ConfigurationError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(ImageValidationError)
async def _image_error_handler(_: Request, exc: ImageValidationError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


# ---------------------------------------------------------------------------
# Paginas
# ---------------------------------------------------------------------------


@app.get("/")
async def index(request: Request, settings: Settings = Depends(get_app_settings)) -> Response:
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "brand_name": settings.brand_name,
            "brand_accent": settings.brand_accent_color,
            "logo_url": settings.logo_url(),
            "max_garments": settings.max_garments,
            "max_upload_mb": settings.max_upload_mb,
            "durations": ALLOWED_VIDEO_DURATIONS,
            "default_duration": settings.video_default_duration,
            "version": __version__,
        },
    )


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


@app.get("/api/health")
async def health(
    settings: Settings = Depends(get_app_settings),
    video: VideoService = Depends(get_video_service),
    registry: JobRegistry = Depends(get_registry),
) -> dict[str, object]:
    return {
        "status": "ok",
        "version": __version__,
        "foundry_endpoint_configured": settings.is_foundry_configured,
        "auth_mode": "api_key" if settings.uses_api_key else "entra_id",
        "image": {
            "configured": settings.is_foundry_configured and all(
                settings.image_deployment(model) for model in IMAGE_MODEL_CHOICES
            ),
            "models": {
                model: {
                    "configured": settings.is_foundry_configured
                    and bool(settings.image_deployment(model)),
                    "deployment": settings.image_deployment(model),
                    "request_size": settings.image_request_size(model),
                }
                for model in IMAGE_MODEL_CHOICES
            },
            "quality": settings.image_quality,
            "output_format": settings.image_output_format,
            "output_compression": settings.image_output_compression,
        },
        "video": {
            "configured": video.is_configured,
            "deployment": settings.video_model_deployment,
            "active_jobs": await registry.active_count(),
            "max_concurrent": settings.max_concurrent_video_jobs,
        },
    }


@app.get("/api/metrics")
async def metrics(request: Request, registry: JobRegistry = Depends(get_registry)) -> dict[str, object]:
    snapshot = await request.app.state.metrics.snapshot()
    snapshot["active_video_jobs"] = await registry.active_count()
    snapshot["generated_at"] = int(time.time())
    return snapshot


@app.post("/api/tryon")
async def create_tryon(
    request: Request,
    person: UploadFile = File(...),
    garments: list[UploadFile] = File(...),
    background: str = Form("original"),
    style: str = Form("ecommerce"),
    image_model: str = Form("gpt-image-2"),
    notes: str = Form(""),
    settings: Settings = Depends(get_app_settings),
    tryon: TryOnService = Depends(get_tryon_service),
) -> JSONResponse:
    await request.app.state.rate_limiter.check(
        "tryon", client_ip(request), settings.rate_limit_image_per_minute
    )

    garments = [item for item in garments if item.filename]
    if not garments:
        raise HTTPException(status_code=400, detail="Envie ao menos uma peca de roupa.")
    if len(garments) > settings.max_garments:
        raise HTTPException(
            status_code=400,
            detail=f"Envie no maximo {settings.max_garments} pecas de roupa.",
        )

    background = background if background in BACKGROUND_CHOICES else "original"
    style = style if style in STYLE_CHOICES else "ecommerce"
    if image_model not in IMAGE_MODEL_CHOICES:
        raise HTTPException(status_code=400, detail="Modelo de imagem invalido.")
    notes = notes.strip()[:MAX_NOTES_LENGTH]

    person_image = await _read_and_normalize(person, settings.max_upload_bytes, "pessoa")
    garment_images: list[NormalizedImage] = []
    for index, upload in enumerate(garments, start=1):
        garment_images.append(
            await _read_and_normalize(upload, settings.max_upload_bytes, f"peca-{index}")
        )

    try:
        result = await tryon.generate(
            person_image, garment_images, background, style, notes, image_model
        )
    except ContentPolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except TryOnError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    await request.app.state.metrics.record_image_generation(
        result.model,
        result.usage.input_text_tokens,
        result.usage.input_image_tokens,
        result.usage.output_image_tokens,
        result.elapsed_ms,
        result.image_id,
        input_megapixels=result.usage.input_megapixels,
        output_megapixels=result.usage.output_megapixels,
    )

    return JSONResponse(
        {
            "image_id": result.image_id,
            "image_data_url": result.data_url,
            "image_url": f"/outputs/{result.filename}",
            "output_path": f"outputs/{result.filename}",
            "elapsed_ms": result.elapsed_ms,
            "model": result.model,
            "input_tokens": result.input_tokens,
            "input_text_tokens": result.usage.input_text_tokens,
            "input_image_tokens": result.usage.input_image_tokens,
            "output_tokens": result.output_tokens,
            "output_image_tokens": result.usage.output_image_tokens,
            "input_megapixels": result.usage.input_megapixels,
            "output_megapixels": result.usage.output_megapixels,
            "total_tokens": result.total_tokens,
            "suggested_orientation": suggest_orientation(result.path),
        }
    )


class VideoRequest(BaseModel):
    image_id: str = Field(min_length=36, max_length=36)
    camera_motion: Literal["runway", "spin", "fabric", "still"] = "runway"
    duration: int = 8
    orientation: Literal["portrait", "landscape"] = "portrait"
    notes: str = ""


@app.post("/api/video", status_code=status.HTTP_202_ACCEPTED)
async def create_video(
    request: Request,
    payload: VideoRequest,
    settings: Settings = Depends(get_app_settings),
    video: VideoService = Depends(get_video_service),
    registry: JobRegistry = Depends(get_registry),
) -> dict[str, object]:
    await request.app.state.rate_limiter.check(
        "video", client_ip(request), settings.rate_limit_video_per_minute
    )

    if not UUID_RE.match(payload.image_id):
        raise HTTPException(status_code=400, detail="Identificador de imagem invalido.")

    image_path = next(
        (
            candidate
            for suffix in (".jpg", ".png")
            if (candidate := settings.outputs_dir / f"{payload.image_id}{suffix}").is_file()
        ),
        None,
    )
    if image_path is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Gere a foto do look antes de criar o video.",
        )

    duration = (
        payload.duration
        if payload.duration in ALLOWED_VIDEO_DURATIONS
        else settings.video_default_duration
    )
    size = orientation_to_size(payload.orientation, ALLOWED_VIDEO_SIZES)
    notes = payload.notes.strip()[:MAX_NOTES_LENGTH]

    try:
        job = await registry.create(payload.image_id, payload.camera_motion, duration, size)
    except CapacityError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc

    task = asyncio.create_task(
        video.run_job(job, registry, image_path, notes, request.app.state.metrics)
    )
    await registry.attach_task(job.id, task)
    return job.to_dict()


@app.get("/api/video/{job_id}")
async def get_video_job(job_id: str, registry: JobRegistry = Depends(get_registry)) -> dict[str, object]:
    if not UUID_RE.match(job_id):
        raise HTTPException(status_code=400, detail="Identificador de job invalido.")
    job = await registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job de video nao encontrado.")
    return job.to_dict()


@app.delete("/api/video/{job_id}")
async def cancel_video_job(job_id: str, registry: JobRegistry = Depends(get_registry)) -> dict[str, object]:
    if not UUID_RE.match(job_id):
        raise HTTPException(status_code=400, detail="Identificador de job invalido.")
    job = await registry.cancel(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job de video nao encontrado.")
    return job.to_dict()


# ---------------------------------------------------------------------------
# Arquivos gerados
# ---------------------------------------------------------------------------


@app.get("/outputs/{filename}")
async def serve_output(filename: str, settings: Settings = Depends(get_app_settings)) -> Response:
    path = safe_output_path(settings.outputs_dir, filename, UUID_IMAGE)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Imagem nao encontrada.")
    return Response(
        content=path.read_bytes(),
        media_type="image/jpeg" if path.suffix == ".jpg" else "image/png",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@app.get("/videos/{filename}")
async def serve_video(
    filename: str, request: Request, settings: Settings = Depends(get_app_settings)
) -> Response:
    path = safe_output_path(settings.videos_dir, filename, UUID_MP4)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Video nao encontrado.")
    return _ranged_response(path, request.headers.get("range"), "video/mp4")


def _ranged_response(path: Path, range_header: str | None, media_type: str) -> Response:
    file_size = path.stat().st_size
    base_headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, max-age=3600",
        "Content-Disposition": f'inline; filename="{path.name}"',
    }

    if not range_header:
        return StreamingResponse(
            _iter_file(path, 0, file_size - 1),
            media_type=media_type,
            headers={**base_headers, "Content-Length": str(file_size)},
        )

    match = _RANGE_RE.match(range_header.strip())
    if not match:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})

    raw_start, raw_end = match.groups()
    if raw_start:
        start = int(raw_start)
        end = int(raw_end) if raw_end else file_size - 1
    else:
        if not raw_end:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})
        start = max(file_size - int(raw_end), 0)
        end = file_size - 1

    end = min(end, file_size - 1)
    if start > end or start >= file_size:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})

    return StreamingResponse(
        _iter_file(path, start, end),
        status_code=206,
        media_type=media_type,
        headers={
            **base_headers,
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Content-Length": str(end - start + 1),
        },
    )


def _iter_file(path: Path, start: int, end: int, chunk_size: int = 1 << 16) -> Iterator[bytes]:
    with path.open("rb") as handle:
        handle.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            data = handle.read(min(chunk_size, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data


async def _read_and_normalize(
    upload: UploadFile, max_bytes: int, label: str
) -> NormalizedImage:
    raw = await upload.read(max_bytes + 1)
    await upload.close()
    return await asyncio.to_thread(normalize_upload, raw, max_bytes, label)
