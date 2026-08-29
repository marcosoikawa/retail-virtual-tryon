"""Reproduz o ciclo completo de video (criar -> polling -> download)."""

from __future__ import annotations

import asyncio
import sys

from app.config import close_credential, get_settings
from app.jobs import JobRegistry
from app.video_service import VideoService


async def main() -> None:
    settings = get_settings()
    images = sorted(settings.outputs_dir.glob("*.png"))
    if not images:
        print("Nenhuma imagem em outputs/. Rode _repro.py antes.")
        return
    image_path = settings.outputs_dir / sys.argv[1] if len(sys.argv) > 1 else images[-1]
    print("imagem base :", image_path.name)
    print("endpoint    :", settings.azure_openai_endpoint)
    print("deployment  :", settings.video_model_deployment)

    registry = JobRegistry(settings.max_concurrent_video_jobs)
    service = VideoService(settings)
    job = await registry.create(image_path.stem, "spin", 4, "720x1280")

    async def watch() -> None:
        last = ""
        while True:
            await asyncio.sleep(3)
            current = await registry.get(job.id)
            if current is None:
                return
            line = f"{current.status}/{current.stage} {current.progress}%"
            if line != last:
                print("  ", line)
                last = line
            if not current.is_active:
                return

    watcher = asyncio.create_task(watch())
    await service.run_job(job, registry, image_path, "")
    await watcher

    final = await registry.get(job.id)
    print("RESULTADO:", final.status, final.video_filename or final.error)
    await service.close()
    await close_credential()
    sys.exit(0 if final.status == "completed" else 1)


if __name__ == "__main__":
    asyncio.run(main())
