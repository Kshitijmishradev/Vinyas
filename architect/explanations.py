from __future__ import annotations

import os
from typing import Any


def explain_finding(finding: dict[str, Any]) -> tuple[str, bool]:
    deterministic = (
        f"{finding['message']} Evidence: {finding.get('evidence') or 'repository-level rule'}. "
        "Review the referenced dependency and either correct it or add a documented, time-bounded suppression."
    )
    if os.environ.get("ARCHITECT_OLLAMA_ENABLED", "false").lower() != "true":
        return deterministic, False
    try:
        import requests

        response = requests.post(
            os.environ.get("ARCHITECT_OLLAMA_URL", "http://127.0.0.1:11434/api/generate"),
            json={
                "model": os.environ.get("ARCHITECT_OLLAMA_MODEL", "qwen2.5-coder:7b"),
                "stream": False,
                "prompt": (
                    "Explain this verified architecture finding in 2-3 concise sentences. Do not invent facts.\n"
                    f"Rule: {finding['rule']}\nLocation: {finding.get('path')}:{finding.get('line')}\n"
                    f"Finding: {finding['message']}\nEvidence: {finding.get('evidence') or 'n/a'}"
                ),
                "options": {"temperature": 0.1, "num_predict": 140},
            },
            timeout=15,
        )
        response.raise_for_status()
        explanation = str(response.json().get("response", "")).strip()
        if explanation:
            return explanation, True
    except Exception:
        pass
    return deterministic, False
