"""Tests for the discovery digest's Slack pointer message.

The bot never posts the paper list itself for the weekly digest — just a
link to the page (see CLAUDE.md). Lab-watch's own Slack formatting is
covered in test_lab_watch.py.
"""

from app.slack import build_digest_pointer_message


def test_pointer_message_with_new_papers():
    [msg] = build_digest_pointer_message(7, "https://example.github.io/ourak/digest.html")
    assert "7 new papers this week" in msg["text"]
    assert "https://example.github.io/ourak/digest.html" in msg["text"]


def test_pointer_message_singular():
    [msg] = build_digest_pointer_message(1, "https://x/digest.html")
    assert "1 new paper this week" in msg["text"]
    assert "1 new papers" not in msg["text"]


def test_pointer_message_no_new_papers_still_links():
    [msg] = build_digest_pointer_message(0, "https://x/digest.html")
    assert "no new papers this week" in msg["text"]
    assert "https://x/digest.html" in msg["text"]
