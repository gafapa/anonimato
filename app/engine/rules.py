"""Rule-based detection of personal data in Spanish/English text.

Every match carries character offsets into the analysed text, a category, a
confidence and an optional validation warning. Identifiers with checksums are
validated; unvalidated look-alikes are kept only with supporting context.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

import regex as re

from . import names_data

CATEGORIES: dict[str, dict[str, str]] = {
    "name": {"label": "Nombres", "token": "NOMBRE"},
    "dni": {"label": "DNI / NIF", "token": "DNI"},
    "nie": {"label": "NIE", "token": "NIE"},
    "cif": {"label": "CIF", "token": "CIF"},
    "passport": {"label": "Pasaporte", "token": "PASAPORTE"},
    "nss": {"label": "N.º Seg. Social", "token": "NSS"},
    "email": {"label": "Email", "token": "EMAIL"},
    "phone": {"label": "Teléfono", "token": "TELÉFONO"},
    "url": {"label": "URL", "token": "URL"},
    "ip": {"label": "Dirección IP", "token": "IP"},
    "plate": {"label": "Matrícula", "token": "MATRÍCULA"},
    "date": {"label": "Fecha nacimiento", "token": "FECHA NACIMIENTO"},
    "address": {"label": "Dirección", "token": "DIRECCIÓN"},
    "iban": {"label": "IBAN / cuenta", "token": "IBAN"},
    "bic": {"label": "BIC / SWIFT", "token": "BIC"},
    "card": {"label": "Tarjeta bancaria", "token": "TARJETA"},
    "id_other": {"label": "Otros identificadores", "token": "ID"},
    "health": {"label": "Datos de salud", "token": "SALUD"},
    "org": {"label": "Organizaciones", "token": "ORGANIZACIÓN"},
    "other": {"label": "Otros datos personales", "token": "DATO"},
    "handwriting": {"label": "Texto manuscrito", "token": "MANUSCRITO"},
    "signature": {"label": "Firma", "token": "FIRMA"},
    "face": {"label": "Rostros", "token": "ROSTRO"},
    "manual": {"label": "Ocultación manual", "token": "MANUAL"},
}

# Categories the user can toggle before processing (the rest are always on).
SELECTABLE = [key for key in CATEGORIES if key not in ("manual",)]
DEFAULT_OFF = {"org"}


@dataclass
class Match:
    start: int
    end: int
    type: str
    value: str
    confidence: float
    prio: int = 0
    warning: str | None = None
    source: str = "rules"
    extra: dict = field(default_factory=dict)


def no_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def canonical(kind: str, value: str) -> str:
    """Key used to give the same token to different spellings of one value."""
    base = no_accents(value).casefold()
    if kind in ("name", "address", "org", "other", "health", "date"):
        return re.sub(r"[\W_]+", " ", base).strip()
    return re.sub(r"[\W_]+", "", base)


# ---------------------------------------------------------------- validators
DNI_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"


def valid_dni(value: str) -> bool:
    v = re.sub(r"[.\s-]", "", value).upper()
    return bool(re.fullmatch(r"\d{8}[A-Z]", v)) and DNI_LETTERS[int(v[:8]) % 23] == v[-1]


def valid_nie(value: str) -> bool:
    v = re.sub(r"[.\s-]", "", value).upper()
    if not re.fullmatch(r"[XYZ]\d{7}[A-Z]", v):
        return False
    number = int("XYZ".index(v[0]).__str__() + v[1:8])
    return DNI_LETTERS[number % 23] == v[-1]


def valid_cif(value: str) -> bool:
    v = re.sub(r"[.\s-]", "", value).upper()
    if not re.fullmatch(r"[ABCDEFGHJNPQRSUVW]\d{7}[0-9A-J]", v):
        return False
    digits = v[1:8]
    even = sum(int(d) for d in digits[1::2])
    odd = sum(sum(divmod(int(d) * 2, 10)) for d in digits[0::2])
    control = (10 - (even + odd) % 10) % 10
    letter = "JABCDEFGHI"[control]
    if v[0] in "PQRSNW":
        return v[-1] == letter
    if v[0] in "ABEH":
        return v[-1] == str(control)
    return v[-1] in (str(control), letter)


IBAN_LENGTHS = {
    "ES": 24, "PT": 25, "FR": 27, "DE": 22, "IT": 27, "GB": 22, "IE": 22, "NL": 18, "BE": 16,
    "AD": 24, "CH": 21, "AT": 20, "LU": 20, "PL": 28, "SE": 24, "DK": 18, "FI": 18, "NO": 15,
    "GR": 27, "RO": 24, "CZ": 24, "SK": 24, "HU": 28, "BG": 22, "HR": 21, "SI": 19, "EE": 20,
    "LV": 21, "LT": 20, "MT": 31, "CY": 28, "GI": 23, "MC": 27, "SM": 27, "LI": 21, "IS": 26,
}


def valid_iban(value: str) -> bool:
    v = re.sub(r"[\s-]", "", value).upper()
    if len(v) < 15 or IBAN_LENGTHS.get(v[:2]) not in (None, len(v)):
        return False
    if v[:2] not in IBAN_LENGTHS:
        return False
    rearranged = v[4:] + v[:4]
    numeric = "".join(str(int(c, 36)) for c in rearranged)
    return int(numeric) % 97 == 1


def valid_ccc(value: str) -> bool:
    v = re.sub(r"[\s-]", "", value)
    if not re.fullmatch(r"\d{20}", v):
        return False
    weights = [1, 2, 4, 8, 5, 10, 9, 7, 3, 6]

    def dc(digits: str) -> int:
        total = sum(int(d) * w for d, w in zip(digits.rjust(10, "0"), weights))
        r = 11 - total % 11
        return 0 if r == 11 else 1 if r == 10 else r

    return int(v[8]) == dc("00" + v[:8]) and int(v[9]) == dc(v[10:])


def valid_card(value: str) -> bool:
    digits = re.sub(r"[\s-]", "", value)
    if not re.fullmatch(r"\d{13,19}", digits) or re.fullmatch(r"(\d)\1+", digits):
        return False
    total, double = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if double:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
        double = not double
    return total % 10 == 0


def valid_nss(value: str) -> bool:
    v = re.sub(r"[\s/.-]", "", value)
    if not re.fullmatch(r"\d{12}", v):
        return False
    province, middle, control = int(v[:2]), int(v[2:10]), int(v[10:])
    number = province * 10_000_000 + middle if middle < 10_000_000 else int(v[:10])
    return number % 97 == control


def valid_ip(value: str) -> bool:
    if ":" in value:
        return value.count(":") >= 2
    parts = value.split(".")
    return len(parts) == 4 and all(p.isdigit() and int(p) <= 255 and (p == "0" or not p.startswith("0")) for p in parts)


def context_before(text: str, start: int, pattern: re.Pattern, reach: int = 40) -> bool:
    return bool(pattern.search(text[max(0, start - reach):start]))


# ---------------------------------------------------------------- base rules
NSS_CTX = re.compile(r"(?i)seg(?:uridad|\.)?\s*soc|\bnss\b|\bnaf\b|afiliaci|n\.?\s*º?\s*s\.?\s*s\.?\b")
PLATE_CTX = re.compile(r"(?i)matr[ií]cula|veh[ií]culo|coche|turismo|motocicleta|placa")
PASSPORT_CTX = re.compile(r"(?i)pasaporte|passport|n\.?º?\s*pas\b")
BIC_CTX = re.compile(r"(?i)\bbic\b|swift")
CARD_CTX = re.compile(r"(?i)tarjeta|card|visa|mastercard|amex|cr[eé]dito|d[eé]bito")

# Separator inside long numbers: space or dash, or a line break (numbers wrap in paragraphs).
WRAP_SEP = r"(?:[ -]|[ \t]*\n[ \t]*)"

RULES: list[dict] = [
    {"type": "email", "prio": 1000, "conf": 0.99,
     "re": re.compile(r"(?i)(?<![\w.%+-])[\w.%+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Z]{2,}\b")},
    {"type": "url", "prio": 950, "conf": 0.9,
     "re": re.compile(r"(?i)\b(?:https?://|www\.)[^\s<>\"']+[^\s<>\"'.,;:)]")},
    {"type": "iban", "prio": 930, "conf": 0.99, "validate": valid_iban,
     "re": re.compile(r"\b[A-Z]{2}\d{2}(?:" + WRAP_SEP + r"?[A-Z0-9]{2,4}){3,8}\b")},
    {"type": "iban", "prio": 925, "conf": 0.97, "validate": valid_ccc,
     "re": re.compile(r"(?<![\d-])\d{4}" + WRAP_SEP + r"?\d{4}" + WRAP_SEP + r"?\d{2}" + WRAP_SEP + r"?\d{10}(?![\d-])")},
    {"type": "card", "prio": 920, "conf": 0.98, "validate": valid_card,
     "re": re.compile(r"(?<![\d-])(?:\d" + WRAP_SEP + r"?){12,18}\d(?![\d-])")},
    {"type": "nss", "prio": 910, "conf": 0.97, "validate": valid_nss, "keep_invalid_ctx": NSS_CTX, "invalid_conf": 0.6,
     "re": re.compile(r"(?<![\d/-])\d{2}[ /-]?\d{8}[ /-]?\d{2}(?![\d/-])")},
    {"type": "phone", "prio": 900, "conf": 0.93,
     "re": re.compile(r"(?<![\w+/-])(?:(?:\+|00)\s?34[\s.-]?|\(\s?(?:\+|00)?34\s?\)\s?)?[6789](?:[\s.-]?\d){8}(?![\d-])")},
    {"type": "phone", "prio": 905, "conf": 0.85, "group": 1,
     "re": re.compile(r"(?i)(?:tel[eé]fono|tel[fé]?\.?|tlf\.?|tfno\.?|m[oó]vil|phone|mobile|fax|contacto)\s*:?\s*"
                      r"((?:\+|00)\d{1,3}[\s.()-]*\d(?:[\s.()-]?\d){5,13})")},
    {"type": "nie", "prio": 880, "conf": 1.0, "validate": valid_nie, "keep_invalid": True, "invalid_conf": 0.62,
     "re": re.compile(r"(?i)\b[XYZ][.\s-]?\d[.\s]?\d{3}[.\s]?\d{3}[\s-]?[A-Z]\b")},
    {"type": "dni", "prio": 870, "conf": 1.0, "validate": valid_dni, "keep_invalid": True, "invalid_conf": 0.62,
     "re": re.compile(r"(?i)(?<![\d\w])\d{1,2}[.\s]?\d{3}[.\s]?\d{3}[\s-]?[A-Z](?![A-Z0-9])")},
    {"type": "cif", "prio": 860, "conf": 0.95, "validate": valid_cif, "keep_invalid": True, "invalid_conf": 0.6,
     "re": re.compile(r"\b[ABCDEFGHJNPQRSUVW][.\s-]?\d{2}[.\s]?\d{3}[.\s]?\d{2}[.\s-]?[0-9A-J]\b")},
    {"type": "passport", "prio": 850, "conf": 0.85, "ctx": PASSPORT_CTX, "ctx_reach": 50,
     "re": re.compile(r"\b(?:[A-Z]{3}\d{6}|[A-Z]{2}\d{7}|[A-Z]\d{8}|\d{9}[A-Z]?)\b")},
    {"type": "bic", "prio": 845, "conf": 0.9, "ctx": BIC_CTX, "ctx_reach": 30,
     "re": re.compile(r"\b[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}(?:[A-Z0-9]{3})?\b")},
    {"type": "ip", "prio": 840, "conf": 0.9, "validate": valid_ip,
     "re": re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])|\b(?:[0-9a-fA-F]{1,4}:){3,7}[0-9a-fA-F]{1,4}\b")},
    {"type": "plate", "prio": 800, "conf": 0.95,
     "re": re.compile(r"\b\d{4}[\s.-]?[BCDFGHJKLMNPRSTVWXYZ]{3}\b")},
    {"type": "plate", "prio": 795, "conf": 0.8, "ctx": PLATE_CTX, "ctx_reach": 60,
     "re": re.compile(r"\b[A-Z]{1,2}[\s-]?\d{4}[\s-]?[A-Z]{1,2}\b")},
]

ID_CONTEXT_RULES = [
    (re.compile(r"(?i)(?:n\.?\s*[º°o]?\.?\s*(?:de\s+)?colegiad[oa]|colegiad[oa]\s+n\.?\s*[º°o]?)\s*:?\s*([A-Z]{0,3}[-/]?\d{3,}[-/]?\d*)"), 0.9),
    (re.compile(r"(?i)(?:\bNHC\b|historia\s+cl[ií]nica|n\.?\s*[º°]?\s*H\.?\s*C\.?)\s*:?\s*(?:n\.?\s*[º°]\s*)?([A-Z0-9][A-Z0-9/-]{3,})"), 0.9),
    (re.compile(r"(?i)(?:\bCIP\b|tarjeta\s+sanitaria|TSI)\s*:?\s*([A-Z0-9]{8,20})"), 0.9),
    (re.compile(r"(?i)(?:n\.?\s*[º°]?\s*(?:de\s+)?(?:expediente|exp\.)|expediente\s+n\.?\s*[º°]?)\s*:?\s*([A-Z0-9][A-Z0-9/.-]{3,})"), 0.6),
    (re.compile(r"(?i)(?:n\.?\s*[º°]?\s*(?:de\s+)?(?:socio|cliente|p[oó]liza|afiliado|empleado|matr[ií]cula\s+escolar))\s*:?\s*([A-Z0-9][A-Z0-9/.-]{3,})"), 0.7),
]

# ---------------------------------------------------------------- dates
MONTHS = r"(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|sep?tiembre|octubre|noviembre|diciembre|ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic|january|february|march|april|june|july|august|september|october|november|december)"
DATE_RE = re.compile(
    r"(?i)\b(?:\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|\d{4}-\d{2}-\d{2}|\d{1,2}\s+de\s+" + MONTHS + r"\s+(?:de\s+|del\s+)?\d{2,4}"
    r"|\d{1,2}[-\s]" + MONTHS + r"\.?[-\s]\d{2,4}|" + MONTHS + r"\s+\d{1,2},?\s+\d{4})\b")
BIRTH_CTX = re.compile(r"(?i)nacid|\bnaci\b|nacimien|\bf\.?\s*(?:de\s+)?nac\b|fecha\s+de\s+nac|\bd\.?\s*o\.?\s*b\b|born|birth|data\s+de\s+nac|\bedad\b|\bnac\.")


def find_dates(text: str) -> list[Match]:
    out = []
    for m in DATE_RE.finditer(text):
        window = text[max(0, m.start() - 80):m.start()] + " " + text[m.end():m.end() + 30]
        if BIRTH_CTX.search(window):
            out.append(Match(m.start(), m.end(), "date", m.group(), 0.9, prio=700))
    return out


# ---------------------------------------------------------------- addresses
STREET_WORDS = (
    r"calle|avenida|plaza|paseo|camino|carretera|praza|r[úu]a|pol[ií]gono|urbanizaci[óo]n|barrio|"
    r"callej[óo]n|pasaje|glorieta|traves[ií]a|cami[ñn]o|ronda|rambla|carrer|passeig|pla[çc]a|avinguda|"
    r"kalea|etorbidea|lugar|parroquia|aldea|v[ií]a|cuesta|costanilla|bulevar|urbanizaci[oó]n|edificio|"
    r"residencial|partida|finca|diseminado|apartado\s+de\s+correos"
)
STREET_ABBR = (
    r"c/|c\.|cl\.|cl|avda\.?|av\.|avd\.|avda|pza\.?|pl\.|plza\.?|p[ºo]\.|ps\.|ctra\.?|crta\.?|cmno\.?|"
    r"urb\.|pol\.|polg\.|p\.\s?i\.|bº|b[ºo]\.|rda\.|gta\.|trav\.|trva\.|pje\.|r/|rúa|c\\"
)
# Abbreviations ending in "." or "/" may touch the name ("C/Mayor"); the others need a space ("Cl Mayor").
ADDRESS_ANCHOR = re.compile(r"(?i)(?<![\p{L}])(?:" + STREET_WORDS + r")\b|(?<![\p{L}])(?:" + STREET_ABBR
                            + r")(?:(?<=[./\º])\s*|\s+)(?=[\p{Lu}\d])")
ADDRESS_FIELD = re.compile(r"(?i)\b(?:direcci[óo]n(?:\s+postal)?|domicilio(?:\s+(?:social|fiscal|a\s+efectos\s+de\s+notificaci[óo]n))?|"
                           r"reside\s+en|residente\s+en|con\s+domicilio\s+en|vive\s+en|sito\s+en|sita\s+en|address|enderezo|helbidea)\s*:?\s+")
ADDR_TOKEN = re.compile(r"[\p{L}\d][\p{L}'’.\-\d/º°ª]*")
ADDR_EXTRA = {"bajo", "bajos", "izq", "izda", "izqda", "dcha", "dch", "der", "dcho", "esc", "escalera", "puerta", "pta",
              "piso", "portal", "bloque", "blq", "nº", "n", "num", "número", "numero", "s/n", "sn", "km", "local",
              "planta", "pl", "atico", "ático", "entresuelo", "principal", "ppal", "casa", "apto", "apartamento",
              "cp", "c.p", "c.p.", "letra", "centro", "interior", "exterior", "ext", "int"}
PARTICLES = {"de", "del", "la", "las", "los", "el", "y", "e", "u", "da", "do", "das", "dos", "d'", "l'", "i"}
POSTCODE = re.compile(r"^(?:0[1-9]|[1-4]\d|5[0-2])\d{3}$")


def _skip(text: str, pos: int, stop_nl: bool = False) -> int:
    while pos < len(text):
        ch = text[pos]
        if ch.isspace():
            if stop_nl and ch in "\r\n":
                break
            pos += 1
        elif ch in ".,;:()\"'»«¡!¿?+–—|[]{}-":
            pos += 1
        else:
            break
    return pos


def _capture_address(text: str, start: int, from_pos: int, abbreviated: bool) -> Match | None:
    pos = _skip(text, from_pos, True)
    end = pos
    tokens: list[str] = []
    upper = digits = 0
    limit = min(len(text), from_pos + 130)
    wrapped = False
    while pos < limit:
        if text[pos] in "\r\n":
            # An address may continue on the next line after a comma, or with a postcode / floor.
            following = ADDR_TOKEN.match(text, _skip(text, pos))
            continues = text[max(0, pos - 4):pos].rstrip().endswith(",") or (
                following is not None and re.match(r"(?i)^(?:\d{5}|\d+[ºª°]|bajo|piso|puerta|esc)", following.group()))
            if wrapped or not tokens or not continues:
                break
            wrapped = True
            pos = _skip(text, pos)
            continue
        m = ADDR_TOKEN.match(text, pos)
        if not m:
            break
        tok = m.group()
        low = no_accents(tok.lower()).rstrip(".")
        if tok[0].isupper() or tok[0].isdigit() or low in ADDR_EXTRA or re.match(r"^\d+[ºª°]?[A-Za-z]?$", tok):
            tokens.append(tok)
            upper += tok[0].isupper()
            digits += tok[0].isdigit()
            end = m.end()
            gap = text[m.end():_skip(text, m.end(), True)]
            sentence_end = (tok.endswith(".") and len(low) > 4) or any(c in gap for c in ".;")
            if digits and sentence_end:
                break  # "…, 33003 Oviedo. Otro texto": the address ends with the sentence
        elif low in PARTICLES:
            pass
        else:
            break
        pos = _skip(text, m.end(), True)
    while tokens and no_accents(tokens[-1].lower()).rstrip(".") in PARTICLES:
        tokens.pop()
    if not tokens or upper == 0:
        return None
    if abbreviated and len(tokens) < 2 and digits == 0:
        return None
    if len(tokens) < 2 and digits == 0:
        return None
    while end > start and text[end - 1] in ".,;:":
        end -= 1
    return Match(start, end, "address", text[start:end], 0.8 if not abbreviated else 0.78, prio=600)


def find_addresses(text: str) -> list[Match]:
    out = []
    for m in ADDRESS_ANCHOR.finditer(text):
        abbreviated = not re.fullmatch("(?i)" + STREET_WORDS, m.group())
        found = _capture_address(text, m.start(), m.end(), abbreviated)
        if found:
            out.append(found)
    for m in ADDRESS_FIELD.finditer(text):
        begin = _skip(text, m.end(), True)
        found = _capture_address(text, begin, begin, False)
        if found:
            found.confidence = 0.82
            out.append(found)
    return out


# ---------------------------------------------------------------- names
NAME_STOPS = {no_accents(w) for w in (
    "director directora gerente jefe jefa presidente presidenta secretario secretaria administrativo administrativa "
    "tecnico tecnica responsable delegado delegada titular cliente representante administracion ventas personal "
    "operaciones contabilidad departamento area unidad servicio centro division coordinador coordinadora coordinacion "
    "municipio provincia localidad ciudad poblacion empresa sociedad corporacion general operador analista asesor "
    "asesora abogado abogada medico medica enfermero enfermera maestro maestra profesor profesora investigador "
    "investigadora estudiante alumno alumna becario becaria practicante consultor consultora ingeniero ingeniera "
    "arquitecto arquitecta adjunto adjunta auxiliar dni nif nie cif nss telefono correo email matricula fecha "
    "direccion domicilio iban cuenta calle avenida plaza juzgado tribunal ayuntamiento concello consejeria "
    "conselleria ministerio universidad colegio instituto hospital banco seguridad social agencia tributaria "
    "sr sra don dona doña firma firmado fdo nombre apellidos apellido expediente referencia asunto "
    "estimado estimada estimados querido querida señor señora señores usuario usuaria cliente clientes atentamente "
    "saludos cordiales distinguido distinguida interesado interesada destinatario remitente "
    "lunes martes miercoles jueves viernes sabado domingo enero febrero marzo abril mayo junio julio agosto "
    "septiembre octubre noviembre diciembre madrid barcelona"
).split()}

NAME_TOKEN = re.compile(r"[\p{L}][\p{L}'’\-‐]*\.?")


def is_known_name(token: str) -> bool:
    key = no_accents(token.lower()).replace("'", "").replace("’", "").rstrip(".")
    return key in names_data.FIRST_NAMES or key in names_data.SURNAMES


def _is_upper_start(tok: str) -> bool:
    return tok[:1].isupper()


def _all_caps(tok: str) -> bool:
    letters = [c for c in tok if c.isalpha()]
    return len(letters) >= 3 and all(c.isupper() for c in letters)


def capture_name_run(text: str, from_pos: int, allow_unknown: bool = False, allow_all_caps: bool = False,
                     stop_at_conjunction: bool = False) -> tuple[int, int, str] | None:
    pos = _skip(text, from_pos)
    start = end = pos
    toks: list[str] = []
    limit = min(len(text), from_pos + 140)
    pending_break = False
    while pos < limit and len(toks) < 6:
        m = NAME_TOKEN.match(text, pos)
        if not m:
            break
        tok = m.group().rstrip(".") if not re.fullmatch(r"\p{Lu}\.", m.group()) else m.group()
        tok_end = m.start() + len(tok)
        low = no_accents(tok.lower()).replace("'", "").replace("’", "").rstrip(".")
        if not _is_upper_start(tok):
            if low in PARTICLES:
                if stop_at_conjunction and len(toks) >= 2 and low in ("y", "e", "u", "i"):
                    break
                pos = _skip(text, tok_end)
                continue
            break
        if low in PARTICLES:
            pos = _skip(text, tok_end)
            continue
        if low in NAME_STOPS:
            break
        if _all_caps(tok) and not allow_all_caps:
            break
        if pending_break and not is_known_name(tok) and (not allow_unknown or len(toks) >= 2):
            break  # a name only continues on the next line with a known name (or a single wrapped word)
        if not toks:
            start = m.start()
        toks.append(tok)
        end = tok_end
        nxt = _skip(text, tok_end)
        pending_break = "\n" in text[tok_end:nxt]
        pos = nxt
    if not toks:
        return None
    surnames_after = sum(1 for t in toks[1:] if no_accents(t.lower()).rstrip(".") in names_data.SURNAMES)
    rare_given_name = len(toks) >= 3 and surnames_after >= 2
    if not is_known_name(toks[0]) and (not allow_unknown or len(toks) < 2) and not rare_given_name:
        return None
    return start, end, " ".join(toks)


TITLE_RE = re.compile(
    r"(?i)\b(?:sr\.?|sra\.?|srta\.?|srs\.?|sras\.?|d\.|dª|dña\.?|don|doña|dr\.?|dra\.?|prof\.?|profª|profa\.?|ing\.?|lic\.?|"
    r"licda\.?|mtro\.?|mtra\.?|excmo\.?|excma\.?|ilmo\.?|ilma\.?|hno\.?|hna\.?|doctor|doctora|mr\.?|mrs\.?|ms\.?|"
    r"letrad[oa]|procurador[a]?|notari[oa])\s+")
LABEL_RE = re.compile(
    r"(?i)\b(?:apellidos\s+y\s+nombre|nombre\s+y\s+apellidos?|nombre\s+completo|nombre\s+del\s+(?:titular|paciente|alumn[oa]|"
    r"solicitante|interesad[oa]|trabajador[a]?|menor|padre|madre|tutor[a]?|cónyuge|conyuge)|nombres?|apellidos?|primer\s+apellido|"
    r"segundo\s+apellido|titular(?:es)?|cliente|propietari[oa]|paciente|beneficiari[oa]|solicitante|firmante|fdo\.?|firmad[oa]|"
    r"firma(?=\s*:)|interesad[oa]|compareciente|representante|padre|madre|tutor(?:a)?|estudiante|alumn[oa]|trabajador[a]?|"
    r"empleado|demandante|demandad[oa]|denunciante|denunciad[oa]|testigo|herederos?|causante|c[óo]nyuge|esposo|esposa|hij[oa]|"
    r"arrendador[a]?|arrendatari[oa]|comprador[a]?|vendedor[a]?|contacto|atenci[óo]n|a/a|att\.?|name|full\s+name|surname|"
    r"el\s+que\s+suscribe|la\s+que\s+suscribe|abajo\s+firmante|nome|nom|izena)\s*:?\s+")
CONTEXT_RE = re.compile(
    r"(?i)\b(?:el\s+abajo\s+firmante|la\s+abajo\s+firmante|abajo\s+firmante|compareciente|el\s+que\s+suscribe|"
    r"la\s+persona\s+f[ií]sica|representante\s+legal|adjudicatari[oa]|a\s+favor\s+de|en\s+nombre\s+de|"
    r"comparece|comparecen|expone|solicita\s+que)(?:\b[^\n]{0,25}?)?")


def find_names(text: str) -> list[Match]:
    out = []
    anchors = []
    for m in TITLE_RE.finditer(text):
        anchors.append((m.end(), True, True, 0.85))
    for m in LABEL_RE.finditer(text):
        anchors.append((m.end(), True, True, 0.82))
    for m in CONTEXT_RE.finditer(text):
        anchors.append((m.end(), False, False, 0.74))
    for pos, unknown, caps, conf in anchors:
        found = capture_name_run(text, pos, allow_unknown=unknown, allow_all_caps=caps)
        if found:
            out.append(Match(found[0], found[1], "name", found[2], conf, prio=500))
    token = re.compile(r"\b\p{Lu}[\p{L}'’\-‐]+")
    pos = 0
    while (m := token.search(text, pos)):
        pos = m.end()
        if not is_known_name(m.group()):
            continue
        found = capture_name_run(text, m.start(), stop_at_conjunction=True,
                                 allow_all_caps=_all_caps(m.group()))
        if not found:
            continue
        known = [t for t in found[2].split() if is_known_name(t)]
        # A rare given name right before two known surnames ("… y Jaione Varela Castro").
        before = re.search(r"(\p{Lu}[\p{Ll}'’-]{2,})[ \t]+$", text[max(0, found[0] - 30):found[0]])
        if before and len(known) >= 2 and not any(no_accents(t.lower()) in names_data.FIRST_NAMES for t in known):
            word = before.group(1)
            preceding = text[max(0, found[0] - 30):found[0]][:before.start(1)].rstrip()
            if no_accents(word.lower()) not in NAME_STOPS and preceding and preceding[-1] not in ".:;!?\n":
                found = (found[0] - len(before.group(0)), found[1], word + " " + found[2])
                known = [word] + known
        if len(known) >= 2 and any(no_accents(t.lower()) in names_data.FIRST_NAMES for t in known) or len(known) >= 3:
            out.append(Match(found[0], found[1], "name", found[2], 0.7, prio=450))
            pos = max(pos, found[1])
    return out


def find_contextual_ids(text: str) -> list[Match]:
    out = []
    for pattern, conf in ID_CONTEXT_RULES:
        for m in pattern.finditer(text):
            out.append(Match(m.start(1), m.end(1), "id_other", m.group(1), conf, prio=820))
    return out


def detect_all(text: str, categories: set[str] | None = None) -> list[Match]:
    cands: list[Match] = []
    for rule in RULES:
        for m in rule["re"].finditer(text):
            group = rule.get("group", 0)
            start, end, value = m.start(group), m.end(group), m.group(group)
            if "ctx" in rule and not context_before(text, start, rule["ctx"], rule.get("ctx_reach", 40)):
                continue
            validate = rule.get("validate")
            valid = validate(value) if validate else True
            if not valid:
                ctx = rule.get("keep_invalid_ctx")
                if not (rule.get("keep_invalid") or (ctx and context_before(text, start, ctx, 50))):
                    continue
            cands.append(Match(start, end, rule["type"], value,
                               rule["conf"] if valid else rule["invalid_conf"], prio=rule["prio"],
                               warning=None if valid else "checksum"))
    cands += find_contextual_ids(text)
    cands += find_dates(text)
    cands += find_addresses(text)
    cands += find_names(text)
    if categories is not None:
        cands = [c for c in cands if c.type in categories]
    return resolve_overlaps(cands)


def resolve_overlaps(cands: list[Match]) -> list[Match]:
    cands = sorted(cands, key=lambda c: (-c.prio, c.start, -(c.end - c.start)))
    kept: list[Match] = []
    for c in cands:
        if c.end <= c.start:
            continue
        if any(c.start < k.end and c.end > k.start for k in kept):
            continue
        kept.append(c)
    return sorted(kept, key=lambda c: c.start)
