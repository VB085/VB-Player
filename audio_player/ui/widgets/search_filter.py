"""QSortFilterProxyModel subclass for filtering playlists by title/artist/album."""

from PyQt6.QtCore import Qt, QSortFilterProxyModel, QRegularExpression


class PlaylistFilterProxy(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    def filterAcceptsRow(self, source_row, source_parent):
        pattern = self.filterRegularExpression().pattern()
        if not pattern:
            return True
        model = self.sourceModel()
        if model is None:
            return True
        idx = model.index(source_row, 0, source_parent)
        title = (idx.data(model.TitleRole) or "").lower()
        artist = (idx.data(model.ArtistRole) or "").lower()
        album = (idx.data(model.AlbumRole) or "").lower()
        p = pattern.lower()
        return p in title or p in artist or p in album
