"""ipodsync — upload music to iPod nano 6G/7G without iTunes/Apple Music.

Transport is a plain volume (mass storage); it edits the SQLite library
`iTunes Library.itlp` and the `Locations.itdb.cbk` signature (hashAB). Cover art
is written in pure Python (ArtworkDB + .ithmb). Knows nothing about where the
files came from.

Public API:
    from ipodsync import find_ipod, ItlpLibrary, Track, HashAB
"""
from .hashab import HashAB, HashABError
from .library import ItlpLibrary
from .models import Track
from .transport import IPod, IPodNotFound, find_ipod

__version__ = "0.1.3"

__all__ = [
    "find_ipod",
    "IPod",
    "IPodNotFound",
    "ItlpLibrary",
    "Track",
    "HashAB",
    "HashABError",
    "__version__",
]
