"""Ollama embedding and chat client."""

from __future__ import annotations

import json
from typing import Any

import httpx
import numpy as np

DEFAULT_EMBED_MODEL = "nomic-embed-text"
DEFAULT_CHAT_MODEL = "llama3.1:8b"
OLLAMA_BASE_URL = "http://127.0.0.1:11434"


class OllamaClient:
    def __init__(
        self,
        base_url: str = OLLAMA_BASE_URL,
        embed_model: str = DEFAULT_EMBED_MODEL,
        chat_model: str = DEFAULT_CHAT_MODEL,
        timeout: float = 120.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.embed_model = embed_model
        self.chat_model = chat_model
        self.timeout = timeout

    def is_available(self) -> bool:
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(f"{self.base_url}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False

    def embed(self, text: str) -> list[float]:
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                f"{self.base_url}/api/embeddings",
                json={"model": self.embed_model, "prompt": text},
            )
            resp.raise_for_status()
            data = resp.json()
            return data["embedding"]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]

    def chat(self, messages: list[dict[str, str]], stream: bool = False) -> str:
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.chat_model,
                    "messages": messages,
                    "stream": stream,
                },
            )
            resp.raise_for_status()
            if stream:
                parts = []
                for line in resp.iter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    if chunk.get("message", {}).get("content"):
                        parts.append(chunk["message"]["content"])
                return "".join(parts)
            return resp.json()["message"]["content"]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    denom = np.linalg.norm(va) * np.linalg.norm(vb)
    if denom == 0:
        return 0.0
    return float(np.dot(va, vb) / denom)


def reciprocal_rank_fusion(
    ranked_lists: list[list[tuple[int, float]]],
    k: int = 60,
) -> list[tuple[int, float]]:
    scores: dict[int, float] = {}
    for ranked in ranked_lists:
        for rank, (item_id, _score) in enumerate(ranked):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)
