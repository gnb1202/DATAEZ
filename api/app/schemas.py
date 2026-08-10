"""Pydantic request/response models for type-safe API contracts."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------

class StatusResponse(BaseModel):
    status: str = "ok"


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class SignupRequest(BaseModel):
    email: str
    password: str
    name: str = ""


class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class AuthTokenResponse(BaseModel):
    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"


class UserResponse(BaseModel):
    user_id: str
    email: str


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

class CreateProjectRequest(BaseModel):
    name: str
    description: str = ""


class UpdateProjectRequest(BaseModel):
    name: str | None = None
    description: str | None = None


class ProjectResponse(BaseModel):
    id: str
    name: str
    description: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    table_count: int = 0
    user_id: str | None = None

    model_config = {"from_attributes": True}


class ProjectListResponse(BaseModel):
    projects: list[ProjectResponse]
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

class ColumnSchema(BaseModel):
    name: str
    type: str
    nullable: bool = True


class CreateTableRequest(BaseModel):
    name: str
    description: str = ""
    columns: list[dict[str, Any]] = []


class UpdateTableRequest(BaseModel):
    name: str | None = None
    description: str | None = None


class TableMetaResponse(BaseModel):
    id: str
    project_id: str
    name: str
    description: str = ""
    columns_schema: list[dict[str, Any]] = []
    row_count: int = 0
    source_file_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class TableListResponse(BaseModel):
    tables: list[TableMetaResponse]


class TableDataResponse(BaseModel):
    columns: list[dict[str, Any]]
    rows: list[dict[str, Any]]
    total_count: int
    limit: int
    offset: int


class AppendResponse(BaseModel):
    rows_inserted: int
    total_row_count: int


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

class FileResponse(BaseModel):
    file_id: str
    filename: str
    size: int | None = None
    size_bytes: int | None = None
    storage_key: str | None = None
    created_at: str | None = None


class FileListResponse(BaseModel):
    files: list[FileResponse]


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------

class CreateConversationRequest(BaseModel):
    project_id: str
    table_id: str | None = None
    title: str = ""


class ConversationResponse(BaseModel):
    conversation_id: str
    project_id: str | None = None
    table_id: str | None = None
    file_id: str | None = None
    title: str = ""
    created_at: str | None = None
    updated_at: str | None = None


class ConversationListResponse(BaseModel):
    conversations: list[ConversationResponse]


class MessageResponse(BaseModel):
    message_id: str
    role: str
    content: str
    steps: list[dict[str, Any]] | None = None
    charts: list[dict[str, Any]] | None = None
    table_data: list[dict[str, Any]] | None = None
    suggestions: list[str] | None = None
    created_at: str | None = None
    mutations_performed: bool = False
    schema_changed: bool = False


class MessageListResponse(BaseModel):
    messages: list[MessageResponse]


# ---------------------------------------------------------------------------
# Send Message
# ---------------------------------------------------------------------------

class SendMessageRequest(BaseModel):
    message: str


# ---------------------------------------------------------------------------
# Dashboard Widgets
# ---------------------------------------------------------------------------

class CreateWidgetRequest(BaseModel):
    project_id: str | None = None
    file_id: str | None = None
    widget_type: str
    title: str = ""
    widget_data: dict[str, Any] = {}
    layout: dict[str, Any] = {}


class UpdateLayoutRequest(BaseModel):
    layouts: list[dict[str, Any]]


class WidgetResponse(BaseModel):
    id: str
    widget_type: str
    title: str = ""
    widget_data: dict[str, Any] = {}
    layout: dict[str, Any] = {}
    created_at: str | None = None


class WidgetListResponse(BaseModel):
    widgets: list[WidgetResponse]
