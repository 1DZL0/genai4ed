"""The schema in one view: every table, its columns and keys, and what each field holds.

    docker exec genai4ed-api .venv/bin/python -m app.schema          # plain text
    docker exec genai4ed-api .venv/bin/python -m app.schema --md     # Markdown, for docs/schema.md

Built from the ORM models, so it cannot drift from the code. The line beside each table is
the model's docstring; the note beside a column is the comment above it in models.py. Row
counts come from the database when it can be reached, and are left out when it cannot.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import re
import sys
from dataclasses import dataclass

from sqlalchemy import CheckConstraint, Column, Table, UniqueConstraint, func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.db import Base, get_sessionmaker

# `_check()` in models.py writes every enum constraint as: column in ('a', 'b', 'c')
_ENUM_CHECK = re.compile(r"^(\w+) in \((.*)\)$")
_CLASS_LINE = re.compile(r"^class (\w+)\(")
_COMMENT_LINE = re.compile(r"^    # ?(.*)$")
_COLUMN_LINE = re.compile(r"^    (\w+): Mapped\[")
_TYPE_NAMES = {"timestamp with time zone": "timestamptz", "character varying": "varchar"}


@dataclass(frozen=True)
class ColumnView:
    name: str
    type: str  # "varchar(64)", with "?" appended when the column may be empty
    keys: str  # "PK", "-> users.id", "unique", "one of: a, b", joined by ", "
    note: str  # the comment above the column in models.py, or ""


@dataclass(frozen=True)
class TableView:
    name: str
    purpose: str  # the model's docstring, or ""
    columns: list[ColumnView]
    unique_together: list[str]  # "(class_id, student_id)" for each multi-column unique constraint


def _notes_from_source() -> dict[str, dict[str, str]]:
    """{class name: {column name: the comment written above it}}, read from models.py."""
    notes: dict[str, dict[str, str]] = {}
    current = ""
    pending: list[str] = []
    for line in inspect.getsource(models).splitlines():
        if m := _CLASS_LINE.match(line):
            current, pending = m.group(1), []
        elif m := _COMMENT_LINE.match(line):
            pending.append(m.group(1).strip())
        elif m := _COLUMN_LINE.match(line):
            if pending:
                notes.setdefault(current, {})[m.group(1)] = " ".join(pending)
            pending = []
        else:
            pending = []
    return notes


def _purposes() -> dict[str, tuple[str, str]]:
    """{table name: (class name, docstring on one line)} for every mapped model."""
    out: dict[str, tuple[str, str]] = {}
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        out[cls.__tablename__] = (cls.__name__, " ".join((cls.__doc__ or "").split()))
    return out


def _type_name(column: Column) -> str:
    name = column.type.compile(dialect=postgresql.dialect()).lower()
    for long, short in _TYPE_NAMES.items():
        name = name.replace(long, short)
    return name


def _enum_values(table: Table) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    for constraint in table.constraints:
        if isinstance(constraint, CheckConstraint):
            if m := _ENUM_CHECK.match(str(constraint.sqltext)):
                values[m.group(1)] = [v.strip().strip("'") for v in m.group(2).split(",")]
    return values


def _unique(table: Table) -> tuple[set[str], list[str]]:
    """Columns unique on their own, and the multi-column unique constraints."""
    single = {c.name for c in table.columns if c.unique}
    together: list[str] = []
    for constraint in table.constraints:
        if isinstance(constraint, UniqueConstraint):
            names = [c.name for c in constraint.columns]
            if len(names) == 1:
                single.add(names[0])
            else:
                together.append("(" + ", ".join(names) + ")")
    return single, sorted(together)


def _keys(column: Column, single_unique: set[str], enum_values: dict[str, list[str]]) -> str:
    parts: list[str] = []
    if column.primary_key:
        parts.append("PK")
    for fk in column.foreign_keys:
        parts.append(f"-> {fk.column.table.name}.{fk.column.name}")
    if column.name in single_unique:
        parts.append("unique")
    if column.name in enum_values:
        parts.append("one of: " + ", ".join(enum_values[column.name]))
    return ", ".join(parts)


def table_views() -> list[TableView]:
    """Every table in dependency order (users first), as the ORM declares it."""
    notes = _notes_from_source()
    purposes = _purposes()
    views: list[TableView] = []
    for table in Base.metadata.sorted_tables:
        class_name, purpose = purposes.get(table.name, ("", ""))
        enum_values = _enum_values(table)
        single_unique, together = _unique(table)
        columns = [
            ColumnView(
                name=c.name,
                type=_type_name(c) + ("?" if c.nullable else ""),
                keys=_keys(c, single_unique, enum_values),
                note=notes.get(class_name, {}).get(c.name, ""),
            )
            for c in table.columns
        ]
        views.append(TableView(table.name, purpose, columns, together))
    return views


def _summary(views: list[TableView], counts: dict[str, int] | None) -> str:
    text = f"GenAI4ED schema: {len(views)} tables"
    if counts is not None:
        text += f", {sum(counts.values())} rows in all"
    return text + "."


def _heading(view: TableView, counts: dict[str, int] | None) -> str:
    if counts is None:
        return view.name
    return f"{view.name} ({counts.get(view.name, 0)} rows)"


def render_text(counts: dict[str, int] | None) -> str:
    views = table_views()
    name_w = max(len(c.name) for v in views for c in v.columns)
    type_w = max(len(c.type) for v in views for c in v.columns)
    lines = [
        _summary(views, counts),
        "A ? after a type means the column may be empty. Notes are the comments in models.py.",
    ]
    for v in views:
        lines.append("")
        lines.append(_heading(v, counts) + (f"  {v.purpose}" if v.purpose else ""))
        for c in v.columns:
            tail = "  ".join(part for part in (c.keys, c.note) if part)
            lines.append(f"  {c.name:<{name_w}}  {c.type:<{type_w}}  {tail}".rstrip())
        for u in v.unique_together:
            lines.append(f"  unique together {u}")
    return "\n".join(lines) + "\n"


def render_markdown(counts: dict[str, int] | None) -> str:
    views = table_views()
    lines = [
        "# GenAI4ED schema",
        "",
        "Generated by `python -m app.schema --md` from the ORM models; change models.py, "
        "not this file.",
        "",
        _summary(views, counts) + " A `?` after a type means the column may be empty. "
        "Notes are the comments in models.py.",
        "",
        "Tables: " + ", ".join(f"`{v.name}`" for v in views) + ".",
    ]
    for v in views:
        lines += ["", f"## {_heading(v, counts)}", ""]
        if v.purpose:
            lines += [v.purpose, ""]
        lines += ["| Column | Type | Keys | Holds |", "|---|---|---|---|"]
        for c in v.columns:
            note = c.note.replace("|", "\\|")
            lines.append(f"| {c.name} | {c.type} | {c.keys} | {note} |")
        for u in v.unique_together:
            lines += ["", f"Unique together: {u}."]
    return "\n".join(lines) + "\n"


async def row_counts(db: AsyncSession) -> dict[str, int]:
    """Exact row count of every table."""
    counts: dict[str, int] = {}
    for table in Base.metadata.sorted_tables:
        result = await db.execute(select(func.count()).select_from(table))
        counts[table.name] = result.scalar_one()
    return counts


async def _counts_or_none() -> dict[str, int] | None:
    try:
        async with get_sessionmaker()() as db:
            return await row_counts(db)
    except Exception as exc:  # whatever stops us reaching the database, the structure prints
        print(f"database not reached ({type(exc).__name__}); row counts left out", file=sys.stderr)
        return None


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m app.schema",
        description="Every table, column and key, with what each field holds.",
    )
    parser.add_argument("--md", action="store_true", help="Markdown instead of plain text")
    parser.add_argument(
        "--no-counts", action="store_true", help="do not touch the database; structure only"
    )
    args = parser.parse_args(argv)
    counts = None if args.no_counts else asyncio.run(_counts_or_none())
    sys.stdout.write(render_markdown(counts) if args.md else render_text(counts))


if __name__ == "__main__":
    main()
