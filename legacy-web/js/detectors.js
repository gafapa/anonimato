export const CATEGORIES = {
  name:    { label: 'Nombres',          token: 'NOMBRE' },
  dni:     { label: 'DNI / NIF',        token: 'DNI' },
  nie:     { label: 'NIE',              token: 'NIE' },
  cif:     { label: 'CIF',              token: 'CIF' },
  nss:     { label: 'N.º Seg. Social',  token: 'NSS' },
  email:   { label: 'Email',            token: 'EMAIL' },
  phone:   { label: 'Teléfono',         token: 'TELÉFONO' },
  url:     { label: 'URL',              token: 'URL' },
  plate:   { label: 'Matrícula',        token: 'MATRÍCULA' },
  date:    { label: 'Fecha nacimiento', token: 'FECHA NACIMIENTO' },
  address: { label: 'Dirección',        token: 'DIRECCIÓN' },
  iban:    { label: 'IBAN',             token: 'IBAN' },
  card:    { label: 'Tarjeta bancaria', token: 'TARJETA' },
  face:    { label: 'Rostros (imagen)', token: 'ROSTRO' },
  manual:  { label: 'Ocultación manual', token: 'MANUAL' },
};

function noAccents(s) {
  return s.normalize('NFD').replace(/[\u0300-\u036f]/g, '');
}

const PARTICLES = new Set(['de', 'del', 'la', 'las', 'los', 'el', 'y', 'e', 'u']);

const NAME_STOPS = new Set([
  'director', 'directora', 'gerente', 'jefe', 'jefa', 'presidente',
  'presidenta', 'secretario', 'secretaria', 'administrativo', 'administrativa',
  'tecnico', 'tecnica', 'tecnico/a', 'tecnica/o', 'responsable', 'delegado',
  'delegada', 'titular', 'cliente', 'representante', 'administracion',
  'ventas', 'personal', 'operaciones', 'contabilidad', 'departamento', 'area',
  'area', 'unidad', 'servicio', 'centro', 'division', 'coordinator',
  'coordinacion', 'municipio', 'provincia', 'localidad', 'ciudad', 'poblacion',
  'empresa', 'sociedad', 'corporacion', 'general', 'operador', 'analista',
  'asesor', 'asesora', 'abogado', 'abogada', 'medico', 'medica', 'enfermero',
  'enfermera', 'maestro', 'maestra', 'profesor', 'profesora', 'investigador',
  'investigadora', 'estudiante', 'alumno', 'alumna', 'becario', 'becaria',
  'practicante', 'consultor', 'consultora', 'ingeniero', 'ingeniera',
  'arquitecto', 'arquitecta', 'adjunto', 'adjunta', 'auxiliar', 'técnico',
  'técnica', 'dni', 'nif', 'nie', 'cif', 'nss', 'telefono', 'teléfono',
  'correo', 'email', 'matricula', 'matrícula', 'fecha', 'direccion', 'dirección',
  'domicilio', 'iban', 'cuenta', 's.a.', 's.l.', 's.l.u.', 's.c.', 's.coop',
]);

const NAMES_DICT = new Set(
  ('aaron abel abraham adela adrian adriana agueda agustin agustina alan alba'
  + ' albert alberto aldo alejandra alejandro alex alexandra alfonso alicia'
  + ' alonso alvaro amadeo amparo ana andrea andres angela angel anna'
  + ' antonia antonio araceli armando arturo beatriz belen benedicta benito'
  + ' berta bartolome blanca borja camila camilo candela carla carlos carmen'
  + ' carolina catalina cecilia celia cesar chema christian clara claudia'
  + ' concepcion consuelo cristian cristina damian daniel daniela david'
  + ' debora diego dimas dolores domingo doña eduardo elena elisa elias'
  + ' emilio emiliano enrique enriqueta estela esteban estela esther eugenio'
  + ' eva evaristo fabian federico felipe felix fernanda fernando florencia'
  + ' florencio flora francisco gabino gabriel gabriela gemma genaro gerardo'
  + ' german gil gloria gonzalo gracia gregorio guadalupe guillermo gustavo'
  + ' hector helena hernan humberto ignacio ines irene isabel isaac isidro'
  + ' ismael itziar jaime javier jeronimo josep joaquin joan jordi jorge jose'
  + ' josefa josefina juan juana julia julia julian julio laia laura leandro'
  + ' leonor leonardo lidia lorena lorenzo luis lucia luisa luna macarena'
  + ' manel manuel marc marta martin mateo matias mario magdalena marcos'
  + ' margarita maria marta mauricio maximo mercedes miguel miquel mireia'
  + ' miriam montserrat mónica nadia natalia natividad nestor nicanor'
  + ' nicolas nieves noa noelia norma nuria octavio oscar paloma paola'
  + ' patricia patricio pablo paco pedro pilar prudencio purificacion quim'
  + ' rafael raul ramon rebecca rebeca ricardo roberta roberto rocio'
  + ' rodrigo rosa rosario roxana ruben ruth salvador salvador samuel sandra'
  + ' santiago sara sebastian segismundo sergio silvia sofia sonia susana'
  + ' tatiana teodora teresa timoteo tomas trinidad valentin valeria vanessa'
  + ' veronica vicente victor violeta virginia waldo wenceslao xavi xabier'
  + ' xose xurxo yago zaida'
  )
    .split(/\s+/)
    .map(noAccents)
);

