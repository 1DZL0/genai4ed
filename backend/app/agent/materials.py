"""Reads what a teacher uploads so the class agent can teach from it.

Documents become text; images are passed to the model as they are.
Scanned PDFs come out empty (no OCR yet) and the teacher is told so.
"""

import io
from dataclasses import dataclass

DOCUMENT_TYPES = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "text/plain": "text",
    "text/markdown": "text",
}
IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
EXTENSIONS = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
MAX_TEXT = 200_000


class UnsupportedMaterial(ValueError):
    pass


@dataclass(frozen=True)
class Extracted:
    media_type: str
    text: str
    is_image: bool


def media_type_for(filename: str, declared: str | None) -> str:
    """The file's extension over the browser's guess, which is often blank."""
    lowered = filename.lower()
    for ext, media in EXTENSIONS.items():
        if lowered.endswith(ext):
            return media
    if declared in DOCUMENT_TYPES or declared in IMAGE_TYPES:
        return declared
    raise UnsupportedMaterial(
        "That file type isn't supported yet. Use PDF, Word, PowerPoint, text or an image."
    )


def extract(filename: str, declared_type: str | None, content: bytes) -> Extracted:
    media_type = media_type_for(filename, declared_type)
    if media_type in IMAGE_TYPES:
        return Extracted(media_type, "", True)
    kind = DOCUMENT_TYPES[media_type]
    try:
        if kind == "pdf":
            text = _pdf(content)
        elif kind == "docx":
            text = _docx(content)
        elif kind == "pptx":
            text = _pptx(content)
        else:
            text = content.decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001 - any parser failure is the same answer to a teacher
        raise UnsupportedMaterial(f"Couldn't read {filename}. Is it a working file?") from exc
    return Extracted(media_type, text.strip()[:MAX_TEXT], False)


def _pdf(content: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    return "\n\n".join((page.extract_text() or "") for page in reader.pages)


def _docx(content: bytes) -> str:
    from docx import Document

    document = Document(io.BytesIO(content))
    parts = [p.text for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text.strip() for cell in row.cells))
    return "\n".join(parts)


def _pptx(content: bytes) -> str:
    from pptx import Presentation

    deck = Presentation(io.BytesIO(content))
    slides: list[str] = []
    for number, slide in enumerate(deck.slides, start=1):
        lines = [
            shape.text_frame.text
            for shape in slide.shapes
            if getattr(shape, "has_text_frame", False) and shape.text_frame.text.strip()
        ]
        if lines:
            slides.append(f"Slide {number}:\n" + "\n".join(lines))
    return "\n\n".join(slides)
