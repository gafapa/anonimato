"""Global propagation: every detected value is searched in the whole document (all text
sources: native text and OCR) together with its common variants."""
from __future__ import annotations

import unicodedata

import regex as re

from . import names_data
from .rules import PARTICLES, no_accents
from .types import PageText

ID_TYPES = {"dni", "nie", "cif", "nss", "iban", "card", "phone", "passport", "bic", "id_other", "plate"}


class NormalizedText:
    """Accent-free, case-folded copy of a text with a map back to original indices."""

    def __init__(self, text: str):
        chars, index = [], []
        for i, ch in enumerate(text):
            folded = "".join(c for c in unicodedata.normalize("NFD", ch) if unicodedata.category(c) != "Mn").casefold()
            for c in folded or " ":
                chars.append(c)
                index.append(i)
        self.text = "".join(chars)
        self.index = index

    def span(self, start: int, end: int) -> tuple[int, int]:
        return self.index[start], self.index[end - 1] + 1


def _id_pattern(value: str) -> str | None:
    core = re.sub(r"[\W_]+", "", no_accents(value).casefold())
    if len(core) < 5:
        return None
    return r"(?<![\w])" + r"[\s.\-/]?".join(re.escape(c) for c in core) + r"(?![\w])"


def _join(words: list[str]) -> str:
    return r"[\s.,'’-]+(?:(?:de|del|la|las|los|y|i)\s+)?".join(re.escape(w) for w in words)


def _words_pattern(words: list[str]) -> str:
    return r"(?<!\w)" + _join(words) + r"(?!\w)"


def variants(kind: str, value: str) -> list[tuple[str, float]]:
    """Regex patterns (on normalised text) and their confidence."""
    if kind in ID_TYPES or kind in ("email", "url", "ip"):
        pattern = _id_pattern(value)
        return [(pattern, 0.9)] if pattern else []
    words = [w for w in re.findall(r"[\w'’-]+", no_accents(value).casefold())]
    if not words:
        return []
    out = [(_words_pattern(words), 0.85)]
    if kind == "name":
        core = [w for w in words if w not in PARTICLES]
        if len(core) >= 3:
            out.append((_words_pattern(core[-2:]), 0.75))                     # both surnames
            out.append((_words_pattern([core[0], core[1]]), 0.7))             # name + first surname
            out.append((r"(?<!\w)" + re.escape(core[0][0]) + r"\.\s*" + _join(core[1:]) + r"(?!\w)", 0.75))
        if len(core) == 2:
            out.append((r"(?<!\w)" + re.escape(core[0][0]) + r"\.\s*" + re.escape(core[1]) + r"(?!\w)", 0.7))
        for surname in core[1:]:
            # A rare surname alone still points to the person.
            if len(surname) >= 5 and surname not in names_data.SURNAMES and surname not in names_data.FIRST_NAMES:
                out.append((r"(?<!\w)" + re.escape(surname) + r"(?!\w)", 0.6))
    elif kind == "address" and len(words) >= 3:
        out.append((_words_pattern(words[:3]), 0.7))
    return out


def search(source: PageText, patterns: list[tuple[str, float]]) -> list[tuple[int, int, float]]:
    norm = NormalizedText(source.text)
    found = []
    for pattern, confidence in patterns:
        for match in re.finditer(pattern, norm.text):
            if match.end() > match.start():
                start, end = norm.span(match.start(), match.end())
                found.append((start, end, confidence))
    return found
