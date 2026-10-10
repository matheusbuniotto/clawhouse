"""The Databricks serving endpoint is an OpenAI-compatible chat model."""

import pytest

from crabriks.model import MissingAccessToken, MissingModelConfig, databricks_chat_model
from crabriks.settings import request_token


def test_user_token_targets_the_workspace_serving_endpoint() -> None:
    model = databricks_chat_model(
        endpoint="databricks-meta-llama-3-3-70b-instruct",
        workspace_host="https://adb-1.azuredatabricks.net",
        access_token="dapi-user",
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
            forwarded="dapi-user",
            user_id="ada@example.com",
            dev_user="ada@example.com",
            dev_token="dapi-dev",
        )
        == "dapi-user"
    )
    assert (
        request_token(
            forwarded="",
            user_id="ada@example.com",
            dev_user="ada@example.com",
            dev_token="dapi-dev",
        )
        == "dapi-dev"
    )
    assert (
        request_token(
            forwarded="",
            user_id="grace@example.com",
            dev_user="ada@example.com",
            dev_token="dapi-dev",
        )
        == ""
    )


def test_a_missing_endpoint_is_refused() -> None:
    with pytest.raises(MissingModelConfig):
        databricks_chat_model(
            endpoint="",
            workspace_host="https://adb-1.azuredatabricks.net",
            access_token="dapi-user",
        )
