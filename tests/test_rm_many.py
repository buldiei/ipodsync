"""`rm` removes several tracks (or a whole album) in one go, signing and compacting
the artwork once instead of per track; --album/--artist ask before removing."""
from types import SimpleNamespace

import pytest

from ipodsync.cli import _confirm_rm, _rm_selection
from ipodsync.library import ItlpLibrary
from test_cloned_fields import _add, _make_itlp

TRACKS = [
    {"pid": 1, "title": "ANOTHER HIM", "artist": "Toby Fox", "album": "UNDERTALE (disc 1)"},
    {"pid": 2, "title": "Megalovania", "artist": "Toby Fox", "album": "UNDERTALE (disc 2)"},
    {"pid": 3, "title": "Papercut", "artist": "Linkin Park", "album": "Hybrid Theory"},
]


def _args(*pids, album=None, artist=None, yes=False, keep_file=False):
    return SimpleNamespace(pid=list(pids), album=album, artist=artist, yes=yes,
                           keep_file=keep_file)


def test_remove_tracks_removes_all_and_recounts_once(tmp_path):
    lib = ItlpLibrary(_make_itlp(tmp_path))
    try:
        pids = [_add(lib, t, "Linkin Park", "Meteora", n) for n, t in
                enumerate(("Foreword", "Don't Stay", "Numb"), 1)]
        keep = _add(lib, "Papercut", "Linkin Park", "Hybrid Theory")
        locations = lib.remove_tracks(pids)
        cx = lib.cx["Library.itdb"]
        assert locations == ["F00/Fore.mp3", "F00/Don'.mp3", "F00/Numb.mp3"]
        assert [r[0] for r in cx.execute("SELECT pid FROM item WHERE artist='Linkin Park'")] == [keep]
        assert cx.execute("SELECT count(*) FROM album WHERE name='Meteora'").fetchone()[0] == 0
        assert cx.execute("SELECT album_count FROM artist WHERE name='Linkin Park'").fetchone()[0] == 1
        assert lib.cx["Locations.itdb"].execute(
            "SELECT count(*) FROM location WHERE item_pid IN (?,?,?)", pids).fetchone()[0] == 0
    finally:
        lib.close()


def test_selection_by_pids_album_and_artist():
    assert [t["pid"] for t in _rm_selection(TRACKS, _args(3, 1))] == [1, 3]
    assert [t["pid"] for t in _rm_selection(TRACKS, _args(album="undertale"))] == [1, 2]
    assert [t["pid"] for t in _rm_selection(TRACKS, _args(album="disc 2", artist="TOBY"))] == [2]
    assert _rm_selection(TRACKS, _args(album="nope")) == []


def test_selection_needs_pids_or_a_filter():
    with pytest.raises(SystemExit):
        _rm_selection(TRACKS, _args())          # never "remove everything"


def test_album_removal_asks_first(monkeypatch, capsys):
    tracks = _rm_selection(TRACKS, _args(album="undertale"))
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    assert _confirm_rm(tracks, _args(album="undertale")) is True
    out = capsys.readouterr().out
    assert "UNDERTALE (disc 1) — Toby Fox" in out and "UNDERTALE (disc 2) — Toby Fox" in out

    monkeypatch.setattr("builtins.input", lambda prompt: "")
    assert _confirm_rm(tracks, _args(album="undertale")) is False


def test_no_question_for_pids_or_yes_and_no_by_default_without_a_terminal(monkeypatch):
    def no_terminal(prompt):
        raise EOFError

    monkeypatch.setattr("builtins.input", no_terminal)
    assert _confirm_rm(TRACKS[:1], _args(1)) is True
    assert _confirm_rm(TRACKS[:2], _args(album="undertale", yes=True)) is True
    assert _confirm_rm(TRACKS[:2], _args(album="undertale")) is False
