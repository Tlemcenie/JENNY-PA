"""Nettoyage de texte pour la normalisation des messages."""

from __future__ import annotations

import re
from html.parser import HTMLParser

_WS_RE = re.compile(r"\s+")


class _HTMLToText(HTMLParser):
    """Extrait le texte brut d'un fragment HTML."""

    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []

    def handle_data(self, data: str) -> None:
        self._chunks.append(data)

    def get_text(self) -> str:
        return "".join(self._chunks)


def strip_html(content: str) -> str:
    """Retire les balises HTML et décode les entités simples."""
    if not content or "<" not in content:
        return content
    parser = _HTMLToText()
    try:
        parser.feed(content)
        parser.close()
        return parser.get_text()
    except Exception:
        return re.sub(r"<[^>]+>", " ", content)


def clean_message_text(raw: str) -> str:
    """Nettoie le texte : HTML, espaces, retours à la ligne."""
    if not raw:
        return ""
    text = strip_html(raw)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WS_RE.sub(" ", text)
    return text.strip()


def detect_language_safe(text: str) -> str | None:
    """Détecte la langue (ISO 639-1) si possible, sinon None."""
    sample = text[:500].strip()
    if len(sample) < 10:
        return None
    try:
        from langdetect import detect

        return detect(sample)
    except Exception:
        return None
