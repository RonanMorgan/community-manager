from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from backend.models import Category, ResourceStatus, ToolName


class GroupResourceOut(BaseModel):
    id: str
    tool: ToolName
    external_id: str | None
    display_name: str
    status: ResourceStatus

    model_config = ConfigDict(from_attributes=True)


class GroupOut(BaseModel):
    id: str
    name: str
    category: Category | None
    created_by: str
    created_at: datetime
    resources: list[GroupResourceOut]

    model_config = ConfigDict(from_attributes=True)


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    # Which tools to provision a resource for. Outline + Mattermost are checked
    # by default in the UI; only "outline" is actually wired up in V0.
    tools: list[ToolName] = Field(default_factory=lambda: [ToolName.OUTLINE])


class GroupCategoryUpdate(BaseModel):
    category: Category


class ResourceRename(BaseModel):
    display_name: str = Field(min_length=1, max_length=255)


class ResourceUser(BaseModel):
    """A user's membership + rights for a given resource, as reported LIVE by
    the underlying tool (never stored in our DB)."""

    id: str
    name: str
    email: str | None
    permission: str  # e.g. "read" / "read_write" for Outline


class AddUserRequest(BaseModel):
    email: EmailStr
    permission: str = Field(default="read", pattern="^(read|read_write)$")


class SyncResult(BaseModel):
    groups_created: int = 0
    groups_updated: int = 0
    groups_deleted: int = 0
    resources_matched: int = 0
    resources_not_found: int = 0
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
