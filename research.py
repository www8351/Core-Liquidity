"""Load written strategy notes (.md/.txt) from the Research/ folder so they can
be fed to the AI as ground-truth context. Images are handled separately by the
caller (base64 vision blocks); this module only concatenates text."""
from __future__ import annotations

import os
import logging

logger = logging.getLogger(__name__)

TEXT_EXTS = (".md", ".txt")
DEFAULT_MAX_CHARS = 40_000


def load_research_notes(research_path: str = "./Research",
                        max_chars: int = DEFAULT_MAX_CHARS) -> str:
    """Concatenate all .md/.txt files under `research_path`, each preceded by a
    header line. Returns "" when the folder is missing or has no text files.
    Output is capped at `max_chars` (a truncation marker is appended if cut)."""
    if not os.path.isdir(research_path):
        return ""

    parts: list[str] = []
    for name in sorted(os.listdir(research_path)):
        if name.lower().endswith(TEXT_EXTS):
            path = os.path.join(research_path, name)
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except OSError as e:
                logger.warning("Could not read research note %s: %s", name, e)
                continue
            logger.info("📄 Reading research note: %s", name)
            parts.append(f"\n\n===== {name} =====\n{content}")

    notes = "".join(parts)
    if len(notes) > max_chars:
        notes = notes[:max_chars] + "\n…[truncated]"
        logger.info("Research notes truncated to %d chars", max_chars)
    return notes
