"""Unit tests for the discussion mention parsing utility."""

from app.modules.discussions.mentions import extract_mentions


class TestExtractMentions:
    def test_single_mention(self) -> None:
        """A single @mention is extracted and lowercased."""
        result = extract_mentions("Hello @Alice!")
        assert result == ["alice"]

    def test_multiple_distinct_mentions(self) -> None:
        """Multiple different @mentions are all extracted in order."""
        result = extract_mentions("Hey @Alice, check with @Bob about this.")
        assert result == ["alice", "bob"]

    def test_case_insensitive_deduplication(self) -> None:
        """@Alice, @alice, and @ALICE collapse to a single 'alice' entry."""
        result = extract_mentions("@Carol @carol @CAROL")
        assert result == ["carol"]

    def test_mixed_case_deduplication_preserves_first_occurrence(self) -> None:
        """Deduplication keeps the first-seen normalised form."""
        result = extract_mentions("Thanks @Dave and @dave for helping")
        assert result == ["dave"]

    def test_no_mentions_returns_empty_list(self) -> None:
        """Text with no @ patterns returns an empty list."""
        result = extract_mentions("No mentions here, just regular text.")
        assert result == []

    def test_empty_string_returns_empty_list(self) -> None:
        """An empty input returns an empty list."""
        assert extract_mentions("") == []

    def test_mention_at_start_of_text(self) -> None:
        """A mention at the very beginning of the text is captured."""
        result = extract_mentions("@Eve you should see this")
        assert result == ["eve"]

    def test_mention_at_end_of_text(self) -> None:
        """A mention at the very end of the text (no trailing space) is captured."""
        result = extract_mentions("Great job @Frank")
        assert result == ["frank"]

    def test_punctuation_boundary_comma(self) -> None:
        """A comma after a mention does not become part of the username."""
        result = extract_mentions("@grace, can you review?")
        assert result == ["grace"]

    def test_punctuation_boundary_period(self) -> None:
        """A period after a mention does not become part of the username."""
        result = extract_mentions("Ask @henry. He knows.")
        assert result == ["henry"]

    def test_punctuation_boundary_exclamation(self) -> None:
        """An exclamation mark after a mention does not become part of the username."""
        result = extract_mentions("Great work @iris!")
        assert result == ["iris"]

    def test_punctuation_boundary_question_mark(self) -> None:
        """A question mark after a mention does not become part of the username."""
        result = extract_mentions("Did you see @jack?")
        assert result == ["jack"]

    def test_underscore_in_username(self) -> None:
        """Underscores are valid username characters and are included."""
        result = extract_mentions("Ping @kate_smith for this")
        assert result == ["kate_smith"]

    def test_numbers_in_username(self) -> None:
        """Numeric characters in usernames are captured correctly."""
        result = extract_mentions("Good point @user123!")
        assert result == ["user123"]

    def test_at_sign_not_followed_by_alphanumeric(self) -> None:
        """A bare @ not followed by alphanumeric characters is ignored."""
        result = extract_mentions("Send to user @ example.com")
        assert result == []

    def test_email_address_not_treated_as_mention(self) -> None:
        """An email address should not create a false-positive mention."""
        result = extract_mentions("Contact user@example.com")
        assert result == []

    def test_preserves_first_occurrence_order(self) -> None:
        """Mention list order matches first occurrence in the text."""
        result = extract_mentions("@zara then @yvonne then @zara again")
        assert result == ["zara", "yvonne"]

    def test_many_unique_mentions(self) -> None:
        """All unique mentions in a longer text are captured."""
        text = "Shoutout to @anna @ben @chloe @dan @elle for their contributions!"
        result = extract_mentions(text)
        assert result == ["anna", "ben", "chloe", "dan", "elle"]

    def test_only_at_signs_returns_empty(self) -> None:
        """A string of bare @ signs with no following tokens returns empty list."""
        assert extract_mentions("@ @@ @  @") == []

    def test_adjacent_mentions_no_space(self) -> None:
        """A second @mention requires a delimiter before it."""
        result = extract_mentions("@alice@bob")
        assert result == ["alice"]