const SURNAMES_DICT = new Set(
  ('garcia gonzalez rodriguez fernandez lopez martinez sanchez perez gomez'
  + ' martin jimenez ruiz hernandez diaz moreno muñoz alvarez romero alonso'
  + ' gutierrez navarro torres dominguez vazquez ramos gil serrano ramirez'
  + ' molina morales ortega delgado castro ortiz marin rubio sanz iglesias'
  + ' medina garrido cortes castillo santos lozano guerrero cano prieto'
  + ' mendez contreras rivas leon marquez gallego calvo vidal blanco'
  + ' herreros parra espinoza santana campos salas robles castilla santiago'
  + ' vera meza olivera benitez carrera rios benito marco romera salvador'
  + ' gracia rodriguez bastida montes reyes cabrera silva prado feliu'
  + ' cerezo montero peña riera bosch gimenez briones saez aranda aznar'
  + ' bautista bonilla cabana casas conejero espejo galan gavilan giner'
  + ' haro lamas machado noguera ospina pacheco palacin penas pontes rangel'
  + ' roset salazar soler soto taboada vega viniegra zambrano'
  )
    .split(/\s+/)
    .map(noAccents)
);

function isKnownName(tok) {
  const key = noAccents(tok.toLowerCase()).replace(/[.'’]/g, '');
  return NAMES_DICT.has(key) || SURNAMES_DICT.has(key);
}

const TOKEN_RE = /^[\p{L}'’\-‐]+/u;
const ADDR_TOKEN_RE = /^[\p{L}'’.\-0-9º°ü]+/u;
const UPPER_START = /^[A-ZÁÉÍÓÚÜÑ]/;
const ALL_CAPS = /^[A-ZÁÉÍÓÚÜÑ]{3,}$/;

function skipSeparators(s, pos, stopAtNL = false) {
  while (pos < s.length) {
    const ch = s[pos];
    if (/\s/.test(ch)) {
      if (stopAtNL && (ch === '\n' || ch === '\r')) break;
      pos++;
      continue;
    }
    if (/[.,;:()"'»«¡!¿?+\-–—/|[\]{}]/.test(ch)) { pos++; continue; }
    break;
  }
  return pos;
}

// Capture a capitalized token sequence (a person's name) from `from`.
// Return { start, end, value } or null.
function captureNameRun(full, from, { allowUnknown = false, allowAllCaps = false, stopAtConjunction = false } = {}) {
  let pos = skipSeparators(full, from);
  let start = pos;
  let runEnd = pos;
  const toks = [];
  const maxReach = Math.min(full.length, from + 140);
  let pendingBreak = false;
  while (pos < maxReach && toks.length < 5) {
    const m = TOKEN_RE.exec(full.slice(pos));
    if (!m) break;
    const tok = m[0];
    const end = pos + tok.length;
    const low = noAccents(tok.toLowerCase().replace(/[.'’]/g, ''));
    if (!UPPER_START.test(tok)) {
      if (PARTICLES.has(low)) {
        if (stopAtConjunction && toks.length >= 2 && ['y', 'e', 'u'].includes(low)) break;
        pos = skipSeparators(full, end);
        continue;
      }
      break;
    }
    if (PARTICLES.has(low)) { pos = skipSeparators(full, end); continue; }
    if (NAME_STOPS.has(low)) break;
    if (ALL_CAPS.test(tok) && !allowAllCaps) break;
    if (pendingBreak && !allowUnknown && !isKnownName(tok)) break;
    if (toks.length === 0) start = pos;
    toks.push(tok);
    runEnd = end;
    pos = skipSeparators(full, end);
    pendingBreak = /\r?\n/.test(full.slice(end, pos));
  }
  if (!toks.length) return null;
  if (!isKnownName(toks[0]) && (!allowUnknown || toks.length < 2)) return null;
  let value = toks.join(' ');
  const trailing = /[.,;:]+$/.exec(value);
  if (trailing) {
    runEnd -= trailing[0].length;
    value = value.slice(0, -trailing[0].length);
  }
  return { start, end: runEnd, value };
}

// Detect dates only when a birth-related context is present.
const DATE_RE = new RegExp(
  '\\b(?:'
  + '\\d{1,2}[-/.]\\d{1,2}[-/.]\\d{2,4}'
  + '|\\d{1,2}\\s+de\\s+\\p{L}+\\s+de\\s+\\d{2,4}'
  + ')\\b',
  'giu'
);
const BIRTH_CTX = /(nacid|naci\b|nacimien|fecha\s+de\s+nac|d\.?\s*n\.?\s*a\.?|born|date\s+of\s+birth|data\s+de\s+nacemento|data\s+de\s+nac)/iu;

// Street-address prefixes.
const STREET_PREFIX =
  'calle|calle de|c/|c\\.|avenida|avda|av\\.|ave\\.|plaza|pl\\.|paseo|'
  + 'paseo de|camino|carretera|ctra|ctra\\.|carretera de|praza|rúa|rua|'
  + 'polígono|polg\\.|urbanización|urb\\.|barrio|callejón|pasaje|glorieta|'
  + 'travesía|camino de|camiño|camíño|ronda';
const ADDRESS_ANCHOR = new RegExp(
  '\\b(?:' + STREET_PREFIX + ')\\b[^\\n]{0,6}?',
  'giu'
);
const ADDRESS_FIELD = /\b(?:direcci[óo]n|domicilio)\s*:?\s+/giu;

const DNI_LETTERS = 'TRWAGMYFPDXBNJZSQVHLCKE';

function validDni(value) {
  const normalized = value.replace(/[.\s-]/g, '').toUpperCase();
  if (!/^\d{8}[A-Z]$/.test(normalized)) return false;
  return DNI_LETTERS[Number(normalized.slice(0, 8)) % 23] === normalized.at(-1);
}

function validNie(value) {
  const normalized = value.replace(/[.\s-]/g, '').toUpperCase();
  if (!/^[XYZ]\d{7}[A-Z]$/.test(normalized)) return false;
  const prefix = { X: '0', Y: '1', Z: '2' }[normalized[0]];
  const number = Number(prefix + normalized.slice(1, 8));
  return DNI_LETTERS[number % 23] === normalized.at(-1);
}

function validIban(value) {
  const normalized = value.replace(/\s/g, '').toUpperCase();
  if (!/^ES\d{22}$/.test(normalized)) return false;
  const rearranged = normalized.slice(4) + normalized.slice(0, 4);
  const numeric = [...rearranged].map((character) => /[A-Z]/.test(character)
    ? String(character.charCodeAt(0) - 55) : character).join('');
  let remainder = 0;
  for (const digit of numeric) remainder = (remainder * 10 + Number(digit)) % 97;
  return remainder === 1;
}

function validCard(value) {
  const digits = value.replace(/[\s-]/g, '');
  if (!/^\d{13,19}$/.test(digits) || /^(\d)\1+$/.test(digits)) return false;
  let sum = 0;
  let doubleDigit = false;
  for (let index = digits.length - 1; index >= 0; index--) {
    let digit = Number(digits[index]);
    if (doubleDigit) { digit *= 2; if (digit > 9) digit -= 9; }
    sum += digit;
    doubleDigit = !doubleDigit;
  }
  return sum % 10 === 0;
}

const BASE_RULES = [
  { type: 'email', prio: 1000, confidence: 0.99, re: /\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/giu },
  { type: 'url', prio: 950, confidence: 0.98, re: /\b(?:https?:\/\/|www\.)[^\s<>"']+/giu },
  { type: 'iban', prio: 925, confidence: 0.99, re: /\bES\d{2}(?:[\s-]?\d{4}){5}\b/giu, validate: validIban },
  { type: 'phone', prio: 900, confidence: 0.92, re: /(?<=^|[\s(:])(?:\+34[\s.)-]?\s*)?[6789]\d{2}[\s.-]?\d{3}[\s.-]?\d{3}\b/gu },
  { type: 'nie', prio: 880, confidence: 1, invalidConfidence: 0.62, re: /\b[XYZ][.\s-]?\d[.\s]?\d{3}[.\s]?\d{3}[\s-]?[A-Z]\b/giu, validate: validNie, keepInvalid: true },
  { type: 'dni', prio: 870, confidence: 1, invalidConfidence: 0.62, re: /(?<!\d)\d{1,2}[.\s]?\d{3}[.\s]?\d{3}[\s-]?[A-Z](?![A-Z0-9])/giu, validate: validDni, keepInvalid: true },
  { type: 'cif', prio: 860, confidence: 0.9, re: /\b[A-HJNPQRSUVW]\d{7}[0-9A-J]\b/gu },
  { type: 'nss', prio: 850, confidence: 0.9, re: /\b(?:\d{2}\/\d{8}\/\d{2}|(?<![0-9])\d{12}(?![0-9]))/gu },
  { type: 'card', prio: 840, confidence: 0.98, re: /(?<!\d)(?:\d[\s-]?){12,18}\d(?!\d)/gu, validate: validCard },
  { type: 'plate', prio: 800, confidence: 0.96, re: /\b\d{4}[\s.-]?[BCDFGHJKLMNPRSTVWXYZ]{3}\b/gu },
];

function findDates(full) {
  const out = [];
  let m;
  DATE_RE.lastIndex = 0;
  while ((m = DATE_RE.exec(full))) {
    const win = full.slice(Math.max(0, m.index - 120), Math.min(full.length, m.index + m[0].length + 140));
    if (BIRTH_CTX.test(win)) {
      out.push({ start: m.index, end: m.index + m[0].length, value: m[0], type: 'date', confidence: 0.9 });
    }
  }
  return out;
}

function captureAddressPhrase(full, from, anchorStart) {
  let pos = skipSeparators(full, from, true);
  const toks = [];
  let start = pos;
  let runEnd = pos;
  let alphaCount = 0;
  const maxReach = Math.min(full.length, from + 70);
  while (pos < maxReach) {
    if (full[pos] === '\n' || full[pos] === '\r') break;
    const m = ADDR_TOKEN_RE.exec(full.slice(pos));
    if (!m) break;
    const tok = m[0];
    const end = pos + tok.length;
    if (UPPER_START.test(tok) || /^\d/.test(tok) || /^[nNº°]/.test(tok)) {
      if (toks.length === 0) start = pos;
      toks.push(tok);
      if (/[A-ZÁÉÍÓÚÜÑ]/.test(tok)) alphaCount++;
      runEnd = end;
      pos = skipSeparators(full, end, true);
      continue;
    }
    const low = noAccents(tok.toLowerCase());
    if (PARTICLES.has(low)) { pos = skipSeparators(full, end, true); continue; }
    break;
  }
  if (toks.length >= 2 && alphaCount >= 1) {
    let value = toks.join(' ');
    const trailing = /[.,;:]+$/.exec(value);
    if (trailing) runEnd -= trailing[0].length;
    if (trailing) value = value.slice(0, -trailing[0].length);
    return { start: anchorStart, end: runEnd, value };
  }
  return null;
}

function findAddresses(full) {
  const out = [];
  const anchors = [];
  let m;
  ADDRESS_ANCHOR.lastIndex = 0;
  while ((m = ADDRESS_ANCHOR.exec(full))) {
    const low = noAccents(m[0].toLowerCase());
    if (!/^(c|pl|av|avda|ctra|pg|polg|urb)\.?$/.test(low.trim())) {
      anchors.push({ start: m.index, end: m.index + m[0].length });
    }
  }
  ADDRESS_FIELD.lastIndex = 0;
  while ((m = ADDRESS_FIELD.exec(full))) {
    anchors.push({ start: m.index, end: m.index + m[0].length });
  }
  for (const a of anchors) {
    const r = captureAddressPhrase(full, a.end, a.start);
    if (r) out.push({ ...r, type: 'address', confidence: 0.78 });
  }
  return out;
}

const TITLE_RE = /\b(?:sr\.?|sra\.?|srta\.?|srs\.?|sras\.?|d\.|dª|dña|don|doña|dr\.?|dra\.?|prof\.?|profª|profa\.?|ing\.?|lic\.?|licda\.?|mtro\.?|mtra\.?|excmo\.?|ilmo\.?|ilma\.?|hno\.?|hna\.?|doctor|doctora)\s+/giu;

const LABEL_RE = new RegExp(
  '\\b(?:apellidos y nombre|nombre y apellidos?|nombre completo|nombre del titular|'
  + 'nombres?|apellidos?|titular(?:es)?|cliente|propietari[oa]|'
  + 'beneficiari[oa]|solicitante|firmante|fdo\\.?|firmad[oa]|firma(?=\\s*:)|'
  + 'interesado|compareciente|representante|padre|madre|tutor(?:a)?|'
  + 'estudiante|alumn[oa]|el que suscribe|abajo firmante)'
  + '\\s*:?\\s+',
  'giu'
);

const CONTEXT_RE = new RegExp(
  '\\b(?:el\\s+abajo\\s+firmante|la\\s+abajo\\s+firmante|abajo\\s+firmante|'
  + 'compareciente|el\\s+que\\s+suscribe|la\\s+persona\\s+f[ií]sica|'
  + 'representante\\s+legal|adjudicatario)(?:\\b[^\\n]{0,25}?)?',
  'giu'
);

function findNames(full) {
  const out = [];
  const anchors = [];

  let m;
  TITLE_RE.lastIndex = 0;
  while ((m = TITLE_RE.exec(full))) anchors.push({ position: m.index + m[0].length, allowUnknown: true, allowAllCaps: true });

  LABEL_RE.lastIndex = 0;
  while ((m = LABEL_RE.exec(full))) anchors.push({ position: m.index + m[0].length, allowUnknown: true, allowAllCaps: true });

  CONTEXT_RE.lastIndex = 0;
  while ((m = CONTEXT_RE.exec(full))) anchors.push({ position: m.index + m[0].length, allowUnknown: false, allowAllCaps: false });

  for (const anchor of anchors) {
    const r = captureNameRun(full, anchor.position, anchor);
    if (r) out.push({ ...r, type: 'name', confidence: anchor.allowUnknown ? 0.82 : 0.74 });
  }
  return out;
}

function findUnanchoredNames(full) {
  const out = [];
  const tokenStarts = /\b\p{Lu}[\p{L}'’\-‐]+/gu;
  let match;
  while ((match = tokenStarts.exec(full))) {
    if (!isKnownName(match[0])) continue;
    const captured = captureNameRun(full, match.index, { stopAtConjunction: true });
    if (!captured) continue;
    const knownTokens = captured.value.split(/\s+/).filter(isKnownName);
    if (knownTokens.length < 2) continue;
    out.push({ ...captured, type: 'name', confidence: 0.68 });
    tokenStarts.lastIndex = Math.max(tokenStarts.lastIndex, captured.end);
  }
  return out;
}

export const _debug = { TITLE_RE, LABEL_RE, CONTEXT_RE, ADDRESS_FIELD, captureNameRun, findNames, skipSeparators, TOKEN_RE, PARTICLES };

export function detectAll(full) {
  const cands = [];
  for (const r of BASE_RULES) {
    r.re.lastIndex = 0;
    let m;
    while ((m = r.re.exec(full))) {
      const valid = !r.validate || r.validate(m[0]);
      if (!valid && !r.keepInvalid) continue;
      cands.push({
        start: m.index, end: m.index + m[0].length, type: r.type, prio: r.prio,
        confidence: valid ? r.confidence : r.invalidConfidence, value: m[0], validationWarning: valid ? null : 'checksum',
      });
    }
  }
  for (const d of findDates(full)) cands.push({ ...d, prio: 700 });
  for (const a of findAddresses(full)) cands.push({ ...a, prio: 600 });
  for (const n of findNames(full)) cands.push({ ...n, prio: 500 });
  for (const n of findUnanchoredNames(full)) cands.push({ ...n, prio: 450 });

  cands.sort((a, b) => (b.prio - a.prio) || (a.start - b.start));

  const kept = [];
  for (const c of cands) {
    if (c.end - c.start <= 0) continue;
    if (kept.some((k) => c.start < k.end && c.end > k.start)) continue;
    kept.push(c);
  }
  return kept;
}
