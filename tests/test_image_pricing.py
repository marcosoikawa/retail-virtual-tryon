import base64
import io
import json
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock

import httpx

from app.config import Settings
from app.main import MetricsStore
from PIL import Image

from app.tryon_service import (
    ImageTokenUsage,
    TryOnError,
    TryOnService,
    _extract_usage,
    _image_megapixels,
)


class ImageUsageTests(TestCase):
    def test_measures_image_megapixels(self) -> None:
        buffer = io.BytesIO()
        Image.new("RGB", (1_000, 500)).save(buffer, format="PNG")

        self.assertEqual(_image_megapixels(buffer.getvalue()), 0.5)

    def test_extracts_text_and_image_token_details(self) -> None:
        response = SimpleNamespace(
            usage=SimpleNamespace(
                input_tokens=1_100,
                output_tokens=2_000,
                input_tokens_details=SimpleNamespace(text_tokens=100, image_tokens=1_000),
            )
        )

        usage = _extract_usage(response)

        self.assertEqual(usage, ImageTokenUsage(100, 1_000, 2_000))

    def test_treats_aggregated_input_as_image_tokens(self) -> None:
        response = {"usage": {"input_tokens": 1_100, "output_tokens": 2_000}}

        usage = _extract_usage(response)

        self.assertEqual(usage, ImageTokenUsage(0, 1_100, 2_000))


class ImagePricingTests(IsolatedAsyncioTestCase):
    async def _cost_for(self, model: str) -> float:
        metrics = MetricsStore(Settings(_env_file=None))
        await metrics.record_image_generation(
            model=model,
            input_text_tokens=100,
            input_image_tokens=1_000,
            output_image_tokens=2_000,
            elapsed_ms=1_000,
            image_id="test-image",
        )
        snapshot = await metrics.snapshot()
        cost = snapshot["cost"]
        assert isinstance(cost, dict)
        return float(cost["total"])

    async def test_gpt_image_2_prices_each_token_type(self) -> None:
        self.assertEqual(await self._cost_for("gpt-image-2"), 0.0685)

    async def test_gpt_image_1_mini_prices_each_token_type(self) -> None:
        self.assertEqual(await self._cost_for("gpt-image-1-mini"), 0.0187)

    def test_flux_2_pro_prices_initial_additional_and_reference_mp(self) -> None:
        settings = Settings(_env_file=None)

        cost = settings.image_generation_cost(
            "FLUX.2-pro", 0, 0, 0, input_megapixels=2.0, output_megapixels=1.5
        )

        self.assertAlmostEqual(cost, 0.0675)

    def test_flux_2_flex_prices_all_megapixels(self) -> None:
        settings = Settings(_env_file=None)

        cost = settings.image_generation_cost(
            "FLUX.2-flex", 0, 0, 0, input_megapixels=2.0, output_megapixels=1.5
        )

        self.assertAlmostEqual(cost, 0.175)

    async def test_gpt_and_flux_consolidate_with_their_own_pricing(self) -> None:
        metrics = MetricsStore(Settings(_env_file=None))
        await metrics.record_image_generation(
            "gpt-image-2", 100, 1_000, 2_000, 1_000, "gpt-image"
        )
        await metrics.record_image_generation(
            "FLUX.2-pro",
            0,
            0,
            0,
            900,
            "flux-image",
            input_megapixels=2.0,
            output_megapixels=1.5,
        )

        snapshot = await metrics.snapshot()
        cost = snapshot["cost"]

        self.assertEqual(cost["per_image"], 0.068)  # type: ignore[index]
        self.assertTrue(cost["complete"])  # type: ignore[index]
        self.assertEqual(cost["unpriced_images"], 0)  # type: ignore[index]
        flux_execution = snapshot["executions"][0]  # type: ignore[index]
        self.assertEqual(flux_execution["input_megapixels"], 2.0)
        self.assertEqual(flux_execution["output_megapixels"], 1.5)


