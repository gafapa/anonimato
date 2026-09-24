import { detectAll } from './js/detectors.js';

const cases = [
  'EXPEDIENTE 2024/001\nTRIBUNAL SUPERIOR DE JUSTICIA DE GALICIA\nEl presente documento no contiene datos.',
  'La empresa ACERO S.L. con CIF B12345678, sita en Polígono de Sabón, 12, 15080 A Coruña.',
  'NOMBRE DEL CENTRO: IES Pontedeume. Solicita el alumno de 2º de ESO.',
  'www.ejemplo.com y https://correo.insti.edu/post/1?x=2 y john.doe@universidad.edu',
  'Nº de expediente: 2025/0003821. Referencia interna 882233.',
  'Dirección de correo electrónico de contacto: info@empresa.com, teléfono +34 981 234 567.',
  'Su DNI es 12345678Z y el NIE X1234567L y el NSS 12/34567890/12.',
  'Matrícula del vehículo: 1234 ABC. Otra matrícula 0000BZL.',
  'Trimestre 1 · Curso 2021-2022 · Alumnado matriculado en 4º curso.',
];

for (const t of cases) {
  const res = detectAll(t).sort((a, b) => a.start - b.start);
  const line = res.map((m) => `${m.type}:${t.slice(m.start, m.end)}`).join('  ') || '(nada)';
  console.log(line + '\n   ← ' + t.split('\n')[0].slice(0, 60));
}
