import pytest

from app.engine.rules import canonical, detect_all


def values(text, kind):
    return [m.value for m in detect_all(text) if m.type == kind]


def spans(text, kind):
    return [text[m.start:m.end] for m in detect_all(text) if m.type == kind]


# ---- ported from the web version -------------------------------------------------
def test_dni_valid_and_invalid_kept_for_review():
    assert values("DNI 12345678Z", "dni") == ["12345678Z"]
    invalid = [m for m in detect_all("DNI 12345678A") if m.type == "dni"][0]
    assert invalid.warning == "checksum" and invalid.confidence < 0.8


def test_nie_valid_and_invalid():
    assert values("NIE X1234567L", "nie") == ["X1234567L"]
    assert [m for m in detect_all("NIE X1234567A") if m.type == "nie"][0].warning == "checksum"


def test_formatted_dni():
    assert values("NIF: 12.345.678-Z", "dni") == ["12.345.678-Z"]
    assert values("DNI 12345678 Z", "dni") == ["12345678 Z"]


def test_email_and_url_do_not_overlap():
    result = detect_all("Contacto: person@example.org y https://example.org/profile")
    assert [m.type for m in result].count("email") == 1
    assert [m.type for m in result].count("url") == 1


def test_birth_date_needs_context():
    assert values("Contrato firmado el 14/03/1985.", "date") == []
    assert values("Fecha de nacimiento: 14/03/1985.", "date") == ["14/03/1985"]
    assert values("Nacido en Lugo el 3 de marzo de 1990.", "date") == ["3 de marzo de 1990"]


def test_iban():
    assert values("Cuenta ES91 2100 0418 4502 0005 1332", "iban") == ["ES91 2100 0418 4502 0005 1332"]
    assert values("Cuenta ES00 2100 0418 4502 0005 1332", "iban") == []
    assert values("IBAN: ES9121000418450200051332", "iban") == ["ES9121000418450200051332"]


def test_foreign_iban_and_ccc():
    assert values("IBAN DE89 3704 0044 0532 0130 00", "iban") == ["DE89 3704 0044 0532 0130 00"]
    assert values("CCC 2100 0418 45 0200051332", "iban") == ["2100 0418 45 0200051332"]


def test_card_luhn():
    assert values("Tarjeta 4111 1111 1111 1111", "card") == ["4111 1111 1111 1111"]
    assert values("Referencia 4111 1111 1111 1112", "card") == []


def test_labelled_international_names():
    assert values("Cliente: Siobhan O’Connor", "name") == ["Siobhan O’Connor"]
    assert values("Titular: François Dubois", "name") == ["François Dubois"]
    assert values("Nombre:\nAaliyah\nKuznetsova", "name") == ["Aaliyah Kuznetsova"]
    assert spans("APELLIDOS Y NOMBRE: PÉREZ GARCÍA, JUAN", "name") == ["PÉREZ GARCÍA, JUAN"]


def test_unlabelled_known_names():
    names = values("Comparecen Juan García Pérez y Ana López Torres ante el tribunal.", "name")
    assert any("Juan García Pérez" in n for n in names)
    assert any("Ana López Torres" in n for n in names)


# ---- review findings ------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("Vive en C/ Mayor 5, 3ºA, Madrid.", "C/ Mayor 5, 3ºA, Madrid"),
    ("Vive en Avda. de América 12, Madrid.", "Avda. de América 12, Madrid"),
    ("Domicilio: Rúa do Franco 14, 2º izq, 15702 Santiago", "Rúa do Franco 14, 2º izq, 15702 Santiago"),
    ("Calle Mayor 12, 28013 Madrid", "Calle Mayor 12, 28013 Madrid"),
])
def test_addresses_including_abbreviations(text, expected):
    assert expected in spans(text, "address")


def test_address_label_is_not_redacted():
    found = spans("Dirección: Avda. de la Constitución 45, 2ºB, Sevilla 41010", "address")
    assert found and not found[0].lower().startswith("direcci")


