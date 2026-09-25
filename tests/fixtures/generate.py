"""Adversarial corpus: one PDF per leak vector, all carrying the same canary data.

Every fixture shows the canary on the page (so it is detected) and hides further
copies in the structure being tested. After anonymisation, no copy may survive.
"""
from __future__ import annotations

import io
import zlib
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf as fitz
import pikepdf
from PIL import Image, ImageDraw, ImageFont

NAME = "Juan García Pérez"
DNI = "12345678Z"
CANARIES = [NAME, DNI]
ASSETS = Path(__file__).parent / "assets"
FONTS = Path("C:/Windows/Fonts")


@dataclass
class Fixture:
    number: int
    key: str
    data: bytes
    filename: str = ""
    canaries: list[str] = field(default_factory=lambda: list(CANARIES))
    needs_ocr: bool = False
    needs_faces: bool = False
    raster_only: bool = False  # only guaranteed by the maximum-security mode

    def __post_init__(self):
        if not self.filename:
            self.filename = f"{self.number:02d}_{self.key}.pdf"


def _visible_page(doc: fitz.Document, extra: str = "") -> fitz.Page:
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), f"Paciente: {NAME}", fontsize=12)
    page.insert_text((72, 120), f"DNI: {DNI}", fontsize=12)
    page.insert_text((72, 160), "Informe sin otros datos relevantes." + extra, fontsize=11)
    return page


def _base() -> fitz.Document:
    doc = fitz.open()
    _visible_page(doc)
    return doc


def _bytes(doc: fitz.Document) -> bytes:
    out = doc.tobytes(garbage=0, deflate=True)
    doc.close()
    return out


def _pike(data: bytes) -> pikepdf.Pdf:
    return pikepdf.open(io.BytesIO(data))


def _pike_bytes(pdf: pikepdf.Pdf) -> bytes:
    buffer = io.BytesIO()
    pdf.save(buffer)
    return buffer.getvalue()


def _xmp(value: str) -> bytes:
    return (f'<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?><x:xmpmeta xmlns:x="adobe:ns:meta/">'
            f'<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description '
            f'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:creator>{value}</dc:creator></rdf:Description>'
            f'</rdf:RDF></x:xmpmeta><?xpacket end="w"?>').encode("utf-8")


def _metadata_stream(pdf: pikepdf.Pdf, value: str) -> pikepdf.Stream:
    stream = pikepdf.Stream(pdf, _xmp(value))
    stream.Type = pikepdf.Name.Metadata
    stream.Subtype = pikepdf.Name.XML
    return stream


def _jpeg_with_text(text: str, size=(420, 80), font="arial.ttf", exif_text: str | None = None) -> bytes:
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    draw.text((10, 20), text, fill="black", font=ImageFont.truetype(str(FONTS / font), 30))
    buffer = io.BytesIO()
    kwargs = {}
    if exif_text:
        exif = Image.Exif()
        exif[0x010E] = exif_text  # ImageDescription
        exif[0x013B] = exif_text  # Artist
        kwargs["exif"] = exif.tobytes()
    image.save(buffer, "JPEG", quality=90, **kwargs)
    data = buffer.getvalue()
    if exif_text:
        # Add an XMP APP1 segment and a COM segment carrying the canary.
        xmp = b"http://ns.adobe.com/xap/1.0/\x00" + _xmp(exif_text)
        app1 = b"\xff\xe1" + (len(xmp) + 2).to_bytes(2, "big") + xmp
        com_payload = exif_text.encode("utf-8")
        com = b"\xff\xfe" + (len(com_payload) + 2).to_bytes(2, "big") + com_payload
        data = data[:2] + app1 + com + data[2:]
    return data


# ------------------------------------------------------------------ fixtures
def f01_info():
    doc = _base()
    doc.set_metadata({"author": NAME, "title": f"Informe de {NAME}", "subject": DNI, "keywords": NAME,
                      "creator": NAME, "producer": NAME, "creationDate": "D:19850314000000", "modDate": "D:20240101000000"})
    pdf = _pike(_bytes(doc))
    pdf.docinfo[pikepdf.Name("/Paciente")] = NAME
    pdf.docinfo[pikepdf.Name("/DNI")] = DNI
    return _pike_bytes(pdf)


