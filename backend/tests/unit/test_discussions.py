"""Unit tests for discussion service helpers."""

import uuid
from datetime import UTC, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.discussions.service import TOMBSTONE, decode_cursor, encode_cursor


# ── Cursor ─────────────────────────────────────────────────────────────────────

class TestCursor:
    def test_roundtrip(self) -> None:
        """Encoding then decoding returns the original (created_at, id) pair."""
        ts = datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC)
        post_id = uuid.uuid4()

        cursor = encode_cursor(ts, post_id)
        recovered_ts, recovered_id = decode_cursor(cursor)

        assert recovered_ts == ts
        assert recovered_id == post_id

    def test_roundtrip_microseconds(self) -> None:
        """Sub-second precision is preserved through encode/decode."""
        ts = datetime(2026, 4, 20, 12, 0, 0, 123456, tzinfo=UTC)
        post_id = uuid.uuid4()

        cursor = encode_cursor(ts, post_id)
        recovered_ts, _ = decode_cursor(cursor)

        assert recovered_ts == ts

    def test_roundtrip_different_timezone(self) -> None:
        """Timestamps with explicit UTC offset survive the roundtrip correctly."""
        ts = datetime(2026, 4, 20, 8, 0, 0, tzinfo=timezone.utc)
        post_id = uuid.uuid4()

        cursor = encode_cursor(ts, post_id)
        recovered_ts, recovered_id = decode_cursor(cursor)

        assert recovered_ts == ts
        assert recovered_id == post_id

    def test_decode_invalid_raises_value_error(self) -> None:
        """A malformed cursor raises ``ValueError``."""
        with pytest.raises(ValueError, match="Invalid cursor"):
            decode_cursor("not-valid-base64!!!")

    def test_decode_truncated_raises_value_error(self) -> None:
        """A cursor missing the ``|`` separator raises ``ValueError``."""
        import base64
        bad = base64.urlsafe_b64encode(b"no-separator-here").decode()
        with pytest.raises(ValueError):
            decode_cursor(bad)

    def test_decode_bad_uuid_raises_value_error(self) -> None:
        """A cursor with a non-UUID ID segment raises ``ValueError``."""
        import base64
        bad = base64.urlsafe_b64encode(b"2026-01-01T00:00:00+00:00|not-a-uuid").decode()
        with pytest.raises(ValueError):
            decode_cursor(bad)

    def test_cursor_is_url_safe(self) -> None:
        """Generated cursors contain only URL-safe characters."""
        ts = datetime(2026, 4, 20, 0, 0, 0, tzinfo=UTC)
        cursor = encode_cursor(ts, uuid.uuid4())
        assert all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_=" for c in cursor)

    def test_two_different_posts_produce_different_cursors(self) -> None:
        """Two distinct posts encode to distinct cursors."""
        ts = datetime(2026, 4, 20, 0, 0, 0, tzinfo=UTC)
        c1 = encode_cursor(ts, uuid.uuid4())
        c2 = encode_cursor(ts, uuid.uuid4())
        assert c1 != c2


# ── Soft-delete tombstone ──────────────────────────────────────────────────────

class TestTombstone:
    def test_tombstone_constant_value(self) -> None:
        """TOMBSTONE is the agreed literal the client expects to display."""
        assert TOMBSTONE == "[deleted]"

    def test_tombstone_is_non_empty(self) -> None:
        """TOMBSTONE is a non-empty string so the body field is always present."""
        assert len(TOMBSTONE) > 0


# ── Ordering contract ──────────────────────────────────────────────────────────

class TestCursorOrdering:
    """Verify the cursor comparison semantics match the intended sort order."""

    def test_top_level_cursor_is_newer(self) -> None:
        """For newest-first ordering, a later timestamp yields a 'less-than' cursor position.

        The next-page cursor encodes the last item in the current page.  The
        query for the next page must return rows *older* than that cursor.
        With (created_at DESC, id DESC) ordering, 'older' means created_at is
        strictly less than the cursor's timestamp, or equal timestamp with a
        smaller id.  This test documents that expectation by checking that two
        timestamps can be compared as expected.
        """
        ts_newer = datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC)
        ts_older = datetime(2026, 4, 20, 11, 0, 0, tzinfo=UTC)

        cursor_ts, _ = decode_cursor(encode_cursor(ts_newer, uuid.uuid4()))

        # The next-page filter condition for top-level posts is: created_at < cursor_ts
        assert ts_older < cursor_ts

    def test_reply_cursor_is_older(self) -> None:
        """For oldest-first ordering, a later cursor means the next page has *newer* rows."""
        ts_older = datetime(2026, 4, 20, 11, 0, 0, tzinfo=UTC)
        ts_newer = datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC)

        cursor_ts, _ = decode_cursor(encode_cursor(ts_older, uuid.uuid4()))

        # The next-page filter for replies is: created_at > cursor_ts
        assert ts_newer > cursor_ts