@pytest.mark.parametrize("text,expected", [
    ("Tel. 912 34 56 78", "912 34 56 78"),
    ("Teléfono: 612345678", "612345678"),
    ("Tlf: (+34) 612 345 678", "(+34) 612 345 678"),
    ("Móvil 0034 612-345-678", "0034 612-345-678"),
    ("Teléfono: +351 912 345 678", "+351 912 345 678"),
])
def test_phones(text, expected):
    assert expected in spans(text, "phone")


def test_nss_requires_checksum_or_context():
    assert values("Pedido nº 123456789012 del 2024.", "nss") == []
    # 28/12345678/xx with the right control digits
    number = 28 * 10**8 + 12345678
    valid = f"28/12345678/{number % 97:02d}"
    assert values(f"Afiliación {valid}", "nss") == [valid]
    assert [m.warning for m in detect_all("NSS: 28/12345678/00") if m.type == "nss"] == ["checksum"]


def test_plates():
    assert values("Matrícula del vehículo: 1234 BCD.", "plate") == ["1234 BCD"]
    assert values("Matrícula 1234 ABC", "plate") == []
    assert values("Vehículo con matrícula M-1234-AB", "plate") == ["M-1234-AB"]


def test_canonical_tokens_match_formats():
    assert canonical("dni", "12345678Z") == canonical("dni", "12.345.678-z")
    assert canonical("name", "José PÉREZ") == canonical("name", "jose perez")


def test_new_categories():
    assert values("Pasaporte: PAB123456", "passport") == ["PAB123456"]
    assert values("BIC: CAIXESBBXXX", "bic") == ["CAIXESBBXXX"]
    assert values("IP de acceso 192.168.1.20", "ip") == ["192.168.1.20"]
    assert values("Versión 1.2.3.400", "ip") == []
    assert values("Nº colegiado: 282812345", "id_other") == ["282812345"]
    assert values("NHC: 00123456", "id_other") == ["00123456"]


def test_cif():
    assert values("CIF B12345674", "cif") == ["B12345674"]


def test_no_false_positives_on_neutral_text():
    text = ("EXPEDIENTE 2024/001\nTRIBUNAL SUPERIOR DE JUSTICIA DE GALICIA\nEl presente documento no contiene datos.\n"
            "Trimestre 1 · Curso 2021-2022 · Alumnado matriculado en 4º curso. Versión 3.2.1")
    kinds = {m.type for m in detect_all(text)}
    assert kinds <= {"id_other"}


def test_fuzzy_verification_matching():
    from app.engine.verify import Target, fuzzy_found
    name = Target.build("name", "Juan García Pérez")
    assert fuzzy_found(name, "texto JUAN GARCIA PEREZ texto")
    assert fuzzy_found(name, "Juan Garcfa Pérez")          # one OCR error
    assert not fuzzy_found(name, "r")
    assert not fuzzy_found(name, "[NOMBRE 1] texto")
    dni = Target.build("dni", "12345678Z")
    assert fuzzy_found(dni, "DNI 12.345.678-Z")
    assert fuzzy_found(dni, "DNI 1234567BZ")               # OCR confusion 8/B
    assert not fuzzy_found(dni, "[DNI 1]")


def test_name_does_not_swallow_next_line():
    assert values("Paciente: Juan García Pérez\nRevisión posterior", "name") == ["Juan García Pérez"]


def test_wrapped_and_unicode_values():
    assert values("Contacto: uxía.varela@correo.es", "email") == ["uxía.varela@correo.es"]
    assert "ES91 2100 0418\n4502 0005 1332" in spans("Pagar en la cuenta ES91 2100 0418\n4502 0005 1332 antes", "iban")
    found = spans("con domicilio en Rúa do Vilar 1, 2ºA,\n33003 Oviedo. Otro texto", "address")
    assert found and found[0].endswith("33003 Oviedo")


def test_rare_given_name_before_known_surnames():
    names = values("Comparecen Juan Pérez López y Jaione Varela Castro, vecinos de Vigo.", "name")
    assert any("Jaione Varela Castro" in n for n in names)
