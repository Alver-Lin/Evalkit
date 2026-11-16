from __future__ import annotations

from pathlib import Path

from app.services.store import config_store

SAMPLES_DIR = Path(__file__).resolve().parents[3] / "samples"

OPENAI_YAML = """# yaml-language-server: $schema=https://promptfoo.dev/config-schema.json
description: OpenAI sample — set OPENAI_API_KEY before running

prompts:
  - 'Answer briefly: {{question}}'

providers:
  - id: openai:gpt-4o-mini
    label: gpt-4o-mini

tests:
  - vars:
      question: What is the capital of France?
    assert:
      - type: icontains
        value: Paris
  - vars:
      question: What is 2 + 2?
    assert:
      - type: icontains
        value: '4'
  - vars:
      question: Name a primary color.
    assert:
      - type: icontains-any
        value: [red, blue, yellow]
"""


def ensure_sample_configs() -> None:
    existing = {c.name: c for c in config_store.list()}

    if "OpenAI Sample" not in existing:
        config_store.create(
            name="OpenAI Sample",
            description="Requires OPENAI_API_KEY in the environment.",
            yaml_content=OPENAI_YAML.strip() + "\n",
        )

    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    (SAMPLES_DIR / "openai-sample.yaml").write_text(OPENAI_YAML.strip() + "\n", encoding="utf-8")
