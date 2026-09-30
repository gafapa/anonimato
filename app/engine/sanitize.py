"""Structural cleaning of the output PDF (pikepdf / qpdf).

Removes every structure that can carry copies of the original data outside the
visible page content: metadata, outlines, tags, alternate texts, thumbnails,
attachments, scripts, private application data and JPEG metadata segments.
"""
from __future__ import annotations

import io

import pikepdf
from PIL import Image

ROOT_KEYS = [
    "/Metadata", "/Outlines", "/PageLabels", "/Names", "/Dests", "/OpenAction", "/AA", "/AcroForm",
    "/StructTreeRoot", "/MarkInfo", "/Threads", "/PieceInfo", "/SpiderInfo", "/Collection", "/Perms",
    "/DSS", "/Legal", "/URI", "/Lang", "/AF", "/Requirements", "/ViewerPreferences", "/PageMode",
]
PAGE_KEYS = [
    "/Thumb", "/Metadata", "/PieceInfo", "/B", "/AA", "/StructParents", "/Annots", "/ID", "/PZ",
    "/SeparationInfo", "/Trans", "/AF", "/Tabs", "/TemplateInstantiated", "/CropBox", "/BleedBox",
    "/TrimBox", "/ArtBox", "/BoxColorInfo", "/VP", "/LastModified", "/UserUnit",
]
ANY_KEYS = ["/Metadata", "/PieceInfo", "/Alternates", "/OPI", "/Thumb", "/StructParent", "/StructParents",
            "/AF", "/LastModified", "/ActualText"]
MARKED_KEYS = ("/ActualText", "/Alt", "/E", "/T", "/Lang")
KEEP_APP = {0xE0, 0xE2, 0xEE}  # JFIF, ICC profile, Adobe (colour transform)


def strip_jpeg_metadata(data: bytes) -> bytes:
    """Lossless removal of EXIF/XMP/IPTC/comments (APPn and COM segments) from a JPEG stream."""
    if data[:2] != b"\xff\xd8":
        return data
    out = bytearray(b"\xff\xd8")
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            return data  # unexpected layout: leave untouched (max-security mode still covers it)
        marker = data[pos + 1]
        if marker == 0xFF:
            pos += 1
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            out += data[pos:pos + 2]
            pos += 2
            continue
        length = int.from_bytes(data[pos + 2:pos + 4], "big")
        segment = data[pos:pos + 2 + length]
        if marker == 0xDA:  # start of scan: copy the rest
            out += data[pos:]
            return bytes(out)
        is_meta = (0xE1 <= marker <= 0xEF and marker not in KEEP_APP) or marker == 0xFE
        if marker == 0xE2 and not segment[4:16].startswith(b"ICC_PROFILE"):
            is_meta = True
        if not is_meta:
            out += segment
        pos += 2 + length
    return bytes(out)


def _filters(stream: pikepdf.Stream) -> list[str]:
    value = stream.get("/Filter")
    if value is None:
        return []
    if isinstance(value, pikepdf.Array):
        return [str(item) for item in value]
    return [str(value)]


def _clean_image(stream: pikepdf.Stream) -> None:
    filters = _filters(stream)
    if filters == ["/DCTDecode"]:
        raw = stream.read_raw_bytes()
        cleaned = strip_jpeg_metadata(raw)
        if cleaned != raw:
            stream.write(cleaned, filter=pikepdf.Name.DCTDecode)
    elif "/JPXDecode" in filters:
        # JPEG 2000 can embed XML/UUID boxes: decode and store the pixels again.
        try:
            image = Image.open(io.BytesIO(stream.read_raw_bytes()))
            image.load()
        except Exception:
            return
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=95)
        stream.write(buffer.getvalue(), filter=pikepdf.Name.DCTDecode)
        stream.ColorSpace = pikepdf.Name.DeviceRGB if image.mode == "RGB" else pikepdf.Name.DeviceGray
        stream.BitsPerComponent = 8
        for key in ("/DecodeParms", "/SMaskInData", "/Decode"):
            if key in stream:
                del stream[key]


