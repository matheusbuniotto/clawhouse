from clawhouse.settings import app_env, settings_from_env
from clawhouse.store.store import MemorySessionStore, open_store


def test_new_name_wins_over_legacy():
    env = {"CLAWHOUSE_DEV_USER": "new@x", "CRABRIKS_DEV_USER": "old@x"}
    assert app_env(env, "CLAWHOUSE_DEV_USER") == "new@x"


def test_falls_back_to_legacy_name():
    env = {"CRABRIKS_DEV_USER": "old@x", "CRABRIKS_SENSITIVE_TOOLS": "bash"}
    settings = settings_from_env(env)
    assert settings.dev_user == "old@x"
    assert settings.sensitive_tools == ("bash",)


def test_unset_returns_none():
    assert app_env({}, "CLAWHOUSE_MODELS") is None


async def test_store_honours_legacy_memory_flag():
    store = await open_store({"CRABRIKS_STORE": "memory"})
    assert isinstance(store, MemorySessionStore)
