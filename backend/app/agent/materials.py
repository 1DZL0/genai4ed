"""Reads what a teacher uploads so the class agent can teach from it.

Documents become text, and the pictures inside them (a diagram in a handout, the pages of a
scan) are pulled out so the drafting agent can be shown them and a page that is only a
picture can be read into words (see `reading`). Uploaded images are passed on as they are.
"""

import io
import re
from dataclasses import dataclass, field

# Pictures kept from inside a document: enough for a handout, not a whole photo album.
MAX_PICTURES = 6
# Smaller than this is a bullet, an icon or a logo, not something to teach from.
MIN_PICTURE_SIDE = 100
MIN_PICTURE_BYTES = 2_000

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
# A picture kept from inside a document is named after the document. The name is the only
# link between the two, and it is what the teacher and the agent both call the picture.
_PICTURE_NAME = re.compile(r"(?P<file>.+) \(picture (?P<number>\d+)\)", re.DOTALL)


class UnsupportedMaterial(ValueError):
    pass


@dataclass(frozen=True)
class Extracted:
    media_type: str
    text: str
    is_image: bool
    # Pictures found inside a document, as (media type, bytes), in order, at most MAX_PICTURES.
    images: tuple[tuple[str, bytes], ...] = field(default=())

    @property
    def needs_reading(self) -> bool:
        """No words of its own but pictures that may hold some: a scan, a photographed page.
        A document with any typed text keeps that and is not read; its pictures stay pictures."""
        return self.is_image or (not self.text.strip() and bool(self.images))


def picture_name(filename: str, number: int) -> str:
    """What the nth picture kept from inside a document is called."""
    return f"{filename} (picture {number})"[:255]


def picture_of(filename: str) -> tuple[str, int] | None:
    """The document a kept picture came out of and its number there, read back from its name;
    None for anything not named that way."""
    named = _PICTURE_NAME.fullmatch(filename)
    return (named["file"], int(named["number"])) if named else None


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
    images: list[tuple[str, bytes]] = []
    try:
        if kind == "pdf":
            text = _pdf(content)
            images = _pdf_images(content)
        elif kind == "docx":
            text = _docx(content)
            images = _docx_images(content)
        elif kind == "pptx":
            text = _pptx(content)
            images = _pptx_images(content)
        else:
            text = content.decode("utf-8", errors="replace")
    except Exception as exc:  # any parser failure is the same answer to a teacher
        raise UnsupportedMaterial(f"Couldn't read {filename}. Is it a working file?") from exc
    return Extracted(media_type, text.strip()[:MAX_TEXT], False, tuple(images))


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


# ---------- the pictures inside a document ----------


def _worth_keeping(data: bytes) -> tuple[str, bytes] | None:
    """A picture big enough to teach from, as PNG or JPEG bytes; None for icons and bullets,
    and for anything Pillow cannot open."""
    from PIL import Image

    if len(data) < MIN_PICTURE_BYTES:
        return None
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception:  # an unreadable picture is simply left out
        return None
    if min(image.size) < MIN_PICTURE_SIDE:
        return None
    if image.format in ("PNG", "JPEG"):
        return (f"image/{image.format.lower()}", data)
    out = io.BytesIO()
    image.convert("RGB").save(out, format="PNG")
    return ("image/png", out.getvalue())


def _keep(candidates) -> list[tuple[str, bytes]]:
    kept: list[tuple[str, bytes]] = []
    for data in candidates:
        if len(kept) >= MAX_PICTURES:
            break
        picture = _worth_keeping(data)
        if picture is not None:
            kept.append(picture)
    return kept


def _pdf_images(content: bytes) -> list[tuple[str, bytes]]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))

    def pictures():
        for page in reader.pages:
            try:
                files = list(page.images)
            except Exception:  # a page whose pictures cannot be read has none
                continue
            for image_file in files:
                try:
                    yield image_file.data
                except Exception:
                    continue

    return _keep(pictures())


def _docx_images(content: bytes) -> list[tuple[str, bytes]]:
    from docx import Document

    document = Document(io.BytesIO(content))
    # Only pictures the body refers to: the package also holds a thumbnail and the like.
    parts = [
        rel.target_part
        for rel in document.part.rels.values()
        if "image" in rel.reltype and not rel.is_external
    ]
    return _keep(part.blob for part in parts)


def _pptx_images(content: bytes) -> list[tuple[str, bytes]]:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    deck = Presentation(io.BytesIO(content))

    def pictures():
        for slide in deck.slides:
            for shape in slide.shapes:
                if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                    yield shape.image.blob

    return _keep(pictures())
