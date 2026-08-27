"""
Embedding generation service.

**Provider: OpenRouter — liquid/lfm-2.5-embedding-350m:free (1024 dimensions)**
Uses the OpenAI-compatible endpoint at https://openrouter.ai/api/v1.
Matches the `vector(1024)` columns in the database schema.

Requires OPENROUTER_API_KEY in .env (already used for LLM calls too).
"""

import time
import random
import requests
from app.config import settings

MODEL = "liquid/lfm-2.5-embedding-350m:free"
DIMENSIONS = 1024
BASE_URL = "https://openrouter.ai/api/v1"

# Retry config for free-tier rate limits
MAX_RETRIES = 5
INITIAL_BACKOFF = 1.0  # seconds


def generate_embedding(text: str) -> list[float]:
    """
    Generate a 1024-dim embedding via OpenRouter (free model).

    Includes exponential backoff with jitter for rate-limit resilience
    during bulk seeding.

    Raises RuntimeError if OPENROUTER_API_KEY is not configured.
    """
    if not settings.OPENROUTER_API_KEY:
        raise RuntimeError(
            "OPENROUTER_API_KEY is required for embedding generation. "
            "Add it to your .env file."
        )

    # Truncate to ~8k tokens (~32k chars) to stay within model limits
    truncated = text[:32_000] if len(text) > 32_000 else text

    last_exc: Exception | None = None
    backoff = INITIAL_BACKOFF

    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.post(
                f"{BASE_URL}/embeddings",
                headers={
                    "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": MODEL,
                    "input": truncated,
                    # No "dimensions" param — model outputs 1024 natively
                },
                timeout=30,
            )

            # Retry on rate-limit (429) or server errors (5xx)
            if resp.status_code == 429 or resp.status_code >= 500:
                resp.raise_for_status()

            resp.raise_for_status()
            data = resp.json()
            return data["data"][0]["embedding"]

        except requests.exceptions.HTTPError as exc:
            last_exc = exc
            status = getattr(exc.response, "status_code", None)
            if status == 429 or (status and status >= 500):
                # Exponential backoff with jitter
                jitter = random.uniform(0, backoff * 0.5)
                time.sleep(backoff + jitter)
                backoff = min(backoff * 2, 60)
                continue
            raise  # Non-retryable HTTP error

        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            last_exc = exc
            jitter = random.uniform(0, backoff * 0.5)
            time.sleep(backoff + jitter)
            backoff = min(backoff * 2, 60)
            continue

    raise RuntimeError(
        f"Embedding generation failed after {MAX_RETRIES} retries: {last_exc}"
    )
