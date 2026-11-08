"""Pictures inside what a teacher attaches: pulled out of Word, PowerPoint and PDF files so
the drafting agent can see them, and read into text when a page is only a picture (a scan,
a photo of a worksheet), so both agents get the words."""

import io

import pypdf
import pytest
from PIL import Image

from app.agent import llm, materials
from app.agent.materials import MIN_PICTURE_BYTES, UnsupportedMaterial, _worth_keeping, extract
from app.models import Material
from tests.test_thread import DESCRIBE, last_card, say

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def png(width: int, height: int, colour=(200, 40, 40)) -> bytes:
    """A picture with some detail in it, as a real diagram has; a flat colour would compress
    down to the size of an icon and be left out on purpose."""
    image = Image.new("RGB", (width, height), colour)
    pixels = image.load()
    for y in range(0, height, 3):
        for x in range(0, width, 3):
            pixels[x, y] = ((x * 7) % 256, (y * 13) % 256, (x * y) % 256)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def docx_with(picture: bytes | None, text: str = "Photosynthesis needs light.") -> bytes:
    from docx import Document

    doc = Document()
    doc.add_paragraph(text)
    if picture is not None:
        doc.add_picture(io.BytesIO(picture))
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def pptx_with(picture: bytes) -> bytes:
    from pptx import Presentation
    from pptx.util import Inches

    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    slide.shapes.add_picture(io.BytesIO(picture), Inches(1), Inches(1))
    out = io.BytesIO()
    deck.save(out)
    return out.getvalue()


def scanned_pdf(pages: int = 1) -> bytes:
    """A PDF whose pages are pictures and nothing else: what a photocopier makes."""
    images = [Image.new("RGB", (600, 800), (250, 250, 250)) for _ in range(pages)]
    out = io.BytesIO()
    images[0].save(out, format="PDF", save_all=True, append_images=images[1:])
    return out.getvalue()


def size_of(data: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(data)).size


def test_pictures_inside_a_word_file_are_pulled_out():
    found = extract("handout.docx", None, docx_with(png(300, 200)))
    assert "Photosynthesis needs light." in found.text
    [(media_type, data)] = found.images
    assert media_type in ("image/png", "image/jpeg") and size_of(data) == (300, 200)


def test_pictures_inside_slides_are_pulled_out():
    found = extract("deck.pptx", None, pptx_with(png(320, 240, (40, 40, 200))))
    [(media_type, data)] = found.images
    assert media_type in ("image/png", "image/jpeg") and size_of(data) == (320, 240)


def test_a_scanned_pdf_gives_its_pages_as_pictures_and_no_text():
    found = extract("scan.pdf", None, scanned_pdf(2))
    assert found.text == ""
    assert len(found.images) == 2
    assert all(size_of(d)[0] >= 500 for _, d in found.images)


def test_tiny_pictures_such_as_icons_and_bullets_are_left_out():
    found = extract("handout.docx", None, docx_with(png(24, 24)))
    assert found.images == ()


def test_a_long_document_keeps_at_most_six_pictures():
    found = extract("scan.pdf", None, scanned_pdf(9))
    assert len(found.images) == 6


async def test_a_photographed_worksheet_is_read_into_text_the_tutor_can_use(
    app, client, classroom, db
):
    """An uploaded picture has no text of its own: the model reads it once, on attach, and
    the words are kept as the material's text, so the tutor teaches from them."""
    from sqlalchemy import select

    await say(client, classroom, DESCRIBE)
    reader = llm.ScriptedClient(["The fog comes on little cat feet. It sits looking over harbor."])
    app.dependency_overrides[llm.get_llm_client] = lambda: reader
    attached = await client.post(
        "/api/teacher/thread/materials",
        files={"file": ("worksheet.png", png(640, 480), "image/png")},
        headers=classroom.headers(classroom.teacher),
    )
    assert attached.status_code == 201, attached.text
    [material] = (await db.scalars(select(Material))).all()
    assert material.extracted_text.startswith("The fog comes")
    assert reader.calls[-1]["purpose"] == "material_read"
    # The picture itself went to the reader, not a description of it.
    content = reader.calls[-1]["messages"][-1]["content"]
    assert any(part.get("type") == "image_url" for part in content)


async def test_a_scanned_pdf_is_read_page_by_page_and_its_pages_kept_as_pictures(
    app, client, classroom, db
):
    from sqlalchemy import select

    await say(client, classroom, DESCRIBE)
    reader = llm.ScriptedClient(["Page one: the water cycle.\n\nPage two: evaporation."])
    app.dependency_overrides[llm.get_llm_client] = lambda: reader
    attached = await client.post(
        "/api/teacher/thread/materials",
        files={"file": ("scan.pdf", scanned_pdf(2), "application/pdf")},
        headers=classroom.headers(classroom.teacher),
    )
    assert attached.status_code == 201, attached.text
    rows = (await db.scalars(select(Material).order_by(Material.created_at))).all()
    names = [m.filename for m in rows]
    assert names == ["scan.pdf", "scan.pdf (picture 1)", "scan.pdf (picture 2)"]
    assert rows[0].extracted_text.startswith("Page one")
    # The teacher's message carries every picture, so the drafting agent is shown them.
    event = attached.json()["messages"][-1]
    assert len(event["material_ids"]) == 3
    assert [m["filename"] for m in last_card(attached)["materials"]][0] == "scan.pdf"


