"""Shared fixtures for VB Player tests."""

import pytest
from PyQt6.QtWidgets import QApplication
import sys


@pytest.fixture(scope="session")
def qapp():
    """Ensure a QApplication instance exists for the test session."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app
