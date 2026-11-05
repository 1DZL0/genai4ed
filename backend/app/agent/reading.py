"""Reading a picture into words: a photographed worksheet, the pages of a scanned PDF. The
model is asked once, when the file is attached, and what it reads is kept as the material's
text, so both agents get the words on every turn after that without seeing the picture."""

from app.agent.llm import LLMClient, LLMError, image_part
from app.log import MODEL

SYSTEM = (
    "You are reading teaching material for a teacher. Write out every word on these pages "
    "exactly as it appears, in reading order, keeping headings, numbering and line breaks. "
    "Where there is a diagram, table or picture, describe it in one plain sentence in square "
    "brackets. Write nothing else: no commentary, no answers to the questions on the page."
)
MAX_TOKENS = 4_000


async def read_pictures(
    client: LLMClient, pictures: list[tuple[str, bytes]], *, filename: str
) -> str:
    """The words on these pictures, or an empty string when the model could not be asked."""
    if not pictures:
        return ""
    try:
        result = await client.say(
            purpose="material_read",
            system=SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"The file is called {filename}. Read every page below.",
                        },
                        *[image_part(media_type, data) for media_type, data in pictures],
                    ],
                }
            ],
            max_tokens=MAX_TOKENS,
        )
    except LLMError as exc:
        MODEL.warning("material_read failed for %s: %s", filename, exc)
        return ""
    return (result.raw or "").strip()
