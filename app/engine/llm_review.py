"""Second, contextual pass with the local language model.

The model sees the page text with already-detected data replaced by tokens and
returns literal fragments that still identify a person (indirect identifiers,
health data, relatives, job + place...). A fragment is accepted only if it
appears literally in the page text, so the model cannot invent data.
"""
from __future__ import annotations

import json

import regex as re

from .llm_server import LlamaServer
from .rules import Match, no_accents

TYPES = {"nombre": "name", "direccion": "address", "dirección": "address", "telefono": "phone",
         "teléfono": "phone", "email": "email", "documento": "id_other", "salud": "health",
         "fecha": "date", "otro": "other", "organizacion": "org", "organización": "org"}

PROMPT = """Eres un revisor de anonimización de documentos (RGPD). En el texto siguiente, los datos ya ocultados aparecen como [TIPO n].
Enumera los fragmentos LITERALES que todavía permitan identificar a una persona física concreta o revelen datos sensibles suyos:
nombres o apodos, direcciones, teléfonos, correos, números de documento o de expediente personal, fechas de nacimiento,
parentescos con personas identificables, cargos o puestos únicos junto a un lugar, datos de salud, religión, ideología, afiliación sindical,
orientación sexual, datos de menores.
No incluyas los [TIPO n] ni texto genérico. Copia cada fragmento exactamente como aparece, lo más corto posible.
Responde SOLO con JSON: {"datos": [{"texto": "...", "tipo": "nombre|direccion|telefono|email|documento|salud|fecha|organizacion|otro"}]}
Si no queda nada, responde {"datos": []}.

TEXTO:
"""


def mask_known(text: str, spans: list[tuple[int, int, str]]) -> str:
    out, last = [], 0
    for start, end, label in sorted(spans):
        if start < last:
            continue
        out.append(text[last:start])
        out.append(f"[{label}]")
        last = end
    out.append(text[last:])
    return "".join(out)


def _loose(fragment: str) -> re.Pattern:
    parts = [re.escape(p) for p in fragment.split()]
    return re.compile(r"(?i)" + r"\s+".join(parts))


def review(server: LlamaServer, text: str, known: list[tuple[int, int, str]], chunk: int = 3500) -> list[Match]:
    found: list[Match] = []
    masked = mask_known(text, known)
    for offset in range(0, len(masked), chunk):
        piece = masked[offset:offset + chunk]
        if len(piece.strip()) < 20:
            continue
        try:
            answer = server.chat([{"role": "user", "content": PROMPT + piece}], max_tokens=700, json_mode=True)
            items = json.loads(answer).get("datos", [])
        except Exception:  # a failed review never blocks; verification still runs
            continue
        for item in items if isinstance(items, list) else []:
            fragment = str(item.get("texto", "")).strip() if isinstance(item, dict) else ""
            kind = TYPES.get(no_accents(str(item.get("tipo", "otro")).lower()), "other") if isinstance(item, dict) else "other"
            if len(fragment) < 3 or "[" in fragment:
                continue
            for match in _loose(fragment).finditer(text):
                if any(match.start() < e and match.end() > s for s, e, _ in known):
                    continue
                found.append(Match(match.start(), match.end(), kind, match.group(), 0.6, prio=300, source="llm"))
    return found
