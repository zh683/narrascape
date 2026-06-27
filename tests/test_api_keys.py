from __future__ import annotations


def test_env_file_is_cached_until_reset(monkeypatch):
    from narrascape.api_keys import APIKeys

    calls = []

    def fake_load_env_file():
        calls.append("read")
        return {"ARK_API_KEY": "cached-key"}

    APIKeys.reset_cache()
    monkeypatch.setattr("narrascape.api_keys.load_env_file", fake_load_env_file)
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    try:
        assert APIKeys.ark() == "cached-key"
        assert APIKeys.ark() == "cached-key"
        assert calls == ["read"]

        APIKeys.reset_cache()
        assert APIKeys.ark() == "cached-key"
        assert calls == ["read", "read"]
    finally:
        APIKeys.reset_cache()
