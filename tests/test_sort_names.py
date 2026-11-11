"""Sort names, as iTunes stores them: a sort tag from the file if there is one,
otherwise the name without a leading "The "/"A "/"An " and leading punctuation.
The nano lists and letter-groups by them ("The Killers" under K)."""
import pytest

from ipodsync.library import ItlpLibrary, TrackMeta, _sort_name
from test_cloned_fields import _make_itlp


@pytest.mark.parametrize("name, expected", [
    ("The Beatles", "Beatles"),
    ("A Place for My Head", "Place for My Head"),
    ("An Ending", "Ending"),
    ("THE HOLY", "HOLY"),                          # any case
    ("...And Justice for All", "And Justice for All"),
    ('"It\'s-a Me, Mario!"', 'It\'s-a Me, Mario!"'),
    ("「The Federation」 from FINAL FANTASY XI", "The Federation」 from FINAL FANTASY XI"),
    ("The The", "The"),                            # the article only once, at the start
    ("The", "The"),                                # nothing after it: kept
    ("a-Ha", "a-Ha"),                              # not an article
    ("Anthem", "Anthem"),
    ("Linkin Park", "Linkin Park"),
    ("!!", None),                                  # punctuation only
    ("", None),
])
def test_sort_name_rule(name, expected):
    assert _sort_name(name) == expected


def _add(lib, **kw):
    meta = dict(location="F00/AAAA.mp3", title="A Place for My Head", artist="The Killers",
                album="The Album")
    return lib.add_track(TrackMeta(**{**meta, **kw}), date=0)


def test_added_track_gets_itunes_sort_names_and_sorts_by_them(tmp_path):
    lib = ItlpLibrary(_make_itlp(tmp_path))
    try:
        pid = _add(lib)
        cx = lib.cx["Library.itdb"]
        item = cx.execute("SELECT * FROM item WHERE pid=?", (pid,)).fetchone()
        assert (item["sort_title"], item["sort_artist"], item["sort_album"]) == (
            "Place for My Head", "Killers", "Album")
        assert item["sort_album_artist"] is None       # no album artist tag
        for table in ("artist", "track_artist"):
            assert cx.execute(f"SELECT sort_name FROM {table} WHERE name='The Killers'"
                              ).fetchone()[0] == "Killers"
        assert cx.execute("SELECT sort_name FROM album WHERE name='The Album'").fetchone()[0] == "Album"
        # placed by the sort names: Killers before Metallica, "Place…" between Intro and
        # the template's "The Day That Never Comes" (sort_title kept as the fixture has it)
        assert [r[0] for r in cx.execute("SELECT name FROM artist WHERE name_order < ? "
                                         "ORDER BY name_order", (0xFFFFFFFF,))] == [
            "The Killers", "Metallica"]
        assert [r[0] for r in cx.execute("SELECT title FROM item ORDER BY title_order")] == [
            "Intro", "A Place for My Head", "The Day That Never Comes"]
    finally:
        lib.close()


def test_sort_tags_from_the_file_win(tmp_path):
    lib = ItlpLibrary(_make_itlp(tmp_path))
    try:
        pid = _add(lib, title="The Day", artist="SQUARE ENIX Co., LTD.", album="Final Fantasy",
                   album_artist="SQUARE ENIX Co., LTD.", sort_title="The Day",
                   sort_artist="Ishimoto, Takeharu", sort_album="FINAL FANTASY I",
                   sort_album_artist="Square Enix Music")
        cx = lib.cx["Library.itdb"]
        item = cx.execute("SELECT * FROM item WHERE pid=?", (pid,)).fetchone()
        assert (item["sort_title"], item["sort_artist"], item["sort_album"],
                item["sort_album_artist"]) == ("The Day", "Ishimoto, Takeharu",
                                               "FINAL FANTASY I", "Square Enix Music")
        name = "SQUARE ENIX Co., LTD."
        assert cx.execute("SELECT sort_name FROM artist WHERE name=?", (name,)).fetchone()[0] == \
            "Square Enix Music"                        # artist rows are album artists
        assert cx.execute("SELECT sort_name FROM track_artist WHERE name=?", (name,)).fetchone()[0] == \
            "Ishimoto, Takeharu"
        assert cx.execute("SELECT sort_name FROM album WHERE name='Final Fantasy'").fetchone()[0] == \
            "FINAL FANTASY I"
    finally:
        lib.close()


def test_album_artist_sort_name(tmp_path):
    lib = ItlpLibrary(_make_itlp(tmp_path))
    try:
        pid = _add(lib, artist="Brandon Flowers", album_artist="The Killers")
        cx = lib.cx["Library.itdb"]
        item = cx.execute("SELECT sort_artist, sort_album_artist FROM item WHERE pid=?", (pid,)).fetchone()
        assert tuple(item) == ("Brandon Flowers", "Killers")
        assert cx.execute("SELECT sort_name FROM artist WHERE name='The Killers'").fetchone()[0] == "Killers"
    finally:
        lib.close()
