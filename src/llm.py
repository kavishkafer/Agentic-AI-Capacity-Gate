"""Minimal pluggable LLM client.

Backends, in the order `auto` tries them:
  * ollama   — POST {host}/api/chat            (default host http://localhost:11434)
  * openai   — POST {host}/v1/chat/completions (vLLM, TGI, LM Studio, llama.cpp server)
  * mock     — deterministic offline stub, for testing the harness with no model

Standard library only: no vendor SDK, no dependency to install on the box that
holds the models.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass
class Reply:
    text: str
    model: str
    backend: str
    ok: bool = True
    error: str = ""


def _post(url: str, payload: dict, timeout: int = 180) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


class Client:
    def __init__(self, backend: str = "auto", model: str = "",
                 host: str = "http://localhost:11434", timeout: int = 180):
        self.host = host.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.backend = backend if backend != "auto" else self._detect()

    # ------------------------------------------------------------------ #

    def _detect(self) -> str:
        try:
            with urllib.request.urlopen(f"{self.host}/api/tags", timeout=5) as r:
                tags = json.loads(r.read())
            names = [m["name"] for m in tags.get("models", [])]
            if names and not self.model:
                self.model = names[0]
            return "ollama"
        except Exception:
            pass
        for base in (self.host, "http://localhost:8000"):
            try:
                with urllib.request.urlopen(f"{base}/v1/models", timeout=5) as r:
                    ms = json.loads(r.read())
                ids = [m["id"] for m in ms.get("data", [])]
                if ids and not self.model:
                    self.model = ids[0]
                self.host = base
                return "openai"
            except Exception:
                continue
        return "mock"

    def available_models(self) -> list[str]:
        try:
            if self.backend == "ollama":
                with urllib.request.urlopen(f"{self.host}/api/tags", timeout=5) as r:
                    return [m["name"] for m in json.loads(r.read()).get("models", [])]
            if self.backend == "openai":
                with urllib.request.urlopen(f"{self.host}/v1/models", timeout=5) as r:
                    return [m["id"] for m in json.loads(r.read()).get("data", [])]
        except Exception:
            pass
        return []

    # ------------------------------------------------------------------ #

    def chat(self, system: str, user: str, temperature: float = 0.0,
             max_tokens: int | None = None) -> Reply:
        if self.backend == "mock":
            return Reply(_mock_reply(user), "mock", "mock")
        try:
            if self.backend == "ollama":
                options = {"temperature": temperature}
                if max_tokens is not None:
                    options["num_predict"] = max_tokens
                out = _post(f"{self.host}/api/chat", {
                    "model": self.model,
                    "messages": [{"role": "system", "content": system},
                                 {"role": "user", "content": user}],
                    "stream": False,
                    "options": options,
                }, self.timeout)
                return Reply(out["message"]["content"], self.model, "ollama")

            payload = {
                "model": self.model,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}],
                "temperature": temperature,
            }
            if max_tokens is not None:
                payload["max_tokens"] = max_tokens
            out = _post(f"{self.host}/v1/chat/completions", payload, self.timeout)
            return Reply(out["choices"][0]["message"]["content"], self.model, "openai")

        except (urllib.error.URLError, KeyError, TimeoutError, OSError) as e:
            return Reply("", self.model, self.backend, ok=False, error=str(e))


# --------------------------------------------------------------------------- #
#  response parsing
# --------------------------------------------------------------------------- #

_JSON_BLOCK = re.compile(r"\{.*\}", re.S)


def parse_json(text: str) -> dict | None:
    """Pull the first JSON object out of a reply, tolerating code fences and prose."""
    if not text:
        return None
    t = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M)
    m = _JSON_BLOCK.search(t)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        # last resort: trailing-comma repair
        try:
            return json.loads(re.sub(r",\s*([}\]])", r"\1", m.group(0)))
        except json.JSONDecodeError:
            return None


# --------------------------------------------------------------------------- #
#  mock backend — exercises the harness without a model
# --------------------------------------------------------------------------- #

def _mock_reply(user: str) -> str:
    """Deterministic stand-in. Deliberately over-claims provability, which is the
    behaviour the experiment is built to detect — so a mock run should show a
    non-zero capacity-violation rate and prove the scoring path works."""
    m = re.search(r"\b(T\d{4}(?:\.\d{3})?)\b", user)
    tid = m.group(1) if m else "T0836"
    avail = re.findall(r"^\s*-\s+(.+)$", user, re.M)[:3]
    return json.dumps({
        "technique_id": tid,
        "technique_name": "mock",
        "provable_from_available_telemetry": True,
        "supporting_data_components": avail,
        "reasoning": "mock backend: asserts provability unconditionally",
    })
