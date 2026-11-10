"""add_track() clones an existing row as a template for each new item/album row.
Nothing describing the template's own track or album may leak into the new row:
otherwise e.g. the Albums list shows the template album's artist."""
import sqlite3

from ipodsync.library import ItlpLibrary, TrackMeta

UNKNOWN = 0xFFFFFFFF


def _make_itlp(tmp_path):
    """A library whose first rows (the templates) are a Metallica track/album with
    an album artist, composer, comment, disc info, compilation flag and cover.
    There are no empty-name rows, so the Unknown artist sorts after the last name."""
    d = tmp_path / "iTunes Library.itlp"
    d.mkdir()
    loc = sqlite3.connect(d / "Locations.itdb")
    loc.executescript(
        """
        CREATE TABLE location (item_pid INTEGER, location TEXT, file_size INTEGER,
            extension INTEGER, date_created INTEGER);
        INSERT INTO location VALUES (101, 'F00/AAAA.mp3', 1, 1, 0);
        """
    )
    loc.commit()
    loc.close()
    sqlite3.connect(d / "Dynamic.itdb").execute("CREATE TABLE item_stats (item_pid INTEGER)")
    sqlite3.connect(d / "Extras.itdb").execute("CREATE TABLE chapter (item_pid INTEGER)")
    lib = sqlite3.connect(d / "Library.itdb")
    lib.executescript(
        f"""
        CREATE TABLE item (pid INTEGER PRIMARY KEY, title TEXT, artist TEXT, album TEXT,
            album_artist TEXT, composer TEXT, comment TEXT, sort_title TEXT, sort_artist TEXT,
            sort_album TEXT, sort_album_artist TEXT, sort_composer TEXT, year INTEGER,
            total_time_ms INTEGER, track_number INTEGER, track_count INTEGER,
            disc_number INTEGER, disc_count INTEGER, is_compilation INTEGER, genre_id INTEGER,
            album_pid INTEGER, artist_pid INTEGER, track_artist_pid INTEGER, composer_pid INTEGER,
            date_modified INTEGER, title_order INTEGER, album_order INTEGER,
            artist_order INTEGER, album_artist_order INTEGER, album_by_artist_order INTEGER,
            composer_order INTEGER, artwork_status INTEGER, artwork_cache_id INTEGER);
        CREATE TABLE artist (pid INTEGER PRIMARY KEY, name TEXT, sort_name TEXT, name_order INTEGER,
            album_count INTEGER);
        CREATE TABLE track_artist (pid INTEGER PRIMARY KEY, name TEXT, sort_name TEXT,
            name_order INTEGER, album_count INTEGER);
        CREATE TABLE album (pid INTEGER PRIMARY KEY, name TEXT, sort_name TEXT, name_order INTEGER,
            sort_order INTEGER, artist_pid INTEGER, artist_order INTEGER, item_count INTEGER,
            artist_count_calc INTEGER, all_compilations INTEGER, has_any_compilations INTEGER,
            artwork_status INTEGER, artwork_item_pid INTEGER);
        CREATE TABLE composer (pid INTEGER PRIMARY KEY, name TEXT, sort_name TEXT,
            name_order INTEGER, is_unknown INTEGER);
        CREATE TABLE genre_map (id INTEGER PRIMARY KEY, genre TEXT, has_music INTEGER,
            artist_count_calc INTEGER, album_count_calc INTEGER, album_artist_count_calc INTEGER);
        CREATE TABLE avformat_info (item_pid INTEGER, audio_format INTEGER, bit_rate INTEGER,
            sample_rate INTEGER);
        CREATE TABLE db_info (primary_container_pid INTEGER);
        CREATE TABLE item_to_container (item_pid INTEGER, container_pid INTEGER,
            physical_order INTEGER);
        CREATE TABLE track_size_calc (kind TEXT, size INTEGER);
        INSERT INTO db_info VALUES (1);
        INSERT INTO track_size_calc VALUES ('audio', 0);

        -- Metallica's album_count is stale (3, but its tracks are on one album)
        INSERT INTO artist VALUES (10, 'Metallica', 'Metallica', 100, 3),
            (19, 'Unknown Artist', 'Unknown Artist', {UNKNOWN}, 1);
        INSERT INTO track_artist SELECT * FROM artist;
        INSERT INTO album VALUES
            (20, 'Death Magnetic', 'Death Magnetic', 100, 100, 10, 100, 2, 1, 1, 1, 1, 101),
            (21, 'Greatest Hits', 'Greatest Hits', 200, 200, 10, 100, 0, 0, 0, 0, 0, 0),
            (29, 'Unknown Album', '', {UNKNOWN}, 300, 19, {UNKNOWN}, 1, 1, 0, 0, 0, 0);
        INSERT INTO composer VALUES (1, 'Hetfield', 'Hetfield', 100, 0),
            (2, 'Unknown Composer', 'Unknown Composer', {UNKNOWN}, 1);
        INSERT INTO item VALUES
            (101, 'The Day That Never Comes', 'Metallica', 'Death Magnetic', 'Metallica',
                'Hetfield', 'a comment', 'The Day That Never Comes', 'Metallica',
                'Death Magnetic', 'Metallica', 'Hetfield', 2008, 0, 3, 10, 1, 2, 1, NULL,
                20, 10, 10, 1, 0, 200, 100, 100, 100, NULL, 100, 1, 103),
            (102, 'Intro', '', 'Unknown Album', NULL, NULL, NULL, 'Intro', '', '', NULL,
                NULL, 0, 0, 1, 0, 0, 0, 0, NULL, 29, 19, 19, 2, 0, 100, 300, 200, 200, NULL,
                200, 0, 0);
        """
    )
    lib.commit()
    lib.close()
    return d


