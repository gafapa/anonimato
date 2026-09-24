import { detectAll } from './js/detectors.js';

const cases = [
  'Cliente: María del Carmen Rodríguez.',
  'El Sr. Juan García Pérez, con DNI 12345678Z, reside en Calle Mayor 12, 28013 Madrid.',
  'Fecha de nacimiento: 14/03/1985. Teléfono: 600 123 456',
  'Comparece la abajo firmante, Ana Pérez López, con NIE X1234567L.',
  'Calle Mayor 12, 28013 Madrid\nTeléfono 600 123 456',
  'Dirección: Avda. de la Constitución 45, 2ºB, Sevilla 41010',
];

for (const t of cases) {
  const res = detectAll(t).sort((a, b) => a.start - b.start);
  console.log('\nTEXT: ' + t);
  for (const m of res) {
    console.log(`  ${m.type.padEnd(8)} [${m.start}-${m.end}] "${t.slice(m.start, m.end)}"  v="${m.value}"`);
  }
}
