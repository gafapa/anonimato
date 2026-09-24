import test from 'node:test';
import assert from 'node:assert/strict';
import { detectAll } from './js/detectors.js';

function matches(text, type) {
  return detectAll(text).filter((item) => item.type === type).map((item) => item.value);
}

test('accepts valid DNI and keeps invalid check letters for review', () => {
  assert.deepEqual(matches('DNI 12345678Z', 'dni'), ['12345678Z']);
  const invalid = detectAll('DNI 12345678A').find((item) => item.type === 'dni');
  assert.equal(invalid.value, '12345678A');
  assert.equal(invalid.validationWarning, 'checksum');
  assert.ok(invalid.confidence < 0.8);
});

test('accepts valid NIE and keeps invalid check letters for review', () => {
  assert.deepEqual(matches('NIE X1234567L', 'nie'), ['X1234567L']);
  const invalid = detectAll('NIE X1234567A').find((item) => item.type === 'nie');
  assert.equal(invalid.validationWarning, 'checksum');
});

test('recognizes formatted and split DNI values', () => {
  assert.deepEqual(matches('NIF: 12.345.678-Z', 'dni'), ['12.345.678-Z']);
  assert.deepEqual(matches('DNI 12345678 Z', 'dni'), ['12345678 Z']);
});

test('prioritizes email over overlapping URL-like content', () => {
  const result = detectAll('Contacto: person@example.org y https://example.org/profile');
  assert.equal(result.filter((item) => item.type === 'email').length, 1);
  assert.equal(result.filter((item) => item.type === 'url').length, 1);
});

test('does not treat an unrelated date as a birth date', () => {
  assert.deepEqual(matches('Contrato firmado el 14/03/1985.', 'date'), []);
  assert.deepEqual(matches('Fecha de nacimiento: 14/03/1985.', 'date'), ['14/03/1985']);
});

test('validates Spanish IBAN values', () => {
  assert.deepEqual(matches('Cuenta ES91 2100 0418 4502 0005 1332', 'iban'), ['ES91 2100 0418 4502 0005 1332']);
  assert.deepEqual(matches('Cuenta ES00 2100 0418 4502 0005 1332', 'iban'), []);
});

test('validates payment card numbers with Luhn checksum', () => {
  assert.deepEqual(matches('Tarjeta 4111 1111 1111 1111', 'card'), ['4111 1111 1111 1111']);
  assert.deepEqual(matches('Referencia 4111 1111 1111 1112', 'card'), []);
});

test('detects international names after strong labels', () => {
  assert.deepEqual(matches('Cliente: Siobhan O’Connor', 'name'), ['Siobhan O’Connor']);
  assert.deepEqual(matches('Titular: François Dubois', 'name'), ['François Dubois']);
  assert.deepEqual(matches('APELLIDOS Y NOMBRE: PÉREZ GARCÍA, JUAN', 'name'), ['PÉREZ GARCÍA JUAN']);
  assert.deepEqual(matches('Nombre:\nAaliyah\nKuznetsova', 'name'), ['Aaliyah Kuznetsova']);
});

test('detects known full names without a field label', () => {
  const names = matches('Comparecen Juan García Pérez y Ana López Torres ante el tribunal.', 'name');
  assert.ok(names.some((name) => name.includes('Juan García Pérez')));
  assert.ok(names.some((name) => name.includes('Ana López Torres')));
});
