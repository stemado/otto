"""Workflow JSON schema models -- portable, replayable browser automation recipes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class WorkflowVariable(BaseModel):
    """A declared variable for parameterizing workflow steps."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["credential", "string", "url"] = "string"
    default: str = ""
    description: str = ""


class WorkflowSettings(BaseModel):
    """Global execution settings for a workflow."""

    model_config = ConfigDict(extra="forbid")

    headless: bool = False
    default_timeout_ms: int = Field(default=30000, ge=0)
    step_delay_ms: int = Field(default=500, ge=0)
    on_error: Literal["stop", "continue", "retry"] = "stop"


class WorkflowStep(BaseModel):
    """A single step in a workflow sequence."""

    model_config = ConfigDict(extra="forbid")

    order: int = Field(ge=1)
    name: str
    action: Literal[
        "navigate", "click", "type", "select", "scroll", "wait",
        "wait_for_download", "wait_for_response",
        "press_key", "hover", "clear",
    ]

    # Common optional fields
    selector: str | None = None
    value: str | None = None
    frame_context: str | None = None
    on_error: Literal["stop", "continue", "retry"] | None = None
    timeout_ms: int | None = Field(default=None, ge=0)

    # Action-specific optional fields
    shadow_pierce: bool | None = None          # click, type, select
    clear_first: bool | None = None            # type
    wait_for_load: bool | None = None          # navigate
    filename_pattern: str | None = None        # wait_for_download
    download_dir: str | None = None            # wait_for_download
    url_pattern: str | None = None             # wait_for_response
    method: str | None = None                  # wait_for_response


class WorkflowSource(BaseModel):
    """Provenance of a workflow -- which tool generated it."""

    model_config = ConfigDict(extra="forbid")

    tool: str = "browser-scout"
    session_id: str = ""


class Workflow(BaseModel):
    """A portable, replayable browser automation workflow."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    name: str
    description: str = ""
    created: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source: WorkflowSource = Field(default_factory=WorkflowSource)
    variables: dict[str, WorkflowVariable] = Field(default_factory=dict)
    settings: WorkflowSettings = Field(default_factory=WorkflowSettings)
    steps: list[WorkflowStep] = Field(default_factory=list)
