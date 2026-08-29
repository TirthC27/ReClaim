"""
OpenRouter LLM client with fallback chain and retry.

Step 1 (strategy): DeepSeek only (cheapest)
Step 2 (compose):  DeepSeek → Qwen → Gemini Flash fallback chain
"""

import json
import logging
import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://openrouter.ai/api/v1"

# Model assignments
STEP1_MODELS = ["upstage/solar-pro4"]
STEP2_MODELS = [
    "upstage/solar-pro4",
    "qwen/qwen3-235b-a22b-2507",
    "google/gemini-2.5-flash-preview-05-20",
]


class LLMError(Exception):
    """Raised when all models in a fallback chain fail."""
    pass


def _call_openrouter(model: str, system_prompt: str, user_content: str) -> dict:
    """
    Single LLM call to OpenRouter. Returns parsed JSON response.

    Raises on HTTP errors or JSON parse failures so the fallback chain continues.
    """
    resp = requests.post(
        f"{BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.4,
        },
        timeout=60,
    )
    resp.raise_for_status()

    data = resp.json()
    content = data["choices"][0]["message"]["content"]

    # Strip markdown code fences if the model wraps output
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:-1]) if len(lines) > 2 else content

    return json.loads(content)


def call_with_fallback(
    models: list[str],
    system_prompt: str,
    user_content: str,
    step_name: str = "llm",
) -> dict:
    """
    Try each model in the fallback chain. Return first successful result.

    Each model gets up to 2 attempts with exponential backoff before
    moving to the next model in the chain.
    """
    last_error: Exception | None = None

    for model in models:
        for attempt in range(2):
            try:
                logger.info(f"[{step_name}] Trying {model} (attempt {attempt + 1})")
                result = _call_openrouter(model, system_prompt, user_content)
                logger.info(f"[{step_name}] Success with {model}")
                return result
            except requests.exceptions.HTTPError as exc:
                status = getattr(exc.response, "status_code", None)
                logger.warning(
                    f"[{step_name}] {model} HTTP {status}: {exc}"
                )
                last_error = exc
                if status == 429:
                    import time
                    time.sleep(2 ** (attempt + 1))
                    continue
                break  # Non-retryable HTTP error, try next model
            except (json.JSONDecodeError, KeyError, IndexError) as exc:
                logger.warning(f"[{step_name}] {model} parse error: {exc}")
                last_error = exc
                break  # Parse error, try next model
            except Exception as exc:
                logger.warning(f"[{step_name}] {model} error: {exc}")
                last_error = exc
                break

    raise LLMError(f"All models failed for {step_name}: {last_error}")


def call_step1(system_prompt: str, user_content: str) -> dict:
    """Step 1 — Strategy agent (DeepSeek only)."""
    return call_with_fallback(STEP1_MODELS, system_prompt, user_content, "step1-strategy")


def call_step2(system_prompt: str, user_content: str) -> dict:
    """Step 2 — Offer composer (DeepSeek → Qwen → Gemini fallback chain)."""
    return call_with_fallback(STEP2_MODELS, system_prompt, user_content, "step2-compose")
