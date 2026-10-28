"""Embedding provider selection: SiliconFlow, OpenAI-compatible, local."""

from __future__ import annotations

import json

import httpx
import pytest

from strata_memory.config import (
    EmbeddingConfig,
    embedding_requires_api_key,
    resolve_embedding_settings,
)
from strata_memory.embedding.base import EmbeddingProvider
from strata_memory.embedding.bge3_siliconflow import BGE3SiliconFlowProvider
from strata_memory.embedding.local import LocalEmbeddingProvider
from strata_memory.embedding.openai_compatible import OpenAICompatibleEmbeddingProvider

_EMBED_ENV = (
    "STRATA_EMBEDDING_PROVIDER",
    "STRATA_EMBEDDING_BASE_URL",
    "STRATA_EMBEDDING_MODEL",
    "STRATA_EMBEDDING_DIMENSION",
    "STRATA_EMBEDDING_TRUNCATE",
    "STRATA_EMBEDDING_ALLOW_EMPTY_KEY",
    "STRATA_EMBEDDING_API_KEY",
    "STRATA_API_KEY",
    "SILICONFLOW_API_KEY",
    "OPENAI_API_KEY",
)


@pytest.fixture
def clean_embed_env(monkeypatch):
    for name in _EMBED_ENV:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_defaults_are_local(clean_embed_env):
    settings = resolve_embedding_settings(EmbeddingConfig())
    assert settings.provider == "local"
    assert settings.model == "sentence-transformers/all-MiniLM-L6-v2"
    assert settings.base_url == ""
    assert settings.dimension == 384
    assert not embedding_requires_api_key(settings.provider, settings.base_url)


def test_env_can_still_select_siliconflow(clean_embed_env):
    clean_embed_env.setenv("STRATA_EMBEDDING_PROVIDER", "siliconflow")
    settings = resolve_embedding_settings(EmbeddingConfig())
    assert settings.provider == "siliconflow"
    assert settings.model == "BAAI/bge-m3"
    assert settings.base_url == "https://api.siliconflow.cn/v1"
    assert embedding_requires_api_key(settings.provider, settings.base_url)


def test_env_overrides_saved_endpoint(clean_embed_env):
    clean_embed_env.setenv("STRATA_EMBEDDING_BASE_URL", "https://embed.example/v1/")
    clean_embed_env.setenv("STRATA_EMBEDDING_MODEL", "custom-embed")
    clean_embed_env.setenv("STRATA_EMBEDDING_DIMENSION", "768")
    saved = EmbeddingConfig(provider="siliconflow", model="BAAI/bge-m3", dimension=384)
    settings = resolve_embedding_settings(saved)
    assert settings.provider == "siliconflow"
    assert settings.model == "custom-embed"
    assert settings.base_url == "https://embed.example/v1"
    assert settings.dimension == 768


def test_provider_switch_uses_that_providers_defaults(clean_embed_env):
    clean_embed_env.setenv("STRATA_EMBEDDING_PROVIDER", "openai")
    settings = resolve_embedding_settings(EmbeddingConfig())
    assert settings.provider == "openai"
    assert settings.model == "text-embedding-3-small"
    assert settings.base_url == "https://api.openai.com/v1"
    assert settings.dimension == 1536
    assert embedding_requires_api_key(settings.provider, settings.base_url)


def test_explicit_override_beats_env(clean_embed_env):
    clean_embed_env.setenv("STRATA_EMBEDDING_PROVIDER", "openai")
    clean_embed_env.setenv("STRATA_EMBEDDING_MODEL", "from-env")
    settings = resolve_embedding_settings(
        EmbeddingConfig(),
        overrides={"provider": "local", "model": "from-arg"},
    )
    assert settings.provider == "local"
    assert settings.model == "from-arg"
    assert settings.base_url == ""
    assert settings.dimension == 384
    assert not embedding_requires_api_key(settings.provider, settings.base_url)


def test_loopback_endpoint_does_not_require_a_key(clean_embed_env):
    assert not embedding_requires_api_key("openai_compatible", "http://127.0.0.1:11434/v1")
    assert not embedding_requires_api_key("openai_compatible", "http://localhost:8080/v1")
    assert embedding_requires_api_key("openai_compatible", "https://api.openai.com/v1")


