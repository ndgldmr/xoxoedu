"""Mention parsing for discussion post bodies.

Extracts ``@username`` patterns from free-text post content and normalises
them into a deduplicated list of lowercase usernames for downstream use by
notification hooks.

Pattern rules:
- A mention starts with ``@`` and is followed by one or more alphanumeric
  characters or underscores.
- The ``@`` must start at the beginning of the text or follow a non-word
  boundary so email addresses like ``user@example.com`` do not create
  accidental mentions.
- Termination is determined by the regex engine: any character that is not
  alphanumeric or ``_`` ends the token.  This makes the parser tolerant of
  punctuation boundaries such as ``@alice,``, ``@bob.``, and ``@carol!``.
- Matching is case-insensitive for deduplication: ``@Alice`` and ``@alice``
  in the same post collapse to a single entry ``alice``.
- The returned list preserves first-occurrence order after normalisation.
"""

from __future__ import annotations

import re

# Matches @username tokens; group(1) captures the username portion only.
_MENTION_RE = re.compile(r"(?<![A-Za-z0-9_])@([A-Za-z0-9_]+)")


def extract_mentions(text: str) -> list[str]:
    """Return a deduplicated, lowercase list of @mentioned usernames.

    Args:
        text: The raw post body to scan.

    Returns:
        An ordered list of unique lowercase usernames found in *text*.
        The order reflects first occurrence.  An empty list is returned
        if no mentions are present.

    Examples::

        >>> extract_mentions("Hey @Alice, look at @bob's answer!")
        ['alice', 'bob']

        >>> extract_mentions("@Carol @carol @CAROL")
        ['carol']

        >>> extract_mentions("No mentions here.")
        []
    """
    seen: set[str] = set()
    result: list[str] = []
    for match in _MENTION_RE.finditer(text):
        username_lower = match.group(1).lower()
        if username_lower not in seen:
            seen.add(username_lower)
            result.append(username_lower)
    return result
