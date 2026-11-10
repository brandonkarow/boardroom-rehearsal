"""Claude client, strict JSON handling, and the demo-mode cache.

Live mode: calls the Anthropic API and records each validated output in the cache.
Demo mode (no API key): serves the cached outputs for the Northbeam sample, so the
whole flow works without a key. The cache is keyed by task + a hash of the input
data (not the prompt wording), so it stays valid while prompts are tuned.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "prompts"
CACHE_PATH = ROOT / "demo_cache" / "cache.json"
MODEL = os.getenv("BR_MODEL", "claude-sonnet-5-5")
MAX_TOKENS = 4000


class LLMError(RuntimeError):
    """Raised with a message that is safe to show in the UI."""


class DemoCacheMiss(LLMError):
    pass


def read_prompt(name: str) -> str:
    return (PROMPTS / name).read_text()


def get_api_key() -> str | None:
    """Streamlit secrets first, then the environment (and a local .env)."""
    try:
        import streamlit as st
        key = st.secrets.get("ANTHROPIC_API_KEY")  # raises if no secrets file
        if isinstance(key, str) and key.strip():
            return key.strip()
    except Exception:
        pass
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except Exception:
        pass
    return os.getenv("ANTHROPIC_API_KEY") or None


# ---- Clients ----------------------------------------------------------------

class Client(Protocol):
    def complete(self, system: str, user: str) -> str: ...


class AnthropicClient:
    def __init__(self, api_key: str, model: str = MODEL):
        import anthropic  # imported lazily so demo mode needs no SDK at import time
        self._client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def complete(self, system: str, user: str) -> str:
        try:
            msg = self._client.messages.create(
                model=self.model, max_tokens=MAX_TOKENS, system=system,
                messages=[{"role": "user", "content": user}])
        except Exception as exc:
            raise LLMError(f"The AI call failed ({exc.__class__.__name__}). "
                           "Check the API key and spend limit, or use demo mode.") from exc
        return "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text")


# ---- JSON -------------------------------------------------------------------

def parse_json(text: str) -> Any:
    """Parse a JSON object, tolerating code fences or stray text around it."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        start, end = t.find("{"), t.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("no JSON object found in the reply")
        return json.loads(t[start:end + 1])


def call_json(client: Client, system: str, user: str,
              validate: Callable[[Any], Any], retries: int = 1) -> Any:
    """Call the model, parse and validate JSON; on failure, retry once with the error."""
    prompt, last_err = user, None
    for _ in range(retries + 1):
        text = client.complete(system, prompt)
        try:
            return validate(parse_json(text))
        except (ValueError, KeyError, TypeError) as exc:
            last_err = str(exc)
            prompt = (user + "\n\nYour previous reply could not be used: " + last_err
                      + ". Reply again with only valid JSON in the required shape.")
    raise LLMError(f"The AI returned invalid output twice ({last_err}).")


# ---- Demo cache -------------------------------------------------------------

def data_hash(*parts: Any) -> str:
    blob = json.dumps(parts, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


class DemoCache:
    def __init__(self, path: Path = CACHE_PATH):
        self.path = path
        self.entries: dict[str, dict] = {}
        if path.exists():
            try:
                self.entries = json.loads(path.read_text())
            except Exception:
                self.entries = {}

    def get(self, key: str) -> Any | None:
        e = self.entries.get(key)
        return None if e is None else e["output"]

    def put(self, key: str, task: str, output: Any, model: str) -> None:
        self.entries[key] = {"task": task, "model": model, "output": output,
                             "created": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        try:  # best effort: Streamlit Cloud's disk is ephemeral; the UI offers a download
            self.path.parent.mkdir(exist_ok=True)
            self.path.write_text(json.dumps(self.entries, indent=2))
        except OSError:
            pass

    def export(self) -> str:
        return json.dumps(self.entries, indent=2)


class LLM:
    """One entry point for every AI call, in live or demo mode."""

    def __init__(self, client: Client | None = None, cache: DemoCache | None = None):
        self.cache = cache or DemoCache()
        if client is None:
            key = get_api_key()
            client = AnthropicClient(key) if key else None
        self.client = client
        self.mode = "live" if client else "demo"
        self.model = getattr(client, "model", MODEL) if client else "cached"

    def json(self, task: str, key_parts: tuple, system: str, user: str,
             validate: Callable[[Any], Any]) -> Any:
        key = f"{task}:{data_hash(*key_parts)}"
        if self.mode == "demo":
            out = self.cache.get(key)
            if out is None:
                raise DemoCacheMiss(
                    "Demo mode has cached results only for the Northbeam sample. "
                    "Add an ANTHROPIC_API_KEY to rehearse with your own data.")
            return validate(out)
        out = call_json(self.client, system, user, validate)
        self.cache.put(key, task, out, self.model)
        return out
