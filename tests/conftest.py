import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

QUICKML_VARS = ["QUICKML_ENDPOINT_URL", "QUICKML_ENDPOINT_KEY", "CATALYST_ORG", "QUICKML_TOKEN", "QUICKML_FEATURES",
                "QUICKML_PAYLOAD_MODE", "ZOHO_REFRESH_TOKEN", "ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET"]


@pytest.fixture(autouse=True)
def no_quickml_env(monkeypatch):
    """Every test starts with QuickML unconfigured, regardless of the developer's own .env."""
    for v in QUICKML_VARS:
        monkeypatch.delenv(v, raising=False)
