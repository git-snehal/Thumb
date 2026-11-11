"""Template catalogue: which layouts exist."""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path


@dataclass(frozen=True)
class TemplateSpec:
    key: str            # used in callback data and shown as "current template"
    label: str          # button text
    file: str           # Jinja template file
    variant: str = ""   # css class on <body> for theme / layout variants
    active: bool = True
    special: bool = False   # needs a character image; shown as its own full-width button


DEFAULT_TEMPLATES = [
    TemplateSpec("template1", "Template 1 (Main)", "template1.html"),
    TemplateSpec("animeposter1_v2", "Poster 1 (v2)", "template1.html", variant="dark"),
    TemplateSpec("animeposter1_v3", "Poster 1 (v3)", "template1.html", variant="mirror"),
    TemplateSpec("animeposter2", "Poster 2", "poster2.html"),
    TemplateSpec("animeposter3", "Poster 3", "poster3.html"),
    TemplateSpec("animeposter4", "Poster 4", "poster4.html"),
    TemplateSpec("animeposter5", "Poster 5", "poster5.html"),
    TemplateSpec("animeposter6", "Poster 6", "poster6.html"),
    TemplateSpec("animeposter7", "Poster 7", "poster7.html"),
    TemplateSpec("animeposter8", "Poster 8", "poster8.html"),
    TemplateSpec("animeposter9", "Poster 9", "poster9.html"),
    TemplateSpec("animeposter10", "Poster 10", "poster10.html"),
    TemplateSpec("animeposter11", "Poster 11", "poster11.html"),
    TemplateSpec("animeposter12", "Poster 12", "poster12.html"),
    TemplateSpec("animeposter13", "Poster 13", "poster13.html"),
    TemplateSpec("special", "✨ Special Design", "special.html", special=True),
]


def load_templates(overrides_file: Path | None = None) -> list[TemplateSpec]:
    """Defaults, optionally patched by templates.json, e.g. {"animeposter5": {"active": false}}."""
    specs = list(DEFAULT_TEMPLATES)
    if overrides_file and overrides_file.is_file():
        patch = json.loads(overrides_file.read_text())
        specs = [replace(s, **patch.get(s.key, {})) for s in specs]
    return [s for s in specs if s.active]
