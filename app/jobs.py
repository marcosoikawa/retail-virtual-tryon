"""Registro em memoria dos jobs de geracao de video."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Literal

logger = logging.getLogger(__name__)

VideoStatus = Literal["queued", "in_progress", "completed", "failed", "cancelled"]
ACTIVE_STATUSES: frozenset[str] = frozenset({"queued", "in_progress"})

STAGE_LABELS: dict[str, str] = {
    "uploading": "Enviando",
    "queued": "Na fila",
    "rendering": "Renderizando",
    "finalizing": "Finalizando",
    "done": "Concluido",
}

JOB_TTL_SECONDS = 6 * 60 * 60


@dataclass(slots=True)
class VideoJob:
    id: str
    image_id: str
    camera_motion: str
    duration: int
    size: str
    status: VideoStatus = "queued"
    stage: str = "uploading"
    progress: int = 0
    video_filename: str | None = None
    error: str | None = None
    remote_id: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    task: asyncio.Task[None] | None = field(default=None, repr=False)

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES

    def to_dict(self) -> dict[str, object]:
        return {
            "job_id": self.id,
            "image_id": self.image_id,
            "status": self.status,
            "stage": self.stage,
            "stage_label": STAGE_LABELS.get(self.stage, self.stage),
            "progress": self.progress,
            "elapsed_ms": int((self.updated_at - self.created_at) * 1000),
            "video_url": f"/videos/{self.video_filename}" if self.video_filename else None,
            "error": self.error,
        }


class JobRegistry:
    """Armazena jobs da sessao do processo; nao persiste em disco."""

    def __init__(self, max_concurrent: int) -> None:
        self._jobs: dict[str, VideoJob] = {}
        self._lock = asyncio.Lock()
        self._max_concurrent = max_concurrent

    async def create(self, image_id: str, camera_motion: str, duration: int, size: str) -> VideoJob:
        async with self._lock:
            self._prune_locked()
            if self._active_count_locked() >= self._max_concurrent:
                raise CapacityError(
                    "Limite de videos simultaneos atingido. Aguarde a conclusao de um job."
                )
            job = VideoJob(
                id=str(uuid.uuid4()),
                image_id=image_id,
                camera_motion=camera_motion,
                duration=duration,
                size=size,
            )
            self._jobs[job.id] = job
            return job

    async def get(self, job_id: str) -> VideoJob | None:
        async with self._lock:
            return self._jobs.get(job_id)

    async def update(self, job_id: str, **fields: object) -> VideoJob | None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if job.status in {"cancelled", "failed"} and fields.get("status") == "completed":
                return job
            for key, value in fields.items():
                setattr(job, key, value)
            job.updated_at = time.time()
            return job

    async def attach_task(self, job_id: str, task: asyncio.Task[None]) -> None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.task = task

    async def cancel(self, job_id: str) -> VideoJob | None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if not job.is_active:
                return job
            job.status = "cancelled"
            job.stage = "done"
            job.error = None
            job.updated_at = time.time()
            task = job.task
        if task is not None and not task.done():
            task.cancel()
        logger.info("Job de video %s cancelado pelo usuario.", job_id)
        return job

    async def cancel_all(self) -> None:
        async with self._lock:
            tasks = [job.task for job in self._jobs.values() if job.task and not job.task.done()]
        for task in tasks:
            task.cancel()

    async def active_count(self) -> int:
        async with self._lock:
            return self._active_count_locked()

    def _active_count_locked(self) -> int:
        return sum(1 for job in self._jobs.values() if job.is_active)

    def _prune_locked(self) -> None:
        cutoff = time.time() - JOB_TTL_SECONDS
        stale = [
            job_id
            for job_id, job in self._jobs.items()
            if not job.is_active and job.updated_at < cutoff
        ]
        for job_id in stale:
            self._jobs.pop(job_id, None)


class CapacityError(RuntimeError):
    """Nao ha capacidade para aceitar mais um job de video."""
