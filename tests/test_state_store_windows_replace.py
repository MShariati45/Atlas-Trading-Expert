from pathlib import Path
from unittest.mock import patch

from atlas.core.state_store import JsonFileStateStore


def test_json_store_retries_transient_permission_error(tmp_path):
    path = tmp_path / "state.json"
    store = JsonFileStateStore(path)
    real_replace = __import__("os").replace
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError(13, "transient Windows access denied")
        return real_replace(src, dst)

    with patch("atlas.core.state_store.os.replace", side_effect=flaky), \
         patch("atlas.core.state_store.time.sleep", return_value=None):
        store.set("hello", {"value": 42})

    assert calls["n"] == 3
    assert store.get("hello") == {"value": 42}


def test_json_store_cleans_temp_after_success(tmp_path):
    path = tmp_path / "state.json"
    store = JsonFileStateStore(path)
    store.set("x", 1)
    assert list(tmp_path.glob("state.json.*.tmp")) == []
