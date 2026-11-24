"""Tests for OS_MCP_GUARD_CONFIG_DIR injection and cloud-name normalisation."""

from __future__ import annotations

import os

import pytest
from openstack.config.loader import OpenStackConfig

from openstack_mcp_guarded.config_dir import (
    CONFIG_DIR_ENV,
    ConfigDirError,
    apply_config_dir,
    canonical_cloud_name,
)

CLOUDS = """\
clouds:
  EXAMPLE-CLOUD:
    auth:
      auth_url: https://keystone.example:5000/v3
      username: tester
      user_domain_name: Default
      project_name: admin
      project_domain_name: Default
    region_name: EXAMPLE-CLOUD
"""
SECURE = """\
clouds:
  EXAMPLE-CLOUD:
    auth:
      password: s3cret
"""


@pytest.fixture
def cfg_dir(tmp_path):
    (tmp_path / "clouds.yaml").write_text(CLOUDS)
    secure = tmp_path / "secure.yaml"
    secure.write_text(SECURE)
    secure.chmod(0o600)
    return tmp_path


def test_unset_is_noop():
    env: dict[str, str] = {}
    assert apply_config_dir(env) is None
    assert env == {}


def test_sets_both_files(cfg_dir):
    env = {CONFIG_DIR_ENV: str(cfg_dir)}
    assert apply_config_dir(env) == cfg_dir
    assert env["OS_CLIENT_CONFIG_FILE"] == str(cfg_dir / "clouds.yaml")
    assert env["OS_CLIENT_SECURE_FILE"] == str(cfg_dir / "secure.yaml")
    # consumed, so the SDK does not invent an "envvars" cloud from it
    assert CONFIG_DIR_ENV not in env


def test_secure_file_is_optional(tmp_path):
    (tmp_path / "clouds.yaml").write_text(CLOUDS)
    env = {CONFIG_DIR_ENV: str(tmp_path)}
    apply_config_dir(env)
    assert "OS_CLIENT_SECURE_FILE" not in env


def test_explicit_variables_win(cfg_dir):
    env = {
        CONFIG_DIR_ENV: str(cfg_dir),
        "OS_CLIENT_CONFIG_FILE": "/explicit/clouds.yaml",
    }
    apply_config_dir(env)
    assert env["OS_CLIENT_CONFIG_FILE"] == "/explicit/clouds.yaml"


def test_missing_directory_errors(tmp_path):
    with pytest.raises(ConfigDirError, match="not a directory"):
        apply_config_dir({CONFIG_DIR_ENV: str(tmp_path / "nope")})


def test_missing_clouds_file_errors(tmp_path):
    with pytest.raises(ConfigDirError, match="no clouds.yaml"):
        apply_config_dir({CONFIG_DIR_ENV: str(tmp_path)})


def test_warns_on_loose_secure_permissions(cfg_dir, capsys):
    (cfg_dir / "secure.yaml").chmod(0o644)
    apply_config_dir({CONFIG_DIR_ENV: str(cfg_dir)})
    assert "WARNING" in capsys.readouterr().err


def test_no_warning_for_private_secure_file(cfg_dir, capsys):
    apply_config_dir({CONFIG_DIR_ENV: str(cfg_dir)})
    assert capsys.readouterr().err == ""


def test_sdk_reads_injected_directory(cfg_dir, monkeypatch):
    env: dict[str, str] = {CONFIG_DIR_ENV: str(cfg_dir)}
    apply_config_dir(env)
    for key in ("OS_CLIENT_CONFIG_FILE", "OS_CLIENT_SECURE_FILE"):
        monkeypatch.setenv(key, env[key])

    cfg = OpenStackConfig()
    assert cfg.get_cloud_names() == ["EXAMPLE-CLOUD"]
    auth = cfg.get_one("EXAMPLE-CLOUD").config["auth"]
    assert auth["password"] == "s3cret"
    assert auth["auth_url"] == "https://keystone.example:5000/v3"


def test_canonical_cloud_name(cfg_dir, monkeypatch):
    monkeypatch.setenv("OS_CLIENT_CONFIG_FILE", str(cfg_dir / "clouds.yaml"))
    monkeypatch.setenv("OS_CLIENT_SECURE_FILE", str(cfg_dir / "secure.yaml"))
    assert canonical_cloud_name("example-cloud") == "EXAMPLE-CLOUD"
    assert canonical_cloud_name("EXAMPLE-CLOUD") == "EXAMPLE-CLOUD"
    assert canonical_cloud_name("other") == "other"


def test_canonical_cloud_name_ambiguous_is_unchanged(tmp_path, monkeypatch):
    (tmp_path / "clouds.yaml").write_text(
        "clouds:\n  Cloud1: {auth: {}}\n  cloud1: {auth: {}}\n"
    )
    monkeypatch.setenv("OS_CLIENT_CONFIG_FILE", str(tmp_path / "clouds.yaml"))
    assert canonical_cloud_name("CLOUD1") == "CLOUD1"
    assert canonical_cloud_name("cloud1") == "cloud1"


def test_main_exits_cleanly_on_bad_dir(tmp_path, monkeypatch, capsys):
    from openstack_mcp_guarded.server import main

    monkeypatch.setenv(CONFIG_DIR_ENV, str(tmp_path / "nope"))
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    assert "ERROR" in capsys.readouterr().err
    assert os.environ.get("OS_CLIENT_CONFIG_FILE") != str(tmp_path / "nope")
