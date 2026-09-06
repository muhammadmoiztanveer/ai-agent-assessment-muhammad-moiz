"""SQLAlchemy ORM models for the persistence layer.

Four entities model the pipeline domain and mirror the API contracts:

    Profile 1──* Run 1──* Query 1──* Recommendation

Design notes:
- UUID string primary keys (``uuid4().hex``-style) keep IDs opaque and URL-safe.
- Enums are stored as portable ``VARCHAR`` (``native_enum=False``) so the same
  schema works on SQLite and Postgres without custom types.
- List/dict fields (competitors, insights, reports, keywords) use the JSON column
  type, which SQLite and Postgres both support.
- Timestamps are timezone-aware UTC ``datetime`` values, defaulted at insert time.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON as SAJSON,
)
from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    """Generate a compact, URL-safe UUID4 hex string."""
    return uuid.uuid4().hex


def _utcnow() -> datetime:
    """Current timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


# --------------------------------------------------------------------------- #
# Enumerations (stored as VARCHAR for cross-dialect portability)
# --------------------------------------------------------------------------- #
class RunStatus(enum.StrEnum):
    """Lifecycle status of a pipeline run."""

    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class VisibilityStatus(enum.StrEnum):
    """Whether the brand domain is visible for a discovered query."""

    VISIBLE = "visible"
    NOT_VISIBLE = "not_visible"
    UNKNOWN = "unknown"


class ContentType(enum.StrEnum):
    """Type of content a recommendation proposes."""

    BLOG_POST = "blog_post"
    LANDING_PAGE = "landing_page"
    FAQ = "faq"


class Priority(enum.StrEnum):
    """Recommendation priority."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


def _enum_col(enum_cls: type[enum.StrEnum]) -> Enum:
    """Build a portable, string-backed Enum column for a StrEnum."""
    return Enum(
        enum_cls,
        native_enum=False,
        values_callable=lambda e: [member.value for member in e],
        length=32,
    )


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class Profile(Base):
    """A brand/keyword profile — the subject of search-visibility analysis."""

    __tablename__ = "profiles"

    profile_uuid: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    industry: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    competitors: Mapped[list[str]] = mapped_column(SAJSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    runs: Mapped[list[Run]] = relationship(
        back_populates="profile",
        cascade="all, delete-orphan",
        order_by="Run.started_at",
    )


class Run(Base):
    """A single execution of the LangGraph pipeline for a profile."""

    __tablename__ = "runs"

    run_uuid: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    profile_uuid: Mapped[str] = mapped_column(
        ForeignKey("profiles.profile_uuid", ondelete="CASCADE"), index=True, nullable=False
    )
    status: Mapped[RunStatus] = mapped_column(
        _enum_col(RunStatus), default=RunStatus.RUNNING, nullable=False
    )
    planned_retrieval_calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    extracted_records: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    top_insights: Mapped[list[dict[str, Any]]] = mapped_column(SAJSON, default=list, nullable=False)
    report_json: Mapped[dict[str, Any]] = mapped_column(SAJSON, default=dict, nullable=False)
    report_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    error_flag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    error_detail: Mapped[dict[str, Any] | None] = mapped_column(SAJSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    profile: Mapped[Profile] = relationship(back_populates="runs")
    queries: Mapped[list[Query]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="Query.opportunity_score.desc()",
    )
    recommendations: Mapped[list[Recommendation]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )


class Query(Base):
    """A discovered sub-query (keyword) with metrics and visibility for a run."""

    __tablename__ = "queries"

    query_uuid: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    run_uuid: Mapped[str] = mapped_column(
        ForeignKey("runs.run_uuid", ondelete="CASCADE"), index=True, nullable=False
    )
    # Denormalized for fast per-profile filtering without a join.
    profile_uuid: Mapped[str] = mapped_column(
        ForeignKey("profiles.profile_uuid", ondelete="CASCADE"), index=True, nullable=False
    )
    query_text: Mapped[str] = mapped_column(String(512), nullable=False)
    estimated_search_volume: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    competitive_difficulty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    opportunity_score: Mapped[float] = mapped_column(Float, default=0.0, index=True, nullable=False)
    domain_visible: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    visibility_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    visibility_status: Mapped[VisibilityStatus] = mapped_column(
        _enum_col(VisibilityStatus), default=VisibilityStatus.UNKNOWN, nullable=False
    )
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    run: Mapped[Run] = relationship(back_populates="queries")
    recommendations: Mapped[list[Recommendation]] = relationship(
        back_populates="target_query",
        cascade="all, delete-orphan",
    )


class Recommendation(Base):
    """A content recommendation targeting a specific discovered query."""

    __tablename__ = "recommendations"

    recommendation_uuid: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    run_uuid: Mapped[str] = mapped_column(
        ForeignKey("runs.run_uuid", ondelete="CASCADE"), index=True, nullable=False
    )
    target_query_uuid: Mapped[str] = mapped_column(
        ForeignKey("queries.query_uuid", ondelete="CASCADE"), index=True, nullable=False
    )
    content_type: Mapped[ContentType] = mapped_column(_enum_col(ContentType), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    target_keywords: Mapped[list[str]] = mapped_column(SAJSON, default=list, nullable=False)
    priority: Mapped[Priority] = mapped_column(
        _enum_col(Priority), default=Priority.MEDIUM, nullable=False
    )

    run: Mapped[Run] = relationship(back_populates="recommendations")
    target_query: Mapped[Query] = relationship(back_populates="recommendations")
