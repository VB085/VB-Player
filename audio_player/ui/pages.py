"""Content stack page indices."""

from enum import IntEnum


class Page(IntEnum):
    SONGS = 0
    ALBUMS = 1
    MANAGE = 2
    ALBUM_DETAIL = 3
    FAVORITES = 4
    PLAYLISTS = 5
    PLAYLIST_DETAIL = 6
    NETWORK = 7
