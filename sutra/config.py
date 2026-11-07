"""Configuration loading.

Reads `config/sutra.yaml` (Sutra's config: model, tools, limits) and
`config/agents/*.yaml` (one YAML per agent Sutra manages). Environment
variables override the YAML values.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(__file__).resolve().parent / "config"


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


def load_sutra_config() -> dict[str, Any]:
    cfg = _load_yaml(CONFIG_DIR / "sutra.yaml")
    # Environment overrides.
    if os.environ.get("OLLAMA_BASE_URL"):
        cfg["model"] = {**cfg.get("model", {}), "endpoint": os.environ["OLLAMA_BASE_URL"]}
    if os.environ.get("HUMAN_OWNER"):
        cfg["human_owner"] = os.environ["HUMAN_OWNER"]
    return cfg


def load_agent_configs() -> list[dict[str, Any]]:
    """Load every agent YAML in config/agents/."""
    agents_dir = CONFIG_DIR / "agents"
    if not agents_dir.exists():
        return []
    out = []
    for p in sorted(agents_dir.glob("*.yaml")):
        data = _load_yaml(p)
        if data:
            data["_source_file"] = p.name
            out.append(data)
    return out