"""Verify domain packages export their canonical shapes and functions."""

import crabriks.agent as agent_pkg
import crabriks.api as api_pkg
import crabriks.capabilities as cap_pkg
import crabriks.store as store_pkg


def test_domain_agent_exports() -> None:
    assert hasattr(agent_pkg, "crabriks_agent")
    assert hasattr(agent_pkg, "run_turn")
    assert hasattr(agent_pkg, "build_system_prompt")
    assert hasattr(agent_pkg, "to_model_messages")
    assert hasattr(agent_pkg, "select_model")


def test_domain_capabilities_exports() -> None:
    assert hasattr(cap_pkg, "skills_capability")
    assert hasattr(cap_pkg, "mcp_capability")
    assert hasattr(cap_pkg, "load_mcp_tools")
    assert hasattr(cap_pkg, "resolve_agent_workspace")
    assert hasattr(cap_pkg, "load_bootstrap")


def test_domain_api_exports() -> None:
    assert hasattr(api_pkg, "create_app")
    assert hasattr(api_pkg, "resolve_caller")


def test_domain_store_exports() -> None:
    assert hasattr(store_pkg, "open_store")
    assert hasattr(store_pkg, "MemorySessionStore")
    assert hasattr(store_pkg, "LakebaseSessionStore")
    assert hasattr(store_pkg, "TranscriptEntry")
    assert hasattr(store_pkg, "ApprovalEntry")
