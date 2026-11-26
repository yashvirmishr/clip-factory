import logging
import os
import shutil
import tempfile

# Must happen before any clipper import: config reads the env at import time.
_TEST_DATA_DIR: str | None = None
if "CLIPPER_DATA_DIR" not in os.environ:
    _TEST_DATA_DIR = tempfile.mkdtemp(prefix="clipper-test-")
    os.environ["CLIPPER_DATA_DIR"] = _TEST_DATA_DIR
os.environ.setdefault("CLIPPER_SECRET_BACKEND", "memory")
os.environ.setdefault("CLIPPER_DISABLE_WEEKLY", "1")
os.environ.setdefault("CLIPPER_DISABLE_PUBLISH_SCHEDULER", "1")
os.environ.setdefault("CLIPPER_DISABLE_REVOKE", "1")

import pytest  # noqa: E402

from clipper import db, policy, secrets  # noqa: E402
from clipper.config import SETTINGS  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_secrets():
    secrets.configure(secrets.MemorySecretStore())
    yield
    secrets.reset()


@pytest.fixture(scope="session", autouse=True)
def _init_db():
    db.init()
    yield
    SETTINGS.ensure_dirs()
    # Only remove the directory this suite created; an explicit
    # CLIPPER_DATA_DIR points at real user data and is left untouched.
    if _TEST_DATA_DIR:
        test_root = os.path.abspath(_TEST_DATA_DIR)
        for logger in [logging.getLogger(), *logging.Logger.manager.loggerDict.values()]:
            if not isinstance(logger, logging.Logger):
                continue
            for handler in list(logger.handlers):
                filename = getattr(handler, "baseFilename", "")
                if filename and os.path.abspath(filename).startswith(test_root + os.sep):
                    logger.removeHandler(handler)
                    handler.close()
        shutil.rmtree(_TEST_DATA_DIR, ignore_errors=True)


@pytest.fixture
def clean_db():
    db.init()
    policy.clear_for_tests()
    with db.connect() as conn:
        for table in (
            "suggestions", "personal_models", "post_metrics", "posts", "publish_jobs",
            "account_snapshots", "accounts", "decisions", "hook_edits", "clip_edits",
            "analyses", "sources", "state",
        ):
            conn.execute(f"DELETE FROM {table}")
    yield
    with db.connect() as conn:
        for table in (
            "suggestions", "personal_models", "post_metrics", "posts", "publish_jobs",
            "account_snapshots", "accounts", "decisions", "hook_edits", "clip_edits",
            "analyses", "sources", "state",
        ):
            conn.execute(f"DELETE FROM {table}")
