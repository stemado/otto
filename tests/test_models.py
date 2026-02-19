"""Tests for new token-optimization models."""

from browser_scout.models import ElementSummary, FindElementsResult, InteractiveElement


def test_element_summary_creation():
    summary = ElementSummary(
        total=100,
        visible=80,
        by_type={"button": 10, "input": 5, "a": 65},
        by_frame={"main": 90, "iframe#content": 10},
    )
    assert summary.total == 100
    assert summary.visible == 80
    assert summary.by_type["button"] == 10
    assert summary.by_frame["main"] == 90


def test_element_summary_defaults():
    summary = ElementSummary(total=0, visible=0)
    assert summary.by_type == {}
    assert summary.by_frame == {}


def test_find_elements_result():
    result = FindElementsResult(
        matched=2,
        total_on_page=50,
        elements=[
            InteractiveElement(
                tag="button",
                type="submit",
                selector="#login",
                text="Log In",
            ),
        ],
    )
    assert result.matched == 2
    assert len(result.elements) == 1
    assert result.elements[0].selector == "#login"


def test_find_elements_result_defaults():
    result = FindElementsResult(matched=0, total_on_page=0)
    assert result.elements == []
