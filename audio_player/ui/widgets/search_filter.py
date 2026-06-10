"""QSortFilterProxyModel subclass for filtering and sorting playlists."""

from PyQt6.QtCore import Qt, QSortFilterProxyModel, QRegularExpression


class PlaylistFilterProxy(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._sort_role = Qt.ItemDataRole.DisplayRole

    def setSortRole(self, role: int):
        self._sort_role = role

    def lessThan(self, left, right):
        l = left.data(self._sort_role)
        r = right.data(self._sort_role)
        # Handle None/empty
        if l is None:
            return True
        if r is None:
            return False
        # Numeric comparison for duration
        if self._sort_role in (getattr(left.model(), 'DurationRole', -1),):
            try:
                return float(l) < float(r)
            except (ValueError, TypeError):
                return False
        # String comparison (case-insensitive)
        return str(l).lower() < str(r).lower()

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
