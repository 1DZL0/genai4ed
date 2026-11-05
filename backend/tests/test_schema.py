"""The schema view: every table in one place, with what each field holds."""

from app.db import Base
from app.schema import render_markdown, render_text


def test_text_view_names_every_table_and_what_it_holds():
    out = render_text(counts=None)
    for table in Base.metadata.sorted_tables:
        assert f"\n{table.name}" in out
    # A table's purpose, from its docstring.
    assert "Append-only evidence ledger" in out
    # A column's note, from the comment above it in models.py.
    assert "The ids of exactly the records the agent was shown." in out
    # An enum check constraint, read back as its values.
    assert "one of: teacher, student" in out
    # A foreign key, pointing at what it references.
    assert "-> users.id" in out
    # A column that may be empty is marked.
    assert "varchar(254)?" in out


def test_markdown_view_has_a_section_per_table_and_shows_counts():
    out = render_markdown(counts={"users": 3})
    assert out.count("\n## ") == len(Base.metadata.tables)
    assert "## users (3 rows)" in out
    assert "| context_manifest | jsonb |" in out