def _clean_marked_content(stream: pikepdf.Stream) -> None:
    """Remove alternate/actual texts from BDC property dictionaries inside a content stream."""
    try:
        instructions = pikepdf.parse_content_stream(stream)
    except Exception:
        return
    changed = False
    rebuilt = []
    for instruction in instructions:
        if isinstance(instruction, pikepdf.ContentStreamInlineImage):
            rebuilt.append(instruction)
            continue
        operands, operator = instruction.operands, instruction.operator
        if str(operator) in ("BDC", "DP") and len(operands) == 2 and isinstance(operands[1], pikepdf.Dictionary):
            props = operands[1]
            for key in MARKED_KEYS:
                if key in props:
                    del props[key]
                    changed = True
        rebuilt.append(pikepdf.ContentStreamInstruction(operands, operator))
    if changed:
        stream.write(pikepdf.unparse_content_stream(rebuilt))


def _content_streams(pdf: pikepdf.Pdf):
    for page in pdf.pages:
        contents = page.obj.get("/Contents")
        if isinstance(contents, pikepdf.Array):
            yield from (item for item in contents if isinstance(item, pikepdf.Stream))
        elif isinstance(contents, pikepdf.Stream):
            yield contents
    for obj in pdf.objects:
        if isinstance(obj, pikepdf.Stream) and obj.get("/Subtype") == pikepdf.Name.Form:
            yield obj


def _rename_layers(pdf: pikepdf.Pdf) -> None:
    props = pdf.Root.get("/OCProperties")
    if props is None:
        return
    for index, ocg in enumerate(props.get("/OCGs", []), start=1):
        if isinstance(ocg, pikepdf.Dictionary):
            ocg.Name = pikepdf.String(f"Capa {index}")
            for key in ("/Usage", "/Intent"):
                if key in ocg:
                    del ocg[key]
    config = props.get("/D")
    if isinstance(config, pikepdf.Dictionary):
        for key in ("/Name", "/Creator", "/AS", "/Order", "/Locked", "/RBGroups"):
            if key in config:
                del config[key]
    if "/Configs" in props:
        del props["/Configs"]


def _normalise_boxes(page: pikepdf.Page) -> None:
    """MediaBox := visible CropBox; other boxes removed."""
    obj = page.obj
    crop = obj.get("/CropBox")
    media = page.mediabox
    if crop is not None:
        c = [float(v) for v in crop]
        m = [float(v) for v in media]
        box = [max(min(c[0], c[2]), min(m[0], m[2])), max(min(c[1], c[3]), min(m[1], m[3])),
               min(max(c[0], c[2]), max(m[0], m[2])), min(max(c[1], c[3]), max(m[1], m[3]))]
        if box[2] > box[0] and box[3] > box[1]:
            obj.MediaBox = pikepdf.Array(box)


def sanitize(data: bytes) -> bytes:
    pdf = pikepdf.open(io.BytesIO(data))
    with pdf:
        if "/Info" in pdf.trailer:
            del pdf.trailer["/Info"]
        root = pdf.Root
        for key in ROOT_KEYS:
            if key in root:
                del root[key]
        _rename_layers(pdf)
        for page in pdf.pages:
            _normalise_boxes(page)
            for key in PAGE_KEYS:
                if key in page.obj:
                    del page.obj[key]
        for obj in pdf.objects:
            if not isinstance(obj, (pikepdf.Dictionary, pikepdf.Stream)):
                continue
            kind = obj.get("/Type")
            if kind in (pikepdf.Name.Metadata, pikepdf.Name.EmbeddedFile, pikepdf.Name.Filespec):
                continue  # unreachable once references are removed
            for key in ANY_KEYS:
                if key in obj:
                    try:
                        del obj[key]
                    except Exception:
                        pass
            if isinstance(obj, pikepdf.Stream) and obj.get("/Subtype") == pikepdf.Name.Image:
                _clean_image(obj)
            resources = obj.get("/Resources") if isinstance(obj, (pikepdf.Dictionary, pikepdf.Stream)) else None
            if isinstance(resources, pikepdf.Dictionary) and "/Properties" in resources:
                for _, prop in resources.Properties.items():
                    if isinstance(prop, pikepdf.Dictionary) and prop.get("/Type") != pikepdf.Name.OCG:
                        for key in MARKED_KEYS + ("/Metadata",):
                            if key in prop:
                                del prop[key]
        for stream in list(_content_streams(pdf)):
            _clean_marked_content(stream)
        buffer = io.BytesIO()
        pdf.remove_unreferenced_resources()
        pdf.save(buffer, compress_streams=True, object_stream_mode=pikepdf.ObjectStreamMode.generate,
                 fix_metadata_version=False, linearize=False, static_id=False,
                 stream_decode_level=pikepdf.StreamDecodeLevel.generalized)
    return buffer.getvalue()
