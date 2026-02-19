"""Session history tracking — append-only log of all session activity."""

from __future__ import annotations

from datetime import datetime, timezone

from .models import (
    ActionRecord,
    FindElementsRecord,
    NetworkEvent,
    ScoutReport,
    ScoutSummaryRecord,
    SessionHistory,
)
from .scout import build_element_summary


class SessionHistoryTracker:
    """Tracks all actions, scout reports, network events, and navigations for a session."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.actions: list[ActionRecord] = []
        self.scouts: list[ScoutSummaryRecord] = []
        self.find_elements_calls: list[FindElementsRecord] = []
        self.network_events: list[NetworkEvent] = []
        self.navigations: list[dict] = []

    def record_scout(self, report: ScoutReport) -> None:
        """Record a compact summary of a scout (no element list)."""
        summary = build_element_summary(report.interactive_elements)
        self.scouts.append(ScoutSummaryRecord(
            page_metadata=report.page_metadata,
            iframe_count=len(report.iframe_map),
            shadow_dom_count=len(report.shadow_dom_boundaries),
            element_summary=summary,
            page_summary=report.page_summary,
        ))

    def record_find_elements(
        self, query: str | None, element_types: list[str] | None, matched: int
    ) -> None:
        """Record a compact find_elements call."""
        self.find_elements_calls.append(FindElementsRecord(
            query=query,
            element_types=element_types,
            matched=matched,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ))

    def record_action(self, record: ActionRecord) -> None:
        self.actions.append(record)

    def record_navigation(self, url: str) -> None:
        self.navigations.append({
            "url": url,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def record_network_event(self, event: NetworkEvent) -> None:
        self.network_events.append(event)

    def get_full_history(self) -> SessionHistory:
        return SessionHistory(
            session_id=self.session_id,
            started_at=self.started_at,
            actions=self.actions,
            scouts=self.scouts,
            find_elements_calls=self.find_elements_calls,
            network_events=self.network_events,
            navigations=self.navigations,
        )
