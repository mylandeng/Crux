from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol

from langchain_openai import OpenAIEmbeddings

from curx.core.config import Settings

TOKEN_PATTERN = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


class EmbeddingModel(Protocol):
    @property
    def provider(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...


class LocalHashEmbedding:
    def __init__(self, dimension: int, model_name: str) -> None:
        if dimension < 32:
            raise ValueError("The embedding dimension must be at least 32.")
        self._dimension = dimension
        self._model_name = model_name

    @property
    def provider(self) -> str:
        return "local"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self._dimension
        tokens = TOKEN_PATTERN.findall(text.lower())
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self._dimension
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm:
            return [value / norm for value in vector]
        return vector

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]


class OpenAIEmbeddingModel:
    def __init__(self, settings: Settings) -> None:
        self._dimension = settings.embedding_dimension
        self._model_name = settings.embedding_model_name
        self._client = OpenAIEmbeddings(
            model=settings.embedding_model_name,
            api_key=settings.embedding_api_key,
            base_url=settings.embedding_base_url,
            dimensions=settings.embedding_dimension,
        )

    @property
    def provider(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors = self._client.embed_documents(texts)
        if any(len(vector) != self._dimension for vector in vectors):
            raise ValueError("The embedding provider returned an unexpected dimension.")
        return vectors


def create_embedding_model(settings: Settings) -> EmbeddingModel:
    provider = settings.embedding_provider.strip().lower()
    if settings.embedding_dimension != 384:
        raise ValueError("The MVP vector index is fixed to 384 dimensions.")
    if provider == "local":
        return LocalHashEmbedding(settings.embedding_dimension, settings.embedding_model_name)
    if provider == "openai":
        return OpenAIEmbeddingModel(settings)
    raise ValueError(f"Unsupported embedding provider: {settings.embedding_provider}.")