def test_provider_specific_key_order(clean_embed_env):
    clean_embed_env.setenv("OPENAI_API_KEY", "sk-openaiopenaiopenaiopenaiopenai")
    clean_embed_env.setenv("SILICONFLOW_API_KEY", "sk-siliconflowsiliconflowsiliconflow")
    silicon = resolve_embedding_settings(EmbeddingConfig(), overrides={"provider": "siliconflow"})
    openai = resolve_embedding_settings(EmbeddingConfig(), overrides={"provider": "openai"})
    assert silicon.api_key.startswith("sk-silicon")
    assert openai.api_key.startswith("sk-openai")


def test_embedding_api_key_beats_strata_api_key(clean_embed_env):
    clean_embed_env.setenv("STRATA_EMBEDDING_API_KEY", "sk-embeddingspecificembeddingspecific")
    clean_embed_env.setenv("STRATA_API_KEY", "sk-genericgenericgenericgeneric")
    settings = resolve_embedding_settings(EmbeddingConfig())
    assert settings.api_key.startswith("sk-embedding")


@pytest.mark.asyncio
async def test_openai_compatible_posts_memory_text(clean_embed_env):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={"data": [{"index": 0, "embedding": [0.25, 0.5, 0.75]}]},
        )

    provider = OpenAICompatibleEmbeddingProvider(
        model="my-embed",
        base_url="https://embed.example/v1",
        api_key="sk-abcdefghijklmnopqrstuvwxyz012345",
        dimension=3,
        truncate=False,
        transport=httpx.MockTransport(handler),
    )
    vec = await provider.embed("memory text leaves the machine")
    assert vec == [0.25, 0.5, 0.75]
    assert seen["url"] == "https://embed.example/v1/embeddings"
    assert seen["body"]["model"] == "my-embed"
    assert seen["body"]["input"] == ["memory text leaves the machine"]
    assert seen["auth"] == "Bearer sk-abcdefghijklmnopqrstuvwxyz012345"
    await provider.close()


@pytest.mark.asyncio
async def test_siliconflow_truncates_bge_m3(clean_embed_env):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [{"index": 0, "embedding": [float(i) for i in range(8)]}]},
        )

    provider = BGE3SiliconFlowProvider(
        model="BAAI/bge-m3",
        base_url="https://api.siliconflow.cn/v1",
        api_key="sk-abcdefghijklmnopqrstuvwxyz012345",
        dimension=4,
        transport=httpx.MockTransport(handler),
    )
    assert await provider.embed("fact") == [0.0, 1.0, 2.0, 3.0]
    await provider.close()


@pytest.mark.asyncio
async def test_non_mrl_model_rejects_dimension_mismatch(clean_embed_env):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3, 0.4]}]},
        )

    provider = OpenAICompatibleEmbeddingProvider(
        model="text-embedding-3-small",
        base_url="https://api.openai.com/v1",
        api_key="sk-abcdefghijklmnopqrstuvwxyz012345",
        dimension=3,
        truncate=False,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(RuntimeError, match="STRATA_EMBEDDING_DIMENSION"):
        await provider.embed("fact")
    await provider.close()


def test_factory_routes_providers(clean_embed_env):
    local = EmbeddingProvider.create("local", "sentence-transformers/all-MiniLM-L6-v2", "", "", 384)
    assert isinstance(local, LocalEmbeddingProvider)
    silicon = EmbeddingProvider.create(
        "siliconflow",
        "BAAI/bge-m3",
        "https://api.siliconflow.cn/v1",
        "sk-abcdefghijklmnopqrstuvwxyz012345",
        384,
    )
    assert isinstance(silicon, BGE3SiliconFlowProvider)
    other = EmbeddingProvider.create(
        "openai_compatible",
        "text-embedding-3-small",
        "https://api.openai.com/v1",
        "sk-abcdefghijklmnopqrstuvwxyz012345",
        1536,
    )
    assert isinstance(other, OpenAICompatibleEmbeddingProvider)
    assert not isinstance(other, BGE3SiliconFlowProvider)


@pytest.mark.asyncio
async def test_local_without_extra_uses_hashing_embedder(clean_embed_env):
    provider = LocalEmbeddingProvider(model="sentence-transformers/all-MiniLM-L6-v2", dimension=384)
    vec = await provider.embed("stays on device")
    assert provider._backend == "hashing"
    assert len(vec) == 384
    assert abs(sum(v * v for v in vec) - 1.0) < 1e-6
    assert vec == await provider.embed("stays on device")
    assert "uv sync --extra local" in provider.install_hint
    await provider.close()