class ImageRequestTests(IsolatedAsyncioTestCase):
    async def _request_kwargs(self, model: str) -> dict[str, object]:
        response = SimpleNamespace(
            data=[SimpleNamespace(b64_json="aW1hZ2U=")],
            usage=SimpleNamespace(
                input_tokens=0,
                output_tokens=0,
                input_tokens_details=SimpleNamespace(text_tokens=0, image_tokens=0),
            ),
        )
        edit = AsyncMock(return_value=response)
        client = SimpleNamespace(images=SimpleNamespace(edit=edit))
        service = TryOnService(Settings(_env_file=None))

        await service._call_with_retry(
            client=client,
            files=[],
            prompt="test",
            model=model,
            deployment=model,
        )

        return edit.await_args.kwargs

    async def _request_extra_body(self, model: str) -> object:
        return (await self._request_kwargs(model))["extra_body"]

    async def test_gpt_image_2_requests_high_input_fidelity(self) -> None:
        self.assertEqual(
            await self._request_extra_body("gpt-image-2"),
            {"input_fidelity": "high"},
        )

    async def test_gpt_image_1_mini_omits_input_fidelity(self) -> None:
        self.assertIsNone(await self._request_extra_body("gpt-image-1-mini"))

    async def test_gpt_image_2_uses_supported_portrait_size(self) -> None:
        self.assertEqual((await self._request_kwargs("gpt-image-2"))["size"], "1024x1536")

    async def test_gpt_image_1_mini_uses_supported_portrait_size(self) -> None:
        self.assertEqual(
            (await self._request_kwargs("gpt-image-1-mini"))["size"],
            "1024x1536",
        )

    async def test_gpt_requests_low_cost_output_parameters(self) -> None:
        request = await self._request_kwargs("gpt-image-2")

        self.assertEqual(request["quality"], "low")
        self.assertEqual(request["output_format"], "jpeg")
        self.assertEqual(request["output_compression"], 80)
        self.assertEqual(request["n"], 1)

    async def _flux_request(self, model: str) -> tuple[dict[str, object], str, str, bytes]:
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["_path"] = request.url.path
            captured["_query"] = request.url.query.decode("ascii")
            captured["_authorization"] = request.headers.get("Authorization")
            captured.update(json.loads(request.content))
            return httpx.Response(
                200,
                json={"data": [{"b64_json": base64.b64encode(b"image").decode("ascii")}]},
            )

        settings = Settings(
            _env_file=None,
            azure_openai_endpoint="https://example.services.ai.azure.com",
            azure_openai_api_key="secret",
        )
        service = TryOnService(settings)
        await service._flux_client.aclose()
        service._flux_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            deployment = settings.image_deployment(model)
            image, _ = await service._call_flux(
                [("person.png", b"person", "image/png"), ("garment.png", b"garment", "image/png")],
                "test prompt",
                model,
                deployment,
            )
        finally:
            await service.close()

        path = settings.flux_model_path(model)
        return captured, path, deployment, image

    async def test_flux_2_pro_uses_provider_payload(self) -> None:
        payload, path, deployment, image = await self._flux_request("FLUX.2-pro")

        self.assertEqual(path, "flux-2-pro")
        self.assertEqual(payload["_path"], "/providers/blackforestlabs/v1/flux-2-pro")
        self.assertEqual(payload["_query"], "api-version=preview")
        self.assertEqual(payload["_authorization"], "Bearer secret")
        self.assertEqual(payload["model"], deployment)
        self.assertEqual((payload["width"], payload["height"]), (300, 400))
        self.assertEqual(payload["output_format"], "jpeg")
        self.assertEqual(payload["num_images"], 1)
        self.assertEqual(base64.b64decode(payload["input_image"]), b"person")  # type: ignore[arg-type]
        self.assertEqual(base64.b64decode(payload["input_image_2"]), b"garment")  # type: ignore[arg-type]
        self.assertEqual(image, b"image")

    async def test_flux_2_flex_uses_provider_payload(self) -> None:
        payload, path, _, image = await self._flux_request("FLUX.2-flex")

        self.assertEqual(path, "flux-2-flex")
        self.assertEqual(payload["model"], "FLUX.2-flex")
        self.assertEqual(image, b"image")

    async def test_flux_2_pro_rejects_more_than_eight_references(self) -> None:
        service = TryOnService(Settings(_env_file=None))
        files = [(f"{index}.png", b"image", "image/png") for index in range(9)]
        try:
            with self.assertRaises(TryOnError):
                await service._call_flux(files, "prompt", "FLUX.2-pro", "flux-2-pro")
        finally:
            await service.close()