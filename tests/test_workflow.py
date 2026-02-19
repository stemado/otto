"""Tests for workflow JSON schema models."""

from browser_scout.models import ActionRecord, SessionHistory
from browser_scout.workflow import (
    Workflow,
    WorkflowConverter,
    WorkflowSettings,
    WorkflowStep,
    WorkflowVariable,
)


def test_workflow_variable_credential():
    var = WorkflowVariable(type="credential", default="your_password", description="Login password")
    assert var.type == "credential"
    assert var.default == "your_password"


def test_workflow_variable_defaults():
    var = WorkflowVariable()
    assert var.type == "string"
    assert var.default == ""
    assert var.description == ""


def test_workflow_settings_defaults():
    settings = WorkflowSettings()
    assert settings.headless is False
    assert settings.default_timeout_ms == 30000
    assert settings.step_delay_ms == 500
    assert settings.on_error == "stop"


def test_workflow_step_navigate():
    step = WorkflowStep(order=1, name="Go to login", action="navigate", value="https://example.com")
    assert step.order == 1
    assert step.action == "navigate"
    assert step.value == "https://example.com"
    assert step.selector is None
    assert step.frame_context is None


def test_workflow_step_click_with_iframe():
    step = WorkflowStep(
        order=5,
        name="Click export button",
        action="click",
        selector="#exportBtn",
        frame_context="iframe#adprIframe",
    )
    assert step.frame_context == "iframe#adprIframe"


def test_workflow_step_type_with_variable_ref():
    step = WorkflowStep(
        order=2,
        name="Enter username",
        action="type",
        selector="#username",
        value="${USERNAME}",
        clear_first=True,
    )
    assert step.value == "${USERNAME}"
    assert step.clear_first is True


def test_workflow_step_wait_for_download():
    step = WorkflowStep(
        order=9,
        name="Wait for CSV download",
        action="wait_for_download",
        timeout_ms=60000,
        filename_pattern="*.csv",
    )
    assert step.action == "wait_for_download"
    assert step.filename_pattern == "*.csv"


def test_workflow_step_wait_for_response():
    step = WorkflowStep(
        order=7,
        name="Wait for report API response",
        action="wait_for_response",
        url_pattern=r"/api/reports/\d+",
        timeout_ms=15000,
    )
    assert step.action == "wait_for_response"
    assert step.url_pattern == r"/api/reports/\d+"


def test_workflow_step_defaults():
    step = WorkflowStep(order=1, name="test", action="click", selector="#btn")
    assert step.on_error is None
    assert step.timeout_ms is None
    assert step.clear_first is None
    assert step.shadow_pierce is None
    assert step.wait_for_load is None
    assert step.filename_pattern is None
    assert step.url_pattern is None
    assert step.method is None
    assert step.download_dir is None


def test_full_workflow():
    workflow = Workflow(
        name="test-workflow",
        description="A test workflow",
        variables={
            "USERNAME": WorkflowVariable(type="credential", default="your_user"),
        },
        steps=[
            WorkflowStep(order=1, name="Navigate", action="navigate", value="https://example.com"),
            WorkflowStep(order=2, name="Type user", action="type", selector="#user", value="${USERNAME}"),
        ],
    )
    assert workflow.schema_version == "1.0"
    assert workflow.name == "test-workflow"
    assert len(workflow.steps) == 2
    assert "USERNAME" in workflow.variables


def test_workflow_to_json_roundtrip():
    workflow = Workflow(
        name="roundtrip-test",
        description="Tests JSON serialization roundtrip",
        steps=[
            WorkflowStep(order=1, name="Navigate", action="navigate", value="https://example.com"),
        ],
    )
    json_str = workflow.model_dump_json(exclude_none=True, indent=2)
    restored = Workflow.model_validate_json(json_str)
    assert restored.name == "roundtrip-test"
    assert restored.steps[0].value == "https://example.com"


# --- Converter tests ---


def _make_history(actions: list[ActionRecord], session_id: str = "test-session") -> SessionHistory:
    """Helper to build a minimal SessionHistory for testing."""
    return SessionHistory(
        session_id=session_id,
        started_at="2026-02-19T14:00:00Z",
        actions=actions,
    )


def test_converter_navigate_action():
    history = _make_history([
        ActionRecord(action="navigate", value="https://example.com", success=True, timestamp="2026-02-19T14:00:01Z"),
    ])
    workflow = WorkflowConverter.from_history(history, name="test")
    assert len(workflow.steps) == 1
    assert workflow.steps[0].action == "navigate"
    assert workflow.steps[0].value == "https://example.com"
    assert workflow.steps[0].order == 1


def test_converter_skips_failed_actions():
    history = _make_history([
        ActionRecord(action="click", selector="#btn", success=True, timestamp="T1"),
        ActionRecord(action="click", selector="#missing", success=False, error="not found", timestamp="T2"),
        ActionRecord(action="type", selector="#input", value="hello", success=True, timestamp="T3"),
    ])
    workflow = WorkflowConverter.from_history(history, name="test")
    assert len(workflow.steps) == 2
    assert workflow.steps[0].action == "click"
    assert workflow.steps[1].action == "type"
    assert workflow.steps[1].order == 2


def test_converter_preserves_frame_context():
    history = _make_history([
        ActionRecord(
            action="click", selector="#btn", frame_context="iframe#content",
            success=True, timestamp="T1",
        ),
    ])
    workflow = WorkflowConverter.from_history(history, name="test")
    assert workflow.steps[0].frame_context == "iframe#content"


def test_converter_strips_main_frame_context():
    history = _make_history([
        ActionRecord(
            action="click", selector="#btn", frame_context="main",
            success=True, timestamp="T1",
        ),
    ])
    workflow = WorkflowConverter.from_history(history, name="test")
    assert workflow.steps[0].frame_context is None


def test_converter_parameterizes_password():
    history = _make_history([
        ActionRecord(action="type", selector="#login-form_password", value="s3cret!", success=True, timestamp="T1"),
    ])
    workflow = WorkflowConverter.from_history(history, name="test")
    assert workflow.steps[0].value == "${PASSWORD}"
    assert "PASSWORD" in workflow.variables
    assert workflow.variables["PASSWORD"].type == "credential"


def test_converter_parameterizes_username_before_password():
    history = _make_history([
        ActionRecord(action="type", selector="#login-form_username", value="admin", success=True, timestamp="T1"),
        ActionRecord(action="click", selector="#next", success=True, timestamp="T2"),
        ActionRecord(action="type", selector="#login-form_password", value="s3cret!", success=True, timestamp="T3"),
    ])
    workflow = WorkflowConverter.from_history(history, name="test")
    assert workflow.steps[0].value == "${USERNAME}"
    assert "USERNAME" in workflow.variables
    assert workflow.variables["USERNAME"].type == "credential"
    # Step 2 (click) is preserved between username and password
    assert workflow.steps[2].value == "${PASSWORD}"


def test_converter_auto_generates_step_names():
    history = _make_history([
        ActionRecord(action="navigate", value="https://example.com/login", success=True, timestamp="T1"),
        ActionRecord(action="click", selector="#submit-btn", success=True, timestamp="T2"),
    ])
    workflow = WorkflowConverter.from_history(history, name="test")
    assert "Navigate" in workflow.steps[0].name or "navigate" in workflow.steps[0].name.lower()
    assert workflow.steps[1].name  # Non-empty name generated


def test_converter_sets_source():
    history = _make_history([], session_id="sess-abc")
    workflow = WorkflowConverter.from_history(history, name="test")
    assert workflow.source.tool == "browser-scout"
    assert workflow.source.session_id == "sess-abc"


def test_converter_json_output_excludes_none():
    history = _make_history([
        ActionRecord(action="click", selector="#btn", success=True, timestamp="T1"),
    ])
    workflow = WorkflowConverter.from_history(history, name="test")
    json_str = workflow.model_dump_json(exclude_none=True, indent=2)
    # None fields like frame_context, shadow_pierce should not appear
    assert "frame_context" not in json_str
    assert "shadow_pierce" not in json_str
    assert "url_pattern" not in json_str