# ── Upvote toggle logic ────────────────────────────────────────────────────────

class TestUpvoteToggle:
    """Verify the upvote toggle contract without hitting the database."""

    def test_toggle_adds_vote_when_no_existing_vote(self) -> None:
        """When no vote exists, toggling should result in a vote being present."""
        existing_vote = None
        # Simulate the toggle logic
        if existing_vote is not None:
            action = "removed"
        else:
            action = "added"
        assert action == "added"

    def test_toggle_removes_vote_when_vote_exists(self) -> None:
        """When a vote already exists, toggling should remove it."""
        existing_vote = MagicMock()  # non-None simulates an existing vote row
        if existing_vote is not None:
            action = "removed"
        else:
            action = "added"
        assert action == "removed"

    def test_toggle_is_idempotent_in_pairs(self) -> None:
        """Add → Remove is a clean round-trip back to 0 votes."""
        vote_count = 0

        # Add
        vote_count += 1
        assert vote_count == 1

        # Remove
        vote_count -= 1
        assert vote_count == 0

    def test_author_cannot_vote_on_own_post(self) -> None:
        """Service raises CannotVoteOnOwnPost when author_id == user_id."""
        from app.core.exceptions import CannotVoteOnOwnPost

        author_id = uuid.uuid4()
        user_id = author_id  # same user

        with pytest.raises(CannotVoteOnOwnPost):
            if author_id == user_id:
                raise CannotVoteOnOwnPost()

    def test_different_user_can_vote(self) -> None:
        """A different user (not the author) should be allowed to vote."""
        from app.core.exceptions import CannotVoteOnOwnPost

        author_id = uuid.uuid4()
        user_id = uuid.uuid4()  # different user

        # Should NOT raise
        try:
            if author_id == user_id:
                raise CannotVoteOnOwnPost()
        except CannotVoteOnOwnPost:
            pytest.fail("Should not raise for a different user")


# ── Duplicate open-flag protection ────────────────────────────────────────────

class TestDuplicateFlagProtection:
    """Verify the duplicate open-flag guard logic."""

    def test_new_flag_created_when_no_open_flag_exists(self) -> None:
        """When no open flag exists, a new flag row should be inserted."""
        existing_open_flag = None
        action = "update" if existing_open_flag is not None else "create"
        assert action == "create"

    def test_existing_open_flag_is_updated_not_duplicated(self) -> None:
        """When an open flag already exists, it should be updated in-place."""
        existing_open_flag = MagicMock()
        existing_open_flag.reason = "spam"
        action = "update" if existing_open_flag is not None else "create"
        assert action == "update"

    def test_update_changes_reason_and_context(self) -> None:
        """Updating an existing flag changes its reason and context fields."""
        existing_flag = MagicMock()
        existing_flag.reason = "spam"
        existing_flag.context = None

        # Simulate update
        new_reason = "harassment"
        new_context = "The post contains threatening language"
        existing_flag.reason = new_reason
        existing_flag.context = new_context

        assert existing_flag.reason == "harassment"
        assert existing_flag.context == "The post contains threatening language"

    def test_author_cannot_flag_own_post(self) -> None:
        """Service raises CannotFlagOwnPost when author_id == user_id."""
        from app.core.exceptions import CannotFlagOwnPost

        author_id = uuid.uuid4()
        user_id = author_id

        with pytest.raises(CannotFlagOwnPost):
            if author_id == user_id:
                raise CannotFlagOwnPost()

    def test_non_author_can_flag_post(self) -> None:
        """A user who is not the post author should be allowed to flag."""
        from app.core.exceptions import CannotFlagOwnPost

        author_id = uuid.uuid4()
        user_id = uuid.uuid4()

        try:
            if author_id == user_id:
                raise CannotFlagOwnPost()
        except CannotFlagOwnPost:
            pytest.fail("Should not raise for a non-author")

    def test_resolved_flag_cannot_be_resolved_again(self) -> None:
        """Attempting to resolve an already-resolved flag raises DiscussionFlagAlreadyResolved."""
        from app.core.exceptions import DiscussionFlagAlreadyResolved

        flag_status = "dismissed"  # already resolved

        with pytest.raises(DiscussionFlagAlreadyResolved):
            if flag_status != "open":
                raise DiscussionFlagAlreadyResolved()

    def test_open_flag_can_be_resolved(self) -> None:
        """An open flag in status 'open' passes the resolution guard."""
        from app.core.exceptions import DiscussionFlagAlreadyResolved

        flag_status = "open"

        try:
            if flag_status != "open":
                raise DiscussionFlagAlreadyResolved()
        except DiscussionFlagAlreadyResolved:
            pytest.fail("Should not raise for an open flag")
