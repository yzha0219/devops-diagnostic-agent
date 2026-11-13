"""Small environment-based configuration, intentionally avoiding extra settings dependencies."""
from __future__ import annotations

import os

try:
    from dotenv import load_dotenv
    from pathlib import Path
    env_path = Path(__file__).resolve().parent.parent / ".env"
    print("__file__       =", __file__)
    print("env_path       =", env_path)
    print("exists         =", env_path.exists())
    print("is_file        =", env_path.is_file())
    load_dotenv(dotenv_path=env_path, override=False)
except ImportError:
    # Environment variables may still be exported by the shell.
    pass


def llm_api_key() -> str | None:
    return os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")


def llm_base_url() -> str | None:
    # For providers exposing an OpenAI-compatible Chat Completions API.
    return os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL")


def llm_model() -> str:
    return os.getenv("LLM_MODEL", "gpt-4o-mini")
