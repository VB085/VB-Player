"""QSortFilterProxyModel subclass for filtering and sorting playlists."""

from PyQt6.QtCore import Qt, QSortFilterProxyModel, QRegularExpression, QModelIndex


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

    def moveRows(self, source_parent, source_row, count, dest_parent, dest_child):
        """Map proxy indices to source and delegate move."""
        src_model = self.sourceModel()
        if src_model is None or not hasattr(src_model, 'moveRows'):
            return False
        src_row = self.mapToSource(self.index(source_row, 0, source_parent)).row()
        # dest_child is relative to dest_parent; map it
        if dest_child >= self.rowCount(dest_parent):
            dest_src_row = src_model.rowCount()
        else:
            dest_src_row = self.mapToSource(self.index(dest_child, 0, dest_parent)).row()
        return src_model.moveRows(QModelIndex(), src_row, count, QModelIndex(), dest_src_row)