def f02_xmp():
    doc = _base()
    image = _jpeg_with_text("sin datos")
    doc[0].insert_image(fitz.Rect(72, 300, 300, 350), stream=image)
    pdf = _pike(_bytes(doc))
    pdf.Root.Metadata = pdf.make_indirect(_metadata_stream(pdf, NAME))
    page = pdf.pages[0]
    page.obj.Metadata = pdf.make_indirect(_metadata_stream(pdf, DNI))
    for _, xobj in page.Resources.XObject.items():
        xobj.Metadata = pdf.make_indirect(_metadata_stream(pdf, NAME))
    for _, font in page.Resources.Font.items():
        font.Metadata = pdf.make_indirect(_metadata_stream(pdf, DNI))
    return _pike_bytes(pdf)


def f03_outlines():
    doc = _base()
    doc.new_page()
    doc.set_toc([[1, f"Historia de {NAME}", 1], [2, f"DNI {DNI}", 2]])
    doc.set_page_labels([{"startpage": 0, "prefix": f"{NAME}-", "style": "D", "firstpagenum": 1}])
    pdf = _pike(_bytes(doc))
    dest = pikepdf.Array([pdf.pages[0].obj, pikepdf.Name.Fit])
    pdf.Root.Names = pikepdf.Dictionary(Dests=pikepdf.Dictionary(Names=pikepdf.Array([pikepdf.String(NAME), dest])))
    pdf.Root.Dests = pikepdf.Dictionary({"/" + DNI: dest})
    return _pike_bytes(pdf)


def f04_tagged():
    pdf = _pike(_bytes(_base()))
    elem = pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name.P, Alt=pikepdf.String(NAME),
                              ActualText=pikepdf.String(DNI), T=pikepdf.String(NAME), E=pikepdf.String(DNI),
                              Pg=pdf.pages[0].obj, K=0)
    root = pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot, K=pikepdf.Array([pdf.make_indirect(elem)]))
    pdf.Root.StructTreeRoot = pdf.make_indirect(root)
    pdf.Root.MarkInfo = pikepdf.Dictionary(Marked=True)
    pdf.Root.Lang = pikepdf.String("es-ES")
    return _pike_bytes(pdf)


def f05_marked_content():
    pdf = _pike(_bytes(_base()))
    page = pdf.pages[0]
    actual = pikepdf.String(NAME).unparse().decode("latin-1")
    alt = pikepdf.String(DNI).unparse().decode("latin-1")
    prefix = f"/Span <</ActualText {actual} /Alt {alt} /E {actual}>> BDC\n".encode("latin-1")
    page.contents_add(pikepdf.Stream(pdf, prefix), prepend=True)
    page.contents_add(pikepdf.Stream(pdf, b"\nEMC\n"))
    return _pike_bytes(pdf)


def f06_invisible():
    doc = _base()
    doc[0].insert_text((72, 400), f"{NAME} {DNI}", fontsize=12, render_mode=3)
    return _bytes(doc)


def f07_outside_crop():
    doc = _base()
    page = doc[0]
    page.insert_text((72, 800), f"Copia: {NAME} {DNI}", fontsize=12)
    page.set_cropbox(fitz.Rect(0, 0, 595, 600))
    return _bytes(doc)


def f08_hidden_layer():
    doc = _base()
    ocg = doc.add_ocg("Privado", on=False)
    doc[0].insert_text((72, 450), f"Oculto: {NAME} {DNI}", fontsize=12, oc=ocg)
    return _bytes(doc)


def f09_white_tiny():
    doc = _base()
    page = doc[0]
    page.insert_text((72, 500), f"{NAME} {DNI}", fontsize=12, color=(1, 1, 1))
    page.insert_text((72, 520), f"{NAME} {DNI}", fontsize=0.5)
    return _bytes(doc)


def f10_annotations():
    doc = _base()
    page = doc[0]
    free = page.add_freetext_annot(fitz.Rect(72, 300, 400, 330), f"Revisado por {NAME}", fontsize=11)
    free.update()
    note = page.add_text_annot((450, 300), f"DNI del paciente {DNI}")
    note.set_info(title=NAME, content=f"Nota: {NAME} {DNI}")
    note.update()
    stamp = page.add_stamp_annot(fitz.Rect(72, 350, 300, 400), stamp=fitz.STAMP_Approved)
    stamp.set_info(title=NAME, content=DNI)
    stamp.update()
    ink = page.add_ink_annot([[(100, 500), (150, 520), (200, 480), (260, 530)]])
    ink.set_info(title=NAME)
    ink.update()
    return _bytes(doc)


