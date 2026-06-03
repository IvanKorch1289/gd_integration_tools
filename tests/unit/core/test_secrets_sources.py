"""Tests for secrets_sources module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.backend.core.secrets_sources import (
    AwsSecretsManagerSource,
    VaultSettingsSource,
)


class TestVaultSettingsSource:
    def test_no_env_returns_empty(self) -> None:
        src = VaultSettingsSource(object, "secret/app")
        with patch.dict("os.environ", {}, clear=True):
            data = src._load()
        assert data == {}

    def test_hvac_not_installed_returns_empty(self) -> None:
        src = VaultSettingsSource(object, "secret/app")
        env = {"VAULT_ADDR": "http://vault:8200", "VAULT_TOKEN": "tok"}
        with patch.dict("os.environ", env, clear=True):
            with patch.dict("sys.modules", {"hvac": None}):
                data = src._load()
        assert data == {}

    def test_hvac_success(self) -> None:
        src = VaultSettingsSource(object, "secret/app")
        env = {"VAULT_ADDR": "http://vault:8200", "VAULT_TOKEN": "tok"}
        mock_client = MagicMock()
        mock_client.secrets.kv.v2.read_secret_version.return_value = {
            "data": {"data": {"db_password": "secret123"}}
        }
        with patch.dict("os.environ", env, clear=True):
            with patch("hvac.Client", return_value=mock_client):
                data = src._load()
        assert data == {"db_password": "secret123"}

    def test_hvac_exception_returns_empty(self) -> None:
        src = VaultSettingsSource(object, "secret/app")
        env = {"VAULT_ADDR": "http://vault:8200", "VAULT_TOKEN": "tok"}
        with patch.dict("os.environ", env, clear=True):
            with patch("hvac.Client", side_effect=Exception("conn refused")):
                data = src._load()
        assert data == {}

    def test_call_returns_data(self) -> None:
        src = VaultSettingsSource(object, "secret/app")
        with patch.object(src, "_load", return_value={"k": "v"}):
            assert src() == {"k": "v"}

    def test_get_field_value_hit(self) -> None:
        src = VaultSettingsSource(object, "secret/app")
        with patch.object(src, "_load", return_value={"k": "v"}):
            val, name, is_json = src.get_field_value(None, "k")
        assert val == "v"
        assert name == "k"
        assert is_json is False

    def test_get_field_value_miss(self) -> None:
        src = VaultSettingsSource(object, "secret/app")
        with patch.object(src, "_load", return_value={}):
            val, name, is_json = src.get_field_value(None, "k")
        assert val is None


class TestAwsSecretsManagerSource:
    def test_boto3_not_installed(self) -> None:
        src = AwsSecretsManagerSource(object, "my-secret")
        with patch.dict("sys.modules", {"boto3": None}):
            data = src._load()
        assert data == {}

    def test_success(self) -> None:
        src = AwsSecretsManagerSource(object, "my-secret")
        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {
            "SecretString": '{"api_key": "abc"}'
        }
        mock_boto3 = MagicMock()
        mock_boto3.client = MagicMock(return_value=mock_client)
        mock_orjson = MagicMock()
        mock_orjson.loads = __import__("json").loads
        with patch.dict(
            "sys.modules", {"boto3": mock_boto3, "orjson": mock_orjson}
        ):
            data = src._load()
        assert data == {"api_key": "abc"}

    def test_exception_returns_empty(self) -> None:
        src = AwsSecretsManagerSource(object, "my-secret")
        mock_boto3 = MagicMock()
        mock_boto3.client = MagicMock(side_effect=Exception("aws down"))
        mock_orjson = MagicMock()
        mock_orjson.loads = __import__("json").loads
        with patch.dict(
            "sys.modules", {"boto3": mock_boto3, "orjson": mock_orjson}
        ):
            data = src._load()
        assert data == {}

    def test_call(self) -> None:
        src = AwsSecretsManagerSource(object, "my-secret")
        with patch.object(src, "_load", return_value={"k": "v"}):
            assert src() == {"k": "v"}

    def test_get_field_value(self) -> None:
        src = AwsSecretsManagerSource(object, "my-secret")
        with patch.object(src, "_load", return_value={"k": "v"}):
            val, name, is_json = src.get_field_value(None, "k")
        assert val == "v"
        assert is_json is False
