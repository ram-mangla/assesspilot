"""Runtime model registry for suggestion-only Q&A. Separate from any dev-agent config.
Keys stay on the backend; nothing here is exposed to the frontend."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def _load_provider_env() -> None:
    """Load central .env (NVIDIA + OpenRouter keys) without overriding real env vars."""
    candidates = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parents[2] / ".env",
        Path.home() / ".quizagent" / ".env",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and v and not os.environ.get(k):
                os.environ[k] = v
        break


_load_provider_env()


@dataclass(frozen=True)
class ModelSpec:
    logical_name: str
    provider: str           # nvidia | openrouter
    model_id: str
    capabilities: frozenset[str]
    free: bool = True

    @property
    def base_url(self) -> str:
        return NVIDIA_BASE_URL if self.provider == "nvidia" else OPENROUTER_BASE_URL

    @property
    def key_env(self) -> str:
        return "NVIDIA_API_KEY" if self.provider == "nvidia" else "OPENROUTER_API_KEY"


MODELS = {
    "nemotron_ultra": ModelSpec("nemotron_ultra", "nvidia", "nvidia/nemotron-3-ultra-550b-a55b", frozenset({"reasoning", "text", "structured"})),
    "nemotron_super_vl": ModelSpec("nemotron_super_vl", "nvidia", "nvidia/nemotron-3.5-super-vl-120b-a12b", frozenset({"vision", "image", "text", "structured"})),
    "nemotron_lightning": ModelSpec("nemotron_lightning", "nvidia", "nvidia/nemotron-3.5-lightning-30b-a3b", frozenset({"text", "general", "structured"})),
    "nemotron_ultra_or": ModelSpec("nemotron_ultra_or", "openrouter", "nvidia/nemotron-3-ultra-550b-a55b:free", frozenset({"reasoning", "text", "structured"})),
    "nemotron_super_vl_or": ModelSpec("nemotron_super_vl_or", "openrouter", "nvidia/nemotron-3.5-super-vl:free", frozenset({"vision", "image", "text", "structured"})),
    "nemotron_lightning_or": ModelSpec("nemotron_lightning_or", "openrouter", "nvidia/nemotron-3.5-lightning:free", frozenset({"text", "general", "structured"})),
    "north_mini_code": ModelSpec("north_mini_code", "openrouter", "cohere/north-mini-code:free", frozenset({"code", "text", "structured"})),
    "gemma_4": ModelSpec("gemma_4", "openrouter", "google/gemma-4-26b-a4b-it:free", frozenset({"vision", "image", "text", "structured"})),
    "nemotron_nano_omni": ModelSpec("nemotron_nano_omni", "openrouter", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free", frozenset({"vision", "image", "text", "multimodal", "structured"})),
}

_TASK_MAP = {
    "reasoning": ("nemotron_ultra", ["nemotron_ultra_or", "nemotron_lightning", "nemotron_lightning_or"]),
    "vision": ("nemotron_super_vl", ["nemotron_super_vl_or", "gemma_4", "nemotron_nano_omni"]),
    "general": ("nemotron_lightning", ["nemotron_lightning_or", "nemotron_nano_omni", "gemma_4"]),
    "code": ("north_mini_code", ["nemotron_ultra", "nemotron_ultra_or"]),
    "multimodal": ("nemotron_super_vl", ["nemotron_super_vl_or", "nemotron_nano_omni"]),
}


def task_map() -> dict:
    return {task: {"primary": slugs[0], "fallbacks": list(slugs[1:]), "chain": [slugs[0], *slugs[1]]}
            for task, slugs in _TASK_MAP.items()}


def missing_keys(specs: list[ModelSpec] | None = None) -> list[str]:
    specs = specs or list(MODELS.values())
    missing = []
    for env in sorted({s.key_env for s in specs}):
        if not os.environ.get(env):
            missing.append(env)
    return missing


def candidates_for(task: str, needs_image: bool = False, needs_code: bool = False) -> list[ModelSpec]:
    if task not in _TASK_MAP:
        raise ValueError(f"unknown task {task!r}; expected one of {sorted(_TASK_MAP)}")
    primary, fallbacks = _TASK_MAP[task]
    out, seen = [], set()
    for slug in (primary, *fallbacks):
        spec = MODELS[slug]
        if spec.logical_name in seen:
            continue
        seen.add(spec.logical_name)
        caps = spec.capabilities
        if needs_image and not ({"vision", "image", "multimodal"} & caps):
            continue
        if needs_code and not ({"code", "reasoning"} & caps):
            continue
        out.append(spec)
    if needs_image and not out:
        raise RuntimeError("no configured image-capable model available for this task")
    return out


def provider_chain(primary: str, task: str = "general", needs_image: bool = False) -> list[ModelSpec]:
    """Primary first, then every capable model of that task, then each provider's own
    general/vision model. No silent substitution: the chain is exactly what the task map
    plus the registry allow, and the provider actually used is reported back."""
    ordered: list[ModelSpec] = []
    if primary in MODELS:
        ordered.append(MODELS[primary])
    for spec in candidates_for(task, needs_image=needs_image):
        ordered.append(spec)
    tail = "vision" if needs_image else "general"
    for spec in candidates_for(tail, needs_image=needs_image):
        ordered.append(spec)
    out, seen = [], set()
    for spec in ordered:
        if spec.logical_name not in seen:
            seen.add(spec.logical_name)
            out.append(spec)
    return out


def capabilities_summary() -> dict:
    return {name: {"provider": s.provider, "model_id": s.model_id, "free": s.free,
                   "capabilities": sorted(s.capabilities)} for name, s in MODELS.items()}