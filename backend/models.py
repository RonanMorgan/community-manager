"""
ORM models.

See CLAUDE.md for the rationale behind this schema. In short:
- `Group` / `GroupResource` are the only application-owned data: the mapping
  between a logical group and the real resource (e.g. an Outline collection)
  that represents it in each connected tool.
- There is intentionally NO `User` / `Membership` table: who belongs to a
  resource, and with what permission, is always fetched live from the tool's
  own API (Outline is the source of truth for its own memberships). See
  backend/outline_service.py.
- `AuditLog` records admin actions (group/resource created, renamed, user
  added/removed) for traceability.
"""
import enum
import uuid

from sqlalchemy import DateTime, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class ToolName(str, enum.Enum):
    """Supported tools. Only OUTLINE is wired up in V0; the others are
    reserved so `GroupResource.tool` doesn't need a migration to add them."""

    OUTLINE = "outline"
    MATTERMOST = "mattermost"
    BREVO = "brevo"
    VAULTWARDEN = "vaultwarden"


class ResourceStatus(str, enum.Enum):
    PENDING = "pending"  # row created, resource not provisioned in the tool yet
    ACTIVE = "active"  # resource exists and is in sync
    ERROR = "error"  # last provisioning/rename attempt failed
    NOT_FOUND = "not_found"  # synced from Authentik, but no matching resource found in the tool by name


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    # Set when this Group was created (or matched) from an Authentik group during
    # a synchronization run. NULL for groups created manually before Authentik
    # sync existed, or if Authentik sync is never used. See CLAUDE.md §4-bis.
    authentik_group_id: Mapped[str | None] = mapped_column(String, nullable=True, unique=True, index=True)
    created_by: Mapped[str] = mapped_column(String, nullable=False)  # admin email from OIDC claim (no Users table)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[object] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    resources: Mapped[list["GroupResource"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )


class GroupResource(Base):
    """One row per (group, tool): the concrete resource representing that
    group in that tool, e.g. an Outline collection."""

    __tablename__ = "group_resources"
    __table_args__ = (UniqueConstraint("group_id", "tool", name="uq_group_resource_group_tool"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id"), nullable=False)
    tool: Mapped[ToolName] = mapped_column(Enum(ToolName), nullable=False)

    external_id: Mapped[str | None] = mapped_column(String, nullable=True)  # e.g. Outline collection id
    display_name: Mapped[str] = mapped_column(String, nullable=False)  # editable, shown in the groups table
    status: Mapped[ResourceStatus] = mapped_column(Enum(ResourceStatus), default=ResourceStatus.PENDING)

    last_synced_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[object] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    group: Mapped["Group"] = relationship(back_populates="resources")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    actor_email: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)  # e.g. "group.created", "resource.renamed"
    group_id: Mapped[str | None] = mapped_column(String, nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String, nullable=True)
    details: Mapped[str | None] = mapped_column(String, nullable=True)  # free-form human-readable summary
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())
