"""The Databricks serving endpoint and OpenAI-compatible providers are chat models."""

import json

import pytest

from crabriks.model import (
    MissingAccessToken,
    MissingModelConfig,
    ModelEntry,
    UnknownModel,
    databricks_chat_model,
    openai_compatible_chat_model,
    select_model,
)
from crabriks.settings import models_from_env, request_token

COMPATIBLE = {
    "id": "openrouter-llama",
    "label": "Llama 3.3 70B · OpenRouter",
    "model": "meta-llama/llama-3.3-70b-instruct",
    "base_url": "https://openrouter.ai/api/v1",
    "api_key_env": "OPENROUTER_API_KEY",
}


def test_user_token_targets_the_workspace_serving_endpoint() -> None:
    model = databricks_chat_model(
        endpoint="databricks-meta-llama-3-3-70b-instruct",
        workspace_host="https://adb-1.azuredatabricks.net",
        access_token="dapi-" + "user",
    )

    assert model.model_name == "databricks-meta-llama-3-3-70b-instruct"
    assert str(model.base_url).rstrip("/") == (
        "https://adb-1.azuredatabricks.net/serving-endpoints"
    )
    assert model.client.api_key == "dapi-user"


def test_a_missing_token_is_refused() -> None:
    with pytest.raises(MissingAccessToken):
        databricks_chat_model(
            endpoint="databricks-meta-llama-3-3-70b-instruct",
            workspace_host="https://adb-1.azuredatabricks.net",
            access_token="",
        )


def test_forwarded_token_wins_over_the_dev_token() -> None:
    assert (
        request_token(
            forwarded="dapi-" + "user",
            user_id="ada@example.com",
            dev_user="ada@example.com",
            dev_token="dapi-" + "dev",
        )
        == "dapi-user"
    )
    assert (
        request_token(
            forwarded="",
            user_id="ada@example.com",
            dev_user="ada@example.com",
            dev_token="dapi-" + "dev",
        )
        == "dapi-dev"
    )
    assert (
        request_token(
            forwarded="",
            user_id="grace@example.com",
            dev_user="ada@example.com",
            dev_token="dapi-" + "dev",
        )
        == ""
    )


def test_a_missing_endpoint_is_refused() -> None:
    with pytest.raises(MissingModelConfig):
        databricks_chat_model(
            endpoint="",
            workspace_host="https://adb-1.azuredatabricks.net",
            access_token="dapi-" + "user",
        )


def test_a_compatible_endpoint_uses_its_own_key() -> None:
    model = openai_compatible_chat_model(
        model="meta-llama/llama-3.3-70b-instruct",
        base_url="https://openrouter.ai/api/v1",
        api_key="sk-or-" + "secret",
    )

    assert model.model_name == "meta-llama/llama-3.3-70b-instruct"
    assert str(model.base_url).rstrip("/") == "https://openrouter.ai/api/v1"
    assert model.client.api_key == "sk-or-secret"


def test_a_compatible_endpoint_without_a_key_is_refused() -> None:
    with pytest.raises(MissingModelConfig):
        openai_compatible_chat_model(
            model="meta-llama/llama-3.3-70b-instruct",
            base_url="https://openrouter.ai/api/v1",
            api_key="",
        )


def test_the_catalog_keeps_databricks_as_the_default() -> None:
    models = models_from_env(
        {
            "SERVING_ENDPOINT": "databricks-meta-llama-3-3-70b-instruct",
            "DATABRICKS_HOST": "https://adb-1.azuredatabricks.net",
            "CRABRIKS_MODELS": json.dumps([COMPATIBLE]),
        }
    )

    assert [entry.id for entry in models] == ["databricks", "openrouter-llama"]
    assert models[0].is_default is True
    assert models[1].is_default is False
    assert models[1].base_url == "https://openrouter.ai/api/v1"
    assert models[1].api_key_env == "OPENROUTER_API_KEY"


def test_the_first_compatible_model_is_default_without_databricks() -> None:
    models = models_from_env({"CRABRIKS_MODELS": json.dumps([COMPATIBLE])})

    assert [entry.id for entry in models] == ["openrouter-llama"]
    assert models[0].is_default is True


def test_select_model_defaults_then_matches_by_id() -> None:
    entries = (
        ModelEntry(
            id="databricks",
            label="Databricks",
            provider="databricks",
            model="endpoint",
            is_default=True,
        ),
        ModelEntry(
            id="openrouter-llama",
            label="Llama",
            provider="openai_compatible",
            model="meta-llama/llama-3.3-70b-instruct",
            base_url="https://openrouter.ai/api/v1",
            api_key_env="OPENROUTER_API_KEY",
        ),
    )

    assert select_model(entries, None).id == "databricks"
    assert select_model(entries, "openrouter-llama").id == "openrouter-llama"
    with pytest.raises(UnknownModel):
        select_model(entries, "missing")
