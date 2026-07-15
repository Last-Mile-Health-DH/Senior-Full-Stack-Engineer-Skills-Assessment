"""Shared pytest configuration for backend deterministic tests."""

from __future__ import annotations

import os

os.environ.setdefault("ASSESSMENT_TESTING", "1")