def f11_form():
    doc = _base()
    page = doc[0]
    widget = fitz.Widget()
    widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    widget.field_name = "nombre"
    widget.field_label = f"Tooltip {NAME}"
    widget.field_value = NAME
    widget.rect = fitz.Rect(72, 300, 350, 320)
    page.add_widget(widget)
    widget2 = fitz.Widget()
    widget2.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    widget2.field_name = "dni"
    widget2.field_value = DNI
    widget2.rect = fitz.Rect(72, 330, 350, 350)
    page.add_widget(widget2)
    return _bytes(doc)


def f12_shared_xobject():
    doc = fitz.open()
    src = fitz.open()
    sp = src.new_page(width=400, height=100)
    sp.insert_text((10, 40), f"Paciente: {NAME}", fontsize=12)
    sp.insert_text((10, 70), f"DNI: {DNI}", fontsize=12)
    for _ in range(2):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 60), "Cabecera compartida:", fontsize=11)
        page.show_pdf_page(fitz.Rect(72, 80, 472, 180), src, 0)
    return _bytes(doc)


def f13_paths_and_raster():
    doc = _base()
    # Text as vector paths via SVG conversion.
    tmp = fitz.open()
    tp = tmp.new_page(width=400, height=60)
    tp.insert_text((10, 40), f"{NAME} {DNI}", fontsize=16)
    svg = tp.get_svg_image(text_as_path=True)
    vec = fitz.open(stream=svg.encode("utf-8"), filetype="svg")
    vec_pdf = fitz.open("pdf", vec.convert_to_pdf())
    doc[0].show_pdf_page(fitz.Rect(72, 300, 472, 360), vec_pdf, 0)
    # Text only present as pixels.
    image = _jpeg_with_text(f"{NAME} {DNI}", size=(560, 80))
    doc[0].insert_image(fitz.Rect(72, 400, 432, 452), stream=image)
    return _bytes(doc)


def f14_thumbnail():
    doc = _base()
    pix = doc[0].get_pixmap(dpi=40)
    pdf = _pike(_bytes(doc))
    thumb = pikepdf.Stream(pdf, zlib.compress(pix.samples))
    thumb.Width, thumb.Height = pix.width, pix.height
    thumb.ColorSpace = pikepdf.Name.DeviceRGB
    thumb.BitsPerComponent = 8
    thumb.Filter = pikepdf.Name.FlateDecode
    thumb.Canary = pikepdf.String(NAME)
    pdf.pages[0].obj.Thumb = pdf.make_indirect(thumb)
    return _pike_bytes(pdf)


def f15_pieceinfo():
    doc = _base()
    doc[0].insert_image(fitz.Rect(72, 300, 300, 350), stream=_jpeg_with_text("imagen"))
    pdf = _pike(_bytes(doc))
    private = pikepdf.Dictionary(Illustrator=pikepdf.Dictionary(
        LastModified=pikepdf.String("D:2024"), Private=pdf.make_indirect(pikepdf.Stream(pdf, f"{NAME} {DNI}".encode("utf-8")))))
    pdf.Root.PieceInfo = private
    pdf.pages[0].obj.PieceInfo = private
    for _, xobj in pdf.pages[0].Resources.XObject.items():
        alt_img = pikepdf.Stream(pdf, f"{NAME}".encode("utf-8"))
        xobj.Alternates = pikepdf.Array([pikepdf.Dictionary(Image=pdf.make_indirect(alt_img))])
        xobj.OPI = pikepdf.Dictionary({"/1.3": pikepdf.Dictionary(F=pikepdf.String(DNI))})
    pdf.Root.SpiderInfo = pikepdf.Dictionary(V=pikepdf.String(NAME))
    return _pike_bytes(pdf)


def f16_jpeg_exif():
    doc = _base()
    doc[0].insert_image(fitz.Rect(72, 300, 400, 360), stream=_jpeg_with_text("Foto adjunta", exif_text=f"{NAME} {DNI}"))
    return _bytes(doc)