def _add(lib, title, artist, album, n=1):
    return lib.add_track(TrackMeta(location=f"F00/{title[:4]}.mp3", title=title,
                                   artist=artist, album=album, track_number=n), date=0)


def _get(cx, sql, *args):
    return cx.execute(sql, args).fetchone()


def test_new_album_belongs_to_the_tracks_artist(tmp_path):
    lib = ItlpLibrary(_make_itlp(tmp_path))
    try:
        pid = _add(lib, "Papercut", "Linkin Park", "Hybrid Theory")
        _add(lib, "One Step Closer", "Linkin Park", "Hybrid Theory", 2)
        cx = lib.cx["Library.itdb"]
        lp = _get(cx, "SELECT pid, name_order FROM artist WHERE name='Linkin Park'")
        album = _get(cx, "SELECT * FROM album WHERE name='Hybrid Theory'")
        assert _get(cx, "SELECT album_pid FROM item WHERE pid=?", pid)[0] == album["pid"]
        assert album["artist_pid"] == lp["pid"]
        assert album["artist_order"] == lp["name_order"]
        # counts and flags describe this album, not the template's
        assert (album["item_count"], album["artist_count_calc"]) == (2, 1)
        assert (album["all_compilations"], album["has_any_compilations"]) == (0, 0)
        assert (album["artwork_status"], album["artwork_item_pid"]) == (0, 0)
    finally:
        lib.close()


def test_same_album_name_by_another_artist_gets_its_own_row(tmp_path):
    lib = ItlpLibrary(_make_itlp(tmp_path))
    try:
        _add(lib, "Numb", "Linkin Park", "Greatest Hits")
        cx = lib.cx["Library.itdb"]
        rows = cx.execute("SELECT al.pid, a.name FROM album al JOIN artist a ON a.pid=al.artist_pid "
                          "WHERE al.name='Greatest Hits' ORDER BY a.name").fetchall()
        assert [r["name"] for r in rows] == ["Linkin Park", "Metallica"]
        assert rows[1]["pid"] == 21                  # Metallica's album is untouched
        new = _get(cx, "SELECT album_pid FROM item WHERE title='Numb'")[0]
        assert new == rows[0]["pid"]
    finally:
        lib.close()


def test_new_track_inherits_nothing_from_the_template_track(tmp_path):
    lib = ItlpLibrary(_make_itlp(tmp_path))
    try:
        pid = _add(lib, "Papercut", "Linkin Park", "Hybrid Theory")
        cx = lib.cx["Library.itdb"]
        new = _get(cx, "SELECT * FROM item WHERE pid=?", pid)
        for col in ("album_artist", "sort_album_artist", "composer", "sort_composer", "comment"):
            assert new[col] is None, col
        for col in ("is_compilation", "track_count", "disc_number", "disc_count",
                    "artwork_status", "artwork_cache_id"):
            assert new[col] == 0, col
        # no composer: the Unknown Composer row, sorted after the last named composer
        assert (new["composer_pid"], new["composer_order"]) == (2, 200)
    finally:
        lib.close()


def test_counts_follow_the_tracks_on_add_and_remove(tmp_path):
    lib = ItlpLibrary(_make_itlp(tmp_path))
    try:
        _add(lib, "Papercut", "Linkin Park", "Hybrid Theory")
        numb = _add(lib, "Numb", "Linkin Park", "Meteora")
        cx = lib.cx["Library.itdb"]
        # the artist row is cloned from Metallica's (album_count 3): counted, not inherited
        assert _get(cx, "SELECT album_count FROM artist WHERE name='Linkin Park'")[0] == 2
        assert _get(cx, "SELECT album_count FROM track_artist WHERE name='Linkin Park'")[0] == 2
        assert _get(cx, "SELECT album_count FROM artist WHERE name='Metallica'")[0] == 1
        assert _get(cx, "SELECT item_count FROM album WHERE name='Meteora'")[0] == 1

        lib.remove_track(numb)
        assert _get(cx, "SELECT album_count FROM artist WHERE name='Linkin Park'")[0] == 1
        assert _get(cx, "SELECT album_count FROM track_artist WHERE name='Linkin Park'")[0] == 1
    finally:
        lib.close()


def test_unknown_artist_sorts_after_the_last_name(tmp_path):
    lib = ItlpLibrary(_make_itlp(tmp_path))
    try:
        _add(lib, "Papercut", "Linkin Park", "Hybrid Theory")
        cx = lib.cx["Library.itdb"]
        # Linkin Park 100, Metallica 200; with no empty-name rows Unknown gets 300
        intro = _get(cx, "SELECT artist_order, album_artist_order FROM item WHERE pid=102")
        assert tuple(intro) == (300, 300)
    finally:
        lib.close()
