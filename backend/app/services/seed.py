from __future__ import annotations

from pathlib import Path

from app.services.store import config_store

SAMPLES_DIR = Path(__file__).resolve().parents[3] / "samples"

DEMO_YAML = """# yaml-language-server: $schema=https://promptfoo.dev/config-schema.json
description: EvalKit demo — mock provider (no API key required)

prompts:
  - 'Translate to {{language}}: {{text}}'

providers:
  - id: python:mock_provider.py
    label: mock-translator

tests:
  - vars:
      language: French
      text: Hello world
    assert:
      - type: icontains
        value: bonjour
  - vars:
      language: Spanish
      text: Good morning
    assert:
      - type: icontains
        value: buenos
  - vars:
      language: German
      text: Thank you
    assert:
      - type: icontains
        value: danke
"""

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

MOCK_PROVIDER = '''"""Simple mock provider for offline EvalKit demos."""

from __future__ import annotations


TRANSLATIONS = {
    ("french", "hello world"): "Bonjour le monde",
    ("spanish", "good morning"): "Buenos días",
    ("german", "thank you"): "Danke",
}


def call_api(prompt: str, options: dict, context: dict):
    vars_ = (context or {}).get("vars") or {}
    language = str(vars_.get("language", "")).strip().lower()
    text = str(vars_.get("text", "")).strip().lower()
    key = (language, text)

    if "Translate" in prompt or "translate" in prompt.lower():
        output = TRANSLATIONS.get(key, f"[{language}] {vars_.get('text', '')}")
    else:
        output = f"Summary ({language}): {vars_.get('text', '')}"

    return {"output": output}
'''


def ensure_sample_configs() -> None:
    existing = {c.name: c for c in config_store.list()}

    if "Demo Mock Eval" not in existing:
        meta = config_store.create(
            name="Demo Mock Eval",
            description="Offline demo using a Python mock provider (no API key).",
            yaml_content=DEMO_YAML.strip() + "\n",
        )
        _write_mock_provider(meta.id)
    else:
        _write_mock_provider(existing["Demo Mock Eval"].id)

    if "OpenAI Sample" not in existing:
        config_store.create(
            name="OpenAI Sample",
            description="Requires OPENAI_API_KEY in the environment.",
            yaml_content=OPENAI_YAML.strip() + "\n",
        )

    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    (SAMPLES_DIR / "demo-mock.yaml").write_text(DEMO_YAML.strip() + "\n", encoding="utf-8")
    (SAMPLES_DIR / "openai-sample.yaml").write_text(OPENAI_YAML.strip() + "\n", encoding="utf-8")
    (SAMPLES_DIR / "mock_provider.py").write_text(MOCK_PROVIDER, encoding="utf-8")


def _write_mock_provider(config_id: str) -> None:
    from app.core.config import settings

    path = settings.configs_dir / config_id / "mock_provider.py"
    path.write_text(MOCK_PROVIDER, encoding="utf-8")