def f17_incremental():
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), f"Paciente: {NAME}", fontsize=12)
    page.insert_text((72, 120), f"DNI: {DNI}", fontsize=12)
    tmp = Path(__file__).parent / "out" / "_incremental.pdf"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    doc.save(tmp)
    doc.close()
    # The DNI is removed from the current revision, but the incremental save keeps
    # the previous revision (with the DNI) inside the file.
    doc = fitz.open(tmp)
    page = doc[0]
    page.add_redact_annot(page.search_for(f"DNI: {DNI}")[0])
    page.apply_redactions()
    page.insert_text((72, 140), "Revisión posterior", fontsize=12)
    doc.saveIncr()
    doc.close()
    data = tmp.read_bytes()
    tmp.unlink()
    return data


def f18_attachments_js():
    doc = _base()
    doc.embfile_add(f"{NAME}.txt", f"{NAME} {DNI}".encode("utf-8"), filename=f"{NAME}.txt", desc=DNI)
    pdf = _pike(_bytes(doc))
    js = pikepdf.Dictionary(S=pikepdf.Name.JavaScript, JS=pikepdf.String(f"app.alert('{NAME} {DNI}');"))
    pdf.Root.OpenAction = js
    pdf.Root.Names.JavaScript = pikepdf.Dictionary(Names=pikepdf.Array([pikepdf.String("x"), js]))
    pdf.Root.AA = pikepdf.Dictionary(WC=js)
    pdf.pages[0].obj.AA = pikepdf.Dictionary(O=js)
    return _pike_bytes(pdf)


def f19_proportional():
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    font = fitz.Font(fontfile=str(FONTS / "times.ttf"))
    writer = fitz.TextWriter(page.rect)
    writer.append((72, 100), f"WWWWWWMMMM iiiiillll Paciente {NAME} con DNI {DNI} iiiillllWWWW", font=font, fontsize=12)
    writer.write_text(page)
    return _bytes(doc)


def f20_rotated():
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((150, 300), f"Paciente: {NAME}", fontsize=12)
    page.insert_text((150, 320), f"DNI: {DNI}", fontsize=12)
    page.set_cropbox(fitz.Rect(100, 200, 500, 700))
    page.set_rotation(90)
    return _bytes(doc)


def f21_filename():
    return _bytes(_base())


def f22_scan_with_photo():
    page_img = Image.new("RGB", (1240, 1754), "white")  # A4 at 150 dpi
    draw = ImageDraw.Draw(page_img)
    font = ImageFont.truetype(str(FONTS / "arial.ttf"), 34)
    draw.text((120, 200), f"Nombre: {NAME}", fill="black", font=font)
    draw.text((120, 260), f"DNI: {DNI}", fill="black", font=font)
    draw.text((120, 320), "Teléfono: 612 345 678", fill="black", font=font)
    photo = Image.open(ASSETS / "lena.jpg").convert("RGB").resize((180, 180))
    page_img.paste(photo, (900, 150))
    buffer = io.BytesIO()
    page_img.save(buffer, "JPEG", quality=85)
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(page.rect, stream=buffer.getvalue())
    return _bytes(doc)


def f23_handwritten():
    page_img = Image.new("RGB", (1240, 1754), (250, 250, 245))
    draw = ImageDraw.Draw(page_img)
    printed = ImageFont.truetype(str(FONTS / "arial.ttf"), 30)
    hand = ImageFont.truetype(str(FONTS / "Inkfree.ttf"), 44)
    draw.text((120, 200), "SOLICITUD DE CITA", fill="black", font=printed)
    draw.text((120, 300), "Nombre:", fill="black", font=printed)
    draw.text((300, 290), NAME, fill=(20, 30, 120), font=hand)
    draw.text((120, 380), "DNI:", fill="black", font=printed)
    draw.text((300, 370), DNI, fill=(20, 30, 120), font=hand)
    draw.text((120, 460), "Firma:", fill="black", font=printed)
    draw.line([(300, 480), (360, 440), (400, 500), (450, 445), (520, 490)], fill=(20, 30, 120), width=4)
    buffer = io.BytesIO()
    page_img.save(buffer, "JPEG", quality=88)
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(page.rect, stream=buffer.getvalue())
    return _bytes(doc)


