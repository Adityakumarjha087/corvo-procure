"""Database models (SQLAlchemy 2.0). SQLite by default, Postgres via DATABASE_URL."""
from __future__ import annotations

import os
from datetime import date, datetime, timezone

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./cantill.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Item(Base):
    __tablename__ = "items"
    item_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    description: Mapped[str] = mapped_column(String(255))
    uom: Mapped[str] = mapped_column(String(16))
    category: Mapped[str] = mapped_column(String(64))
    item_type: Mapped[str] = mapped_column(String(32))
    standard_price: Mapped[float] = mapped_column(Float)


class Supplier(Base):
    __tablename__ = "suppliers"
    supplier_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    city: Mapped[str] = mapped_column(String(64), default="")
    categories: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(16))
    on_time_pct: Mapped[float] = mapped_column(Float)
    quality_rating: Mapped[float] = mapped_column(Float)


class Plant(Base):
    __tablename__ = "plants"
    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), default="")


class PoHistory(Base):
    __tablename__ = "po_history"
    po_number: Mapped[str] = mapped_column(String(32), primary_key=True)
    po_date: Mapped[date] = mapped_column(Date, index=True)
    supplier_id: Mapped[str] = mapped_column(String(16), index=True)
    item_code: Mapped[str] = mapped_column(String(32), index=True)
    quantity: Mapped[float] = mapped_column(Float)
    uom: Mapped[str] = mapped_column(String(16))
    unit_price: Mapped[float] = mapped_column(Float)
    plant: Mapped[str] = mapped_column(String(16))
    delivered_on_time: Mapped[bool] = mapped_column(Boolean)


class Contract(Base):
    __tablename__ = "contracts"
    contract_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    supplier_id: Mapped[str] = mapped_column(String(16))
    supplier_name: Mapped[str] = mapped_column(String(128), default="")
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    value_cap: Mapped[float] = mapped_column(Float)
    consumed_value: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[str] = mapped_column(String(16), default="register")
    created_by: Mapped[str] = mapped_column(String(64), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    lines: Mapped[list["ContractLine"]] = relationship(back_populates="contract", cascade="all, delete-orphan", lazy="selectin")


class ContractLine(Base):
    __tablename__ = "contract_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contract_id: Mapped[str] = mapped_column(ForeignKey("contracts.contract_id", ondelete="CASCADE"), index=True)
    item_code: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(String(255), default="")
    uom: Mapped[str] = mapped_column(String(16), default="")
    rate: Mapped[float] = mapped_column(Float)
    contract: Mapped[Contract] = relationship(back_populates="lines")


class PolicyVersion(Base):
    __tablename__ = "policy_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[str] = mapped_column(String(32), index=True)
    effective_from: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft | approved | rejected
    document: Mapped[dict] = mapped_column(JSON)
    base_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    changes: Mapped[list] = mapped_column(JSON, default=list)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    ai_notes: Mapped[str] = mapped_column(Text, default="")
    source_name: Mapped[str] = mapped_column(String(255), default="")
    source_text: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(64), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    decided_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decision_comment: Mapped[str] = mapped_column(Text, default="")


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(16), default="upload")  # upload | api | inbox
    mode: Mapped[str] = mapped_column(String(16), default="by_date")
    created_by: Mapped[str] = mapped_column(String(64), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    policy_versions: Mapped[list] = mapped_column(JSON, default=list)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    rows: Mapped[list] = mapped_column(JSON, default=list)
    requirements: Mapped[list] = mapped_column(JSON, default=list)
    purchase_orders: Mapped[list] = mapped_column(JSON, default=list)
    input_csv: Mapped[str] = mapped_column(Text, default="")


class Action(Base):
    __tablename__ = "actions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    target: Mapped[str] = mapped_column(String(32))  # PO-0003 or REQ-0012
    kind: Mapped[str] = mapped_column(String(16))  # approve | override | reject
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    comment: Mapped[str] = mapped_column(Text, default="")
    actor: Mapped[str] = mapped_column(String(64))
    at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Document(Base):
    """A purchase order or sourcing event created when a buyer approves."""

    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_no: Mapped[str] = mapped_column(String(32), unique=True)
    kind: Mapped[str] = mapped_column(String(32))  # PO | RFQ | RFP | CAPEX_SOURCING | NEW_ITEM_SOURCING
    run_id: Mapped[int] = mapped_column(Integer, index=True)
    target: Mapped[str] = mapped_column(String(32))
    route: Mapped[str] = mapped_column(String(32))
    supplier_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    plant: Mapped[str] = mapped_column(String(16), default="")
    value: Mapped[float] = mapped_column(Float, default=0.0)
    body: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class PRInbox(Base):
    __tablename__ = "pr_inbox"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pr_no: Mapped[str] = mapped_column(String(32), index=True)
    pr_line: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    requester: Mapped[str] = mapped_column(String(64), default="")
    department: Mapped[str] = mapped_column(String(64), default="")
    plant: Mapped[str] = mapped_column(String(16))
    item_code: Mapped[str] = mapped_column(String(32), default="")
    description: Mapped[str] = mapped_column(String(255))
    quantity: Mapped[float] = mapped_column(Float)
    uom: Mapped[str] = mapped_column(String(16), default="")
    estimated_unit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    need_by_date: Mapped[date] = mapped_column(Date)
    urgency: Mapped[str] = mapped_column(String(16), default="Normal")
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | processed
    chat_session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user: Mapped[str] = mapped_column(String(64), default="")
    messages: Mapped[list] = mapped_column(JSON, default=list)
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Audit(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    entity: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[str] = mapped_column(String(64))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


def init_db() -> None:
    Base.metadata.create_all(engine)


def audit(db, actor: str, action: str, entity: str, entity_id, detail: dict | None = None) -> None:
    db.add(Audit(actor=actor or "anonymous", action=action, entity=entity, entity_id=str(entity_id), detail=detail or {}))
