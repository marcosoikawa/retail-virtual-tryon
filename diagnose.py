"""Diagnostico temporario: valida credencial, endpoint e deployments no Foundry."""

from __future__ import annotations

import asyncio
import json
import os
import re

import httpx
from azure.identity.aio import DefaultAzureCredential
from dotenv import load_dotenv

load_dotenv()

RAW = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
BASE = re.sub(r"/openai(/v1)?/?$", "", RAW.rstrip("/"))
SCOPES = ["https://ai.azure.com/.default"]


async def main() -> None:
    print("endpoint bruto :", RAW)
    print("endpoint base  :", BASE)

    tokens: dict[str, str] = {}
    async with DefaultAzureCredential() as credential:
        for scope in SCOPES:
            try:
                token = await credential.get_token(scope)
                tokens[scope] = token.token
                print(f"token OK       : {scope}")
            except Exception as exc:  # noqa: BLE001
                print(f"token FALHOU   : {scope} -> {type(exc).__name__}: {exc}")

        if not tokens:
            return

        scope, token = next(iter(tokens.items()))
        headers = {"Authorization": f"Bearer {token}"}

        async with httpx.AsyncClient(timeout=45.0) as client:
            for label, url in [
                ("deployments (classic)", f"{BASE}/openai/deployments?api-version=2023-05-15"),
                ("models (v1)", f"{BASE}/openai/v1/models?api-version=preview"),
            ]:
                try:
                    response = await client.get(url, headers=headers)
                    print(f"\n--- {label} -> {response.status_code}")
                    if response.status_code == 200:
                        payload = response.json()
                        for item in payload.get("data", []):
                            name = item.get("id")
                            model = item.get("model") or item.get("id")
                            print(f"    {name}  (model={model})")
                    else:
                        print("    ", response.text[:500])
                except Exception as exc:  # noqa: BLE001
                    print(f"\n--- {label} -> ERRO {type(exc).__name__}: {exc}")

if __name__ == "__main__":
    asyncio.run(main())
