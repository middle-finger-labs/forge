"""Tests for integrations.linear_client stub."""

from __future__ import annotations

import pytest

from integrations.linear_client import LinearTracker


class TestLinearTrackerStub:
    """All methods should raise NotImplementedError with a useful message."""

    @pytest.fixture
    def tracker(self):
        return LinearTracker(api_key="lin_test", team_id="TEAM-1")

    @pytest.mark.asyncio
    async def test_get_issue_as_spec(self, tracker):
        with pytest.raises(NotImplementedError, match="not yet implemented"):
            await tracker.get_issue_as_spec("LIN-42")

    @pytest.mark.asyncio
    async def test_get_issues_for_pipeline(self, tracker):
        with pytest.raises(NotImplementedError, match="not yet implemented"):
            await tracker.get_issues_for_pipeline()

    @pytest.mark.asyncio
    async def test_update_issue_status(self, tracker):
        with pytest.raises(NotImplementedError, match="not yet implemented"):
            await tracker.update_issue_status("LIN-42", "Coding in progress")

    @pytest.mark.asyncio
    async def test_create_sub_issues(self, tracker):
        with pytest.raises(NotImplementedError, match="not yet implemented"):
            await tracker.create_sub_issues("LIN-42", [{"ticket_key": "T-1"}])

    @pytest.mark.asyncio
    async def test_watch_for_triggers(self, tracker):
        with pytest.raises(NotImplementedError, match="webhook"):
            await tracker.watch_for_triggers(lambda x: x)

    def test_constructor_stores_params(self, tracker):
        assert tracker._api_key == "lin_test"
        assert tracker._team_id == "TEAM-1"
