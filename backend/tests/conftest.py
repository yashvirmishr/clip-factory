import os
import tempfile

# Must happen before any clipper import: config reads the env at import time.
os.environ.setdefault("CLIPPER_DATA_DIR", tempfile.mkdtemp(prefix="clipper-test-"))

import pytest  # noqa: E402

from clipper import db  # noqa: E402
from clipper.config import SETTINGS  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _init_db():
    db.init()
    yield
    SETTINGS.ensure_dirs()


@pytest.fixture
def clean_db():
    db.init()
    with db.connect() as conn:
        for table in ("decisions", "hook_edits", "analyses", "sources", "state"):
            conn.execute(f"DELETE FROM {table}")
    yield
    with db.connect() as conn:
        for table in ("decisions", "hook_edits", "analyses", "sources", "state"):
            conn.execute(f"DELETE FROM {table}")
