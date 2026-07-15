"""Row templates for adding a track to an EMPTY .itlp library.

SYNTHETIC: all string fields are blanked (personal data removed); pid/order are
overwritten in library.add_track. Regenerate with tools/gen_lib_templates.py
(from a local backup — the backup is not part of the public repo).
"""

ITEM_TEMPLATE = {'pid': -9216401694829997841, 'revision_level': None, 'media_kind': 1, 'is_song': 1, 'is_audio_book': 0, 'is_music_video': 0, 'is_movie': 0, 'is_tv_show': 0, 'is_home_video': 0, 'is_ringtone': 0, 'is_tone': 0, 'is_voice_memo': 0, 'is_book': 0, 'is_rental': 0, 'is_itunes_u': 0, 'is_digital_booklet': 0, 'is_podcast': 0, 'date_modified': 758845134, 'year': 2013, 'content_rating': 0, 'content_rating_level': 0, 'is_compilation': 0, 'is_user_disabled': 0, 'remember_bookmark': 0, 'exclude_from_shuffle': 0, 'part_of_gapless_album': 0, 'chosen_by_auto_fill': 0, 'artwork_status': 0, 'artwork_cache_id': 0, 'start_time_ms': 0.0, 'stop_time_ms': 0.0, 'total_time_ms': 224888.0, 'total_burn_time_ms': None, 'track_number': 3, 'track_count': 0, 'disc_number': 0, 'disc_count': 0, 'bpm': 0, 'relative_volume': 0, 'eq_preset': None, 'radio_stream_status': None, 'genius_id': 0, 'genre_id': 12, 'category_id': 0, 'album_pid': -8778576643414911648, 'artist_pid': 3083228396371532061, 'composer_pid': 0, 'title': '', 'artist': '', 'album': '', 'album_artist': '', 'composer': None, 'sort_title': '', 'sort_artist': '', 'sort_album': '', 'sort_album_artist': '', 'sort_composer': None, 'title_order': 89300, 'artist_order': 53900, 'album_order': 32300, 'genre_order': 4700, 'composer_order': 200, 'album_artist_order': 44400, 'album_by_artist_order': None, 'series_name_order': 100, 'comment': None, 'grouping': None, 'description': None, 'description_long': None, 'collection_description': None, 'copyright': None, 'track_artist_pid': 539, 'physical_order': 1245, 'has_lyrics': 0, 'date_released': 0}

ARTIST_TEMPLATE = {'pid': -9211478403244814981, 'kind': 2, 'artwork_status': 0, 'artwork_album_pid': 0, 'name': '', 'name_order': 26600, 'sort_name': '', 'is_unknown': 0, 'has_songs': 1, 'has_music_videos': 0, 'has_non_compilation_tracks': 1, 'album_count': 1}

ALBUM_TEMPLATE = {'pid': -9152521762437827186, 'kind': 2, 'artwork_status': 0, 'artwork_item_pid': 0, 'artist_pid': -8213557128273776184, 'user_rating': 0, 'name': '', 'name_order': 4600, 'all_compilations': 0, 'feed_url': None, 'season_number': 0, 'is_unknown': 0, 'has_songs': 1, 'has_music_videos': 0, 'sort_order': 4600, 'artist_order': 2600, 'has_any_compilations': 0, 'sort_name': '', 'artist_count_calc': 1, 'has_movies': 0, 'item_count': 1, 'min_volume_normalization_energy': 2438}

TRACK_ARTIST_TEMPLATE = {'pid': 1, 'name': '', 'name_order': 100, 'sort_name': '', 'has_songs': 1, 'has_music_videos': 0, 'has_non_compilation_tracks': 1, 'is_unknown': 0, 'album_count': 1}

LOCATION_TEMPLATE = {'item_pid': -7383142142304564027, 'sub_id': 0, 'base_location_id': 1, 'location_type': 1179208773, 'location': '', 'extension': 1297101600, 'kind_id': 1, 'date_created': 737588774, 'file_size': 2192482, 'file_creator': None, 'file_type': None, 'num_dir_levels_file': None, 'num_dir_levels_lib': None}
