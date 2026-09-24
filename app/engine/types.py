from __future__ import annotations

from dataclasses import asdict, dataclass, field

Rect = tuple[float, float, float, float]  # x0, y0, x1, y1 in page coordinates (points, rotated page space)


@dataclass
class Finding:
    id: str
    page: int                 # 0-based page index
    type: str
    value: str | None         # original text (None for faces, signatures, manual areas)
    rects: list[Rect]
    confidence: float
    source: str               # text | ocr | handwriting | ai | llm | propagation | face | signature | manual | form
    enabled: bool = True
    warning: str | None = None
    token: str = ""
    key: str = ""             # canonical key shared by equal values
    detail: str = ""          # human-readable note (e.g. "leído a mano", "revisar")

    def to_json(self) -> dict:
        data = asdict(self)
        data["rects"] = [list(r) for r in self.rects]
        return data


@dataclass
class OcrLine:
    text: str
    rect: Rect
    confidence: float
    char_rects: list[Rect | None] = field(default_factory=list)
    handwritten: bool = False
    engine: str = "ppocr"


@dataclass
class PageText:
    """Text of a page with a rectangle per character (None for synthetic separators)."""
    text: str
    boxes: list[Rect | None]

    def rects_for(self, start: int, end: int) -> list[Rect]:
        """Tight rectangles for a character span, merged per visual line."""
        rects: list[Rect] = []
        current: list[float] | None = None
        for box in self.boxes[start:end]:
            if box is None:
                continue
            if current and abs(box[1] - current[1]) < 0.6 * (current[3] - current[1]) and box[0] >= current[0] - 1:
                current[0] = min(current[0], box[0])
                current[1] = min(current[1], box[1])
                current[2] = max(current[2], box[2])
                current[3] = max(current[3], box[3])
            else:
                if current:
                    rects.append(tuple(current))
                current = list(box)
        if current:
            rects.append(tuple(current))
        return rects


@dataclass
class Options:
    categories: set[str]
    ocr: bool = True
    handwriting: bool = True         # needs the advanced pack
    ai: bool = True                  # GLiNER
    llm_review: bool = True          # needs the advanced pack
    faces: bool = True
    signatures: bool = True
    propagate: bool = True
    mode: str = "label"              # label | blank
    max_security: bool = False
    raster_dpi: int = 300
    ocr_text_layer: bool = True      # searchable layer in maximum-security mode
    uniform_tokens: bool = False
    dpi: int = 200                   # analysis render resolution
    use_gpu: bool = True
