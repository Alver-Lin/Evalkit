"""Simple mock provider for offline EvalKit demos."""

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