async def test_a_typed_pdf_is_not_sent_to_the_reader(app, client, classroom, db):
    """Text that is already there costs nothing to keep; the model reads only what has none."""
    await say(client, classroom, DESCRIBE)
    reader = llm.ScriptedClient([])
    app.dependency_overrides[llm.get_llm_client] = lambda: reader
    attached = await client.post(
        "/api/teacher/thread/materials",
        files={"file": ("notes.docx", docx_with(png(300, 200)), DOCX)},
        headers=classroom.headers(classroom.teacher),
    )
    assert attached.status_code == 201, attached.text
    assert reader.calls == []


async def test_reading_a_picture_does_not_hold_a_database_connection(app, client, classroom, db):
    """The reader can take many seconds; a connection held through it is one the pupils'
    turns and the teacher's board wait for."""
    await say(client, classroom, DESCRIBE)
    held: list[bool] = []

    class Watching(llm.ScriptedClient):
        async def say(self, **kwargs):
            held.append(db.in_transaction())
            return await super().say(**kwargs)

    app.dependency_overrides[llm.get_llm_client] = lambda: Watching(["Fog."])
    attached = await client.post(
        "/api/teacher/thread/materials",
        files={"file": ("worksheet.png", png(640, 480), "image/png")},
        headers=classroom.headers(classroom.teacher),
    )
    assert attached.status_code == 201, attached.text
    assert held == [False]


async def test_a_picture_lands_on_the_lesson_named_or_a_new_one_and_never_anothers(
    app, client, classroom, db
):
    from sqlalchemy import select

    from app.models import LessonContract

    reader = llm.ScriptedClient(["Fog.", "Fog again."])
    app.dependency_overrides[llm.get_llm_client] = lambda: reader

    async def attach(who, **form):
        return await client.post(
            "/api/teacher/thread/materials",
            files={"file": ("worksheet.png", png(640, 480), "image/png")},
            data=form,
            headers=classroom.headers(who),
        )

    # Another teacher's lesson is refused before the model is asked to read anything.
    theirs = await attach(classroom.other_teacher, lesson_id=str(classroom.contract.id))
    assert theirs.status_code == 404 and reader.calls == []
    named = await attach(classroom.teacher, lesson_id=str(classroom.contract.id))
    assert named.status_code == 201, named.text
    # With nothing in focus, the picture starts a lesson of its own.
    fresh = await attach(classroom.other_teacher)
    assert fresh.status_code == 201, fresh.text
    landed = (
        await db.execute(
            select(Material.plan_id, LessonContract.teacher_id).join(
                LessonContract, LessonContract.plan_id == Material.plan_id
            )
        )
    ).all()
    assert {(classroom.contract.plan_id, classroom.teacher.id)} < set(landed)
    assert {teacher for _, teacher in landed} == {classroom.teacher.id, classroom.other_teacher.id}


async def test_when_the_reader_cannot_answer_the_upload_still_lands(app, client, classroom, db):
    from sqlalchemy import select

    await say(client, classroom, DESCRIBE)
    app.dependency_overrides[llm.get_llm_client] = lambda: llm.ScriptedClient([])
    attached = await client.post(
        "/api/teacher/thread/materials",
        files={"file": ("worksheet.png", png(640, 480), "image/png")},
        headers=classroom.headers(classroom.teacher),
    )
    assert attached.status_code == 201, attached.text
    [material] = (await db.scalars(select(Material))).all()
    assert material.extracted_text == "" and material.media_type == "image/png"


# ---------- files that will not read ----------


def test_a_broken_file_is_refused_in_plain_words():
    with pytest.raises(UnsupportedMaterial, match="Couldn't read notes.pdf"):
        extract("notes.pdf", None, b"%PDF-1.7 this is not really a pdf")


def test_a_picture_that_will_not_open_is_left_out():
    assert _worth_keeping(b"\x89PNG not an image" * (MIN_PICTURE_BYTES // 10)) is None


def test_a_pdf_page_whose_pictures_cannot_be_read_gives_none(monkeypatch):
    """One unreadable page, or one unreadable picture, costs only that page or that picture."""
    good = io.BytesIO()
    # Noise, so the picture is big enough to count as one worth teaching from.
    Image.effect_noise((300, 300), 64).convert("RGB").save(good, format="PNG")

    class Unreadable:
        @property
        def data(self):
            raise ValueError("damaged stream")

    class Readable:
        data = good.getvalue()

    class BrokenPage:
        @property
        def images(self):
            raise ValueError("damaged page")

    class Page:
        images = [Unreadable(), Readable()]

    class Reader:
        def __init__(self, _stream):
            self.pages = [BrokenPage(), Page()]

    monkeypatch.setattr(pypdf, "PdfReader", Reader)
    kept = materials._pdf_images(b"ignored")
    assert [kind for kind, _ in kept] == ["image/png"]


async def test_the_tutor_and_the_card_read_materials_without_their_files(db, classroom):
    """Every pupil turn reads the lesson's materials for their text; the file itself (up to
    10 MB a time) stays in the database unless something needs the bytes."""
    from sqlalchemy import inspect

    from app.agent.lessons import materials_of

    db.add(
        Material(
            plan_id=classroom.contract.plan_id,
            teacher_id=classroom.teacher.id,
            filename="notes.txt",
            media_type="text/plain",
            size_bytes=50_000,
            content=b"x" * 50_000,
            extracted_text="Solve each equation.",
        )
    )
    await db.commit()
    db.expunge_all()
    light = await materials_of(db, classroom.contract.plan_id, with_content=False)
    assert [m.extracted_text for m in light] == ["Solve each equation."]
    assert "content" in inspect(light[0]).unloaded
    db.expunge_all()
    full = await materials_of(db, classroom.contract.plan_id)
    assert full[0].content == b"x" * 50_000
