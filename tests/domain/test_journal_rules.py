"""Journal rules that do not need PostgreSQL."""

import pytest

from earthtrend.api.domain.journal.model import JournalError, Note, require_kind


def test_note_and_hypothesis_are_accepted() -> None:
    note = Note(id="n1", author_id="u", case_id="c", text="текст", kind="note")
    hypothesis = Note(id="n2", author_id="u", case_id="c", text="текст", kind="hypothesis")
    assert note.kind == "note"
    assert hypothesis.kind == "hypothesis"
    assert note.owned_by("u")
    assert not hypothesis.owned_by("other")


def test_unknown_kind_is_rejected() -> None:
    with pytest.raises(JournalError) as caught:
        require_kind("conclusion")
    assert caught.value.code == "kind_invalid"
    with pytest.raises(JournalError) as caught:
        Note(id="n", author_id="u", case_id="c", text="текст", kind="conclusion")
    assert caught.value.code == "kind_invalid"