def f24_jpx():
    """JPEG 2000 image with the name in its pixels and a copy in an XML box of the codestream."""
    image = Image.new("RGB", (900, 120), "white")
    ImageDraw.Draw(image).text((20, 30), f"{NAME} {DNI}", fill="black", font=ImageFont.truetype(str(FONTS / "arial.ttf"), 46))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG2000", irreversible=False)
    payload = f"<meta><autor>{NAME}</autor><dni>{DNI}</dni></meta>".encode("utf-8")
    jp2 = buffer.getvalue() + (len(payload) + 8).to_bytes(4, "big") + b"xml " + payload
    doc = _base()
    doc[0].insert_image(fitz.Rect(72, 300, 522, 360), stream=jp2)
    return _bytes(doc)


def f25_signed():
    """Digitally signed form: the signature dictionary names the signer and embeds a certificate."""
    doc = _base()
    widget = fitz.Widget()
    widget.field_type = fitz.PDF_WIDGET_TYPE_SIGNATURE
    widget.field_name = "firma"
    widget.rect = fitz.Rect(72, 400, 300, 450)
    doc[0].add_widget(widget)
    pdf = _pike(_bytes(doc))
    certificate = b"0\x82\x03\x10" + f"CN={NAME}, SERIALNUMBER=IDCES-{DNI}, C=ES".encode("utf-8") + bytes(64)
    signature = pikepdf.Dictionary(
        Type=pikepdf.Name.Sig, Filter=pikepdf.Name("/Adobe.PPKLite"), SubFilter=pikepdf.Name("/adbe.pkcs7.detached"),
        Name=pikepdf.String(NAME), ContactInfo=pikepdf.String(f"{DNI} · 612 345 678"), Reason=pikepdf.String(f"Firmado por {NAME}"),
        Location=pikepdf.String("Madrid"), M=pikepdf.String("D:20240101000000"),
        Contents=pikepdf.String(certificate), ByteRange=pikepdf.Array([0, 0, 0, 0]))
    for field in pdf.Root.AcroForm.Fields:
        if field.get("/FT") == pikepdf.Name.Sig:
            field.V = pdf.make_indirect(signature)
    pdf.Root.AcroForm.SigFlags = 3
    return _pike_bytes(pdf)


def build_all() -> list[Fixture]:
    return [
        Fixture(1, "info", f01_info()),
        Fixture(2, "xmp", f02_xmp()),
        Fixture(3, "outlines", f03_outlines()),
        Fixture(4, "tagged", f04_tagged()),
        Fixture(5, "marked_content", f05_marked_content()),
        Fixture(6, "invisible_text", f06_invisible()),
        Fixture(7, "outside_crop", f07_outside_crop()),
        Fixture(8, "hidden_layer", f08_hidden_layer()),
        Fixture(9, "white_tiny", f09_white_tiny()),
        Fixture(10, "annotations", f10_annotations()),
        Fixture(11, "acroform", f11_form()),
        Fixture(12, "shared_xobject", f12_shared_xobject()),
        Fixture(13, "paths_raster", f13_paths_and_raster(), needs_ocr=True),
        Fixture(14, "thumbnail", f14_thumbnail()),
        Fixture(15, "pieceinfo", f15_pieceinfo()),
        Fixture(16, "jpeg_exif", f16_jpeg_exif()),
        Fixture(17, "incremental", f17_incremental(), canaries=[NAME]),  # the DNI only exists in the old revision
        Fixture(18, "attachments_js", f18_attachments_js()),
        Fixture(19, "proportional", f19_proportional()),
        Fixture(20, "rotated", f20_rotated()),
        Fixture(21, "filename", f21_filename(), filename="Juan_Garcia_Perez_12345678Z_informe.pdf"),
        Fixture(22, "scan_photo", f22_scan_with_photo(), needs_ocr=True, needs_faces=True),
        Fixture(23, "handwritten", f23_handwritten(), needs_ocr=True),
        Fixture(24, "jpeg2000", f24_jpx(), needs_ocr=True),
        Fixture(25, "digital_signature", f25_signed()),
    ]


def main() -> None:
    out = Path(__file__).parent / "out"
    out.mkdir(exist_ok=True)
    for fixture in build_all():
        (out / fixture.filename).write_bytes(fixture.data)
        print(f"{fixture.filename}: {len(fixture.data)} bytes")


if __name__ == "__main__":
    main()
