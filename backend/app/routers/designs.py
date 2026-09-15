"""Designing a lesson with the class agent.

The teacher talks; the agent keeps the lesson brief up to date. Approving a
version makes it teachable. Talking about an approved lesson opens its next
draft version, so lessons already taught keep exactly what they were taught
with.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update

from app.agent import store
from app.agent.brief import LessonBrief
from app.agent.llm import LLMClient, get_llm_client
from app.agent.materials import UnsupportedMaterial, extract
from app.agent.teacher_mode import DesignUnavailable, design_turn
from app.auth import CurrentTeacher, DbSession
from app.config import get_settings
from app.enums import ContractStatus, ExceptionStatus, MessageRole, SessionStatus
from app.models import (
    Class,
    Exception_,
    LessonContract,
    Material,
    Session,
)

router = APIRouter(prefix="/api/teacher/designs", tags=["designs"])

Agent = Annotated[LLMClient, Depends(get_llm_client)]


class StartIn(BaseModel):
    text: str = Field(default="", max_length=6000)


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=6000)
    material_ids: list[uuid.UUID] = Field(default_factory=list, max_length=10)


class MaterialOut(BaseModel):
    id: uuid.UUID
    filename: str
    media_type: str
    size_bytes: int
    readable: bool


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    text: str
    data: dict
    material_ids: list[str]
    created_at: datetime


class LessonRun(BaseModel):
    lesson_id: uuid.UUID
    class_label: str
    status: str
    opened_at: datetime | None
    closed_at: datetime | None
    open_alerts: int


class DesignOut(BaseModel):
    id: uuid.UUID
    plan_id: uuid.UUID
    version: int
    status: str
    title: str
    subject: str
    brief: LessonBrief
    rules_in_words: list[str]
    missing: list[str]
    approved_version_id: uuid.UUID | None
    materials: list[MaterialOut]
    messages: list[MessageOut]
    runs: list[LessonRun]


class DesignCard(BaseModel):
    id: uuid.UUID
    plan_id: uuid.UUID
    version: int
    status: str
    title: str
    subject: str
    duration_minutes: int
    steps: int
    objectives: list[str]
    approved_version_id: uuid.UUID | None
    live: LessonRun | None
    last_run: LessonRun | None
    updated_at: datetime


# ---------- helpers ----------


async def _owned(design_id: uuid.UUID, teacher, db) -> LessonContract:
    contract = await db.get(LessonContract, design_id)
    if contract is None or contract.teacher_id != teacher.id or contract.archived_at is not None:
        raise HTTPException(status_code=404, detail="Lesson not found.")
    return contract


async def _versions(db, plan_id: uuid.UUID) -> list[LessonContract]:
    return list(
        (
            await db.scalars(
                select(LessonContract)
                .where(LessonContract.plan_id == plan_id)
                .order_by(LessonContract.version)
            )
        ).all()
    )


async def _runs(db, plan_id: uuid.UUID) -> list[LessonRun]:
    rows = (
        await db.execute(
            select(Session, Class)
            .join(LessonContract, LessonContract.id == Session.contract_id)
            .join(Class, Class.id == Session.class_id)
            .where(LessonContract.plan_id == plan_id)
            .order_by(Session.created_at.desc())
        )
    ).all()
    runs = []
    for session, klass in rows:
        alerts = await db.scalar(
            select(func.count(Exception_.id)).where(
                Exception_.session_id == session.id,
                Exception_.status == ExceptionStatus.OPEN.value,
            )
        )
        runs.append(
            LessonRun(
                lesson_id=session.id,
                class_label=klass.label,
                status=session.status,
                opened_at=session.opened_at,
                closed_at=session.closed_at,
                open_alerts=alerts or 0,
            )
        )
    return runs


async def _out(db, contract: LessonContract) -> DesignOut:
    brief = LessonBrief.model_validate(contract.brief or {})
    versions = await _versions(db, contract.plan_id)
    approved = next(
        (v for v in reversed(versions) if v.status == ContractStatus.ACTIVE.value), None
    )
    materials = (
        await db.scalars(
            select(Material)
            .where(Material.plan_id == contract.plan_id)
            .order_by(Material.created_at)
        )
    ).all()
    conversation = await store.design_conversation(
        db, teacher_id=contract.teacher_id, plan_id=contract.plan_id
    )
    messages = await store.messages(db, conversation.id)
    return DesignOut(
        id=contract.id,
        plan_id=contract.plan_id,
        version=contract.version,
        status=contract.status,
        title=contract.title,
        subject=contract.subject,
        brief=brief,
        rules_in_words=brief.rules.describe(),
        missing=brief.missing(),
        approved_version_id=approved.id if approved else None,
        materials=[
            MaterialOut(
                id=m.id,
                filename=m.filename,
                media_type=m.media_type,
                size_bytes=m.size_bytes,
                readable=bool(m.extracted_text) or m.media_type.startswith("image/"),
            )
            for m in materials
        ],
        messages=[
            MessageOut(
                id=m.id,
                role=m.role,
                text=m.text,
                data=m.data,
                material_ids=[str(i) for i in m.material_ids],
                created_at=m.created_at,
            )
            for m in messages
            if m.role in (MessageRole.TEACHER.value, MessageRole.AGENT.value)
        ],
        runs=await _runs(db, contract.plan_id),
    )


async def _draft_to_work_on(db, contract: LessonContract) -> LessonContract:
    """The version the teacher's next words change: this one if it's a draft,
    otherwise the plan's open draft, opened now if there isn't one."""
    if contract.status == ContractStatus.DRAFT.value:
        return contract
    versions = await _versions(db, contract.plan_id)
    open_draft = next((v for v in versions if v.status == ContractStatus.DRAFT.value), None)
    if open_draft is not None:
        return open_draft
    draft = LessonContract(
        plan_id=contract.plan_id,
        teacher_id=contract.teacher_id,
        title=contract.title,
        subject=contract.subject,
        status=ContractStatus.DRAFT.value,
        version=versions[-1].version + 1,
        assistance_ladder={},
        exception_thresholds={},
        material={},
        timeline=[],
        brief=dict(contract.brief or {}),
        use_past_lessons=contract.use_past_lessons,
    )
    db.add(draft)
    await db.flush()
    return draft


# ---------- endpoints ----------


@router.get("", response_model=list[DesignCard])
async def list_designs(teacher: CurrentTeacher, db: DbSession) -> list[DesignCard]:
    """Every lesson the teacher has, newest version of each, newest first."""
    rows = (
        await db.scalars(
            select(LessonContract)
            .where(
                LessonContract.teacher_id == teacher.id,
                LessonContract.archived_at.is_(None),
            )
            .order_by(LessonContract.plan_id, LessonContract.version.desc())
        )
    ).all()
    latest: dict[uuid.UUID, LessonContract] = {}
    approved: dict[uuid.UUID, LessonContract] = {}
    for c in rows:
        latest.setdefault(c.plan_id, c)
        if c.status == ContractStatus.ACTIVE.value:
            approved.setdefault(c.plan_id, c)

    cards = []
    for plan_id, c in latest.items():
        brief = LessonBrief.model_validate(c.brief or {})
        runs = await _runs(db, plan_id)
        live = next(
            (r for r in runs if r.status in (SessionStatus.OPEN.value, SessionStatus.PAUSED.value)),
            None,
        )
        last = next((r for r in runs if r.status == SessionStatus.CLOSED.value), None)
        cards.append(
            DesignCard(
                id=c.id,
                plan_id=plan_id,
                version=c.version,
                status=c.status,
                title=c.title,
                subject=c.subject,
                duration_minutes=brief.duration_minutes,
                steps=len(brief.steps),
                objectives=brief.objectives,
                approved_version_id=approved[plan_id].id if plan_id in approved else None,
                live=live,
                last_run=last,
                updated_at=c.created_at,
            )
        )
    cards.sort(key=lambda card: (card.live is None, -card.updated_at.timestamp()))
    return cards


@router.post("", response_model=DesignOut, status_code=status.HTTP_201_CREATED)
async def start_design(
    body: StartIn, teacher: CurrentTeacher, db: DbSession, agent: Agent
) -> DesignOut:
    """A new lesson. With `text`, the agent drafts it straight away."""
    contract = LessonContract(
        plan_id=uuid.uuid4(),
        teacher_id=teacher.id,
        title="New lesson",
        subject="",
        status=ContractStatus.DRAFT.value,
        version=1,
        assistance_ladder={},
        exception_thresholds={},
        material={},
        timeline=[],
        brief={},
    )
    db.add(contract)
    await db.flush()
    await store.design_conversation(db, teacher_id=teacher.id, plan_id=contract.plan_id)
    await db.commit()
    if body.text.strip():
        try:
            await design_turn(
                db,
                agent,
                contract=contract,
                teacher=teacher,
                text=body.text.strip(),
                material_ids=[],
            )
        except DesignUnavailable as exc:
            raise HTTPException(status_code=503, detail=_unavailable(exc)) from exc
    return await _out(db, contract)


@router.get("/{design_id}", response_model=DesignOut)
async def read_design(design_id: uuid.UUID, teacher: CurrentTeacher, db: DbSession) -> DesignOut:
    return await _out(db, await _owned(design_id, teacher, db))


@router.post("/{design_id}/messages", response_model=DesignOut)
async def talk(
    design_id: uuid.UUID, body: MessageIn, teacher: CurrentTeacher, db: DbSession, agent: Agent
) -> DesignOut:
    """Say something to the agent about this lesson. Returns the version it changed,
    which is a new draft when the lesson was already approved."""
    contract = await _draft_to_work_on(db, await _owned(design_id, teacher, db))
    known = set(
        (
            await db.scalars(
                select(Material.id).where(
                    Material.plan_id == contract.plan_id, Material.id.in_(body.material_ids)
                )
            )
        ).all()
    )
    try:
        await design_turn(
            db,
            agent,
            contract=contract,
            teacher=teacher,
            text=body.text.strip(),
            material_ids=[m for m in body.material_ids if m in known],
        )
    except DesignUnavailable as exc:
        raise HTTPException(status_code=503, detail=_unavailable(exc)) from exc
    return await _out(db, contract)


def _unavailable(exc: Exception) -> str:
    return f"The agent couldn't answer just now. Your message is saved; try again. ({exc})"


@router.post("/{design_id}/materials", response_model=MaterialOut, status_code=201)
async def upload_material(
    design_id: uuid.UUID,
    teacher: CurrentTeacher,
    db: DbSession,
    file: Annotated[UploadFile, File()],
) -> MaterialOut:
    contract = await _owned(design_id, teacher, db)
    limit = get_settings().material_max_mb * 1024 * 1024
    content = await file.read(limit + 1)
    if len(content) > limit:
        raise HTTPException(
            status_code=413,
            detail=f"That file is over {get_settings().material_max_mb} MB.",
        )
    try:
        extracted = extract(file.filename or "upload", file.content_type, content)
    except UnsupportedMaterial as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    material = Material(
        teacher_id=teacher.id,
        plan_id=contract.plan_id,
        filename=(file.filename or "upload")[:255],
        media_type=extracted.media_type,
        size_bytes=len(content),
        content=content,
        extracted_text=extracted.text,
    )
    db.add(material)
    await db.commit()
    return MaterialOut(
        id=material.id,
        filename=material.filename,
        media_type=material.media_type,
        size_bytes=material.size_bytes,
        readable=bool(material.extracted_text) or extracted.is_image,
    )


@router.delete("/{design_id}/materials/{material_id}", status_code=204)
async def remove_material(
    design_id: uuid.UUID, material_id: uuid.UUID, teacher: CurrentTeacher, db: DbSession
) -> None:
    contract = await _owned(design_id, teacher, db)
    material = await db.get(Material, material_id)
    if material is None or material.plan_id != contract.plan_id:
        raise HTTPException(status_code=404, detail="Material not found.")
    await db.delete(material)
    await db.commit()


class SettingsIn(BaseModel):
    use_past_lessons: bool


@router.post("/{design_id}/settings", response_model=DesignOut)
async def change_settings(
    design_id: uuid.UUID, body: SettingsIn, teacher: CurrentTeacher, db: DbSession
) -> DesignOut:
    contract = await _draft_to_work_on(db, await _owned(design_id, teacher, db))
    contract.use_past_lessons = body.use_past_lessons
    await db.commit()
    return await _out(db, contract)


@router.post("/{design_id}/approve", response_model=DesignOut)
async def approve(design_id: uuid.UUID, teacher: CurrentTeacher, db: DbSession) -> DesignOut:
    """The teacher's approval, recorded against them and the moment. Only now
    does the agent teach from this brief."""
    contract = await _owned(design_id, teacher, db)
    if contract.status != ContractStatus.DRAFT.value:
        raise HTTPException(status_code=409, detail="This version is already approved.")
    brief = LessonBrief.model_validate(contract.brief or {})
    if brief.missing():
        raise HTTPException(
            status_code=422,
            detail="Before approving, the lesson needs " + ", ".join(brief.missing()) + ".",
        )
    await db.execute(
        update(LessonContract)
        .where(
            LessonContract.plan_id == contract.plan_id,
            LessonContract.id != contract.id,
            LessonContract.status == ContractStatus.ACTIVE.value,
        )
        .values(status=ContractStatus.CLOSED.value)
    )
    contract.status = ContractStatus.ACTIVE.value
    contract.activated_at = datetime.now(UTC)
    contract.activated_by = teacher.id
    contract.title = brief.title.strip()[:255] or contract.title
    contract.subject = brief.subject.strip()[:64] or contract.subject
    await db.commit()
    return await _out(db, contract)


@router.delete("/{design_id}", status_code=204)
async def delete_design(design_id: uuid.UUID, teacher: CurrentTeacher, db: DbSession) -> None:
    """A lesson never taught is deleted; one that has been taught is archived,
    so its lessons and students' work are kept."""
    contract = await _owned(design_id, teacher, db)
    versions = await _versions(db, contract.plan_id)
    taught = await db.scalar(
        select(func.count(Session.id)).where(Session.contract_id.in_([v.id for v in versions]))
    )
    if taught:
        now = datetime.now(UTC)
        for v in versions:
            v.archived_at = now
    else:
        for v in versions:
            await db.delete(v)
    await db.commit()
