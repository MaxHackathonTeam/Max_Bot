"""Промпты из app/llm/prompts/*.md: версия в первой строке, секции «## system» и «## user».

Подстановка — string.Template ($name): фигурные скобки в пользовательском тексте безопасны.
"""

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from string import Template

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
_VERSION = re.compile(r"<!--\s*version:\s*([\w.-]+)\s*-->")
_SECTION = re.compile(r"^## (system|user)\s*$", re.M)


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    system: str
    user: str

    def messages(self, **variables: object) -> list[dict[str, str]]:
        values = {k: "—" if v is None or v == "" else str(v) for k, v in variables.items()}
        return [
            {"role": "system", "content": Template(self.system).safe_substitute(values)},
            {"role": "user", "content": Template(self.user).safe_substitute(values)},
        ]


@cache
def load_prompt(name: str) -> Prompt:
    raw = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
    version = _VERSION.search(raw)
    if version is None:
        raise ValueError(f"В промпте {name} нет версии")
    parts = _SECTION.split(raw)
    sections = dict(zip(parts[1::2], (p.strip() for p in parts[2::2]), strict=True))
    return Prompt(name, version.group(1), sections["system"], sections["user"])
