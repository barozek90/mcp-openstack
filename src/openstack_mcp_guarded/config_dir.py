"""Injection of a cloud-config directory (clouds.yaml + secure.yaml).

openstacksdk reads *files*, not directories: ``OS_CLIENT_CONFIG_FILE`` and
``OS_CLIENT_SECURE_FILE`` are prepended to its search path (first existing
file wins; the secure file is merged into the matching cloud). This module
maps a single directory onto those two variables, so a launcher (wrapper
script, container volume, secret mount) only has to hand over one path:

    OS_MCP_GUARD_CONFIG_DIR=/run/user/1000/openstack

The directory must contain ``clouds.yaml`` (``.yml``/``.json`` also work) and
may contain ``secure.yaml``. Variables already set explicitly win.
"""

from __future__ import annotations

import os
import stat
import sys
from collections.abc import MutableMapping
from pathlib import Path

CONFIG_DIR_ENV = "OS_MCP_GUARD_CONFIG_DIR"
_SUFFIXES = (".yaml", ".yml", ".json")


class ConfigDirError(RuntimeError):
    """The configured directory is unusable (reported at startup)."""


def _stderr(msg: str) -> None:
    """Write to stderr (never stdout: stdio transport)."""
    print(msg, file=sys.stderr, flush=True)


def _find(directory: Path, stem: str) -> Path | None:
    for suffix in _SUFFIXES:
        candidate = directory / f"{stem}{suffix}"
        if candidate.is_file():
            return candidate
    return None


def apply_config_dir(
    environ: MutableMapping[str, str] | None = None,
) -> Path | None:
    """Point openstacksdk at ``$OS_MCP_GUARD_CONFIG_DIR``, if it is set.

    :param environ: Mapping to read/update (defaults to ``os.environ``).
    :return: The directory in use, or ``None`` when the variable is unset.
    :raises ConfigDirError: Directory missing or without a clouds file.
    """
    env = os.environ if environ is None else environ
    # Consume the variable: openstacksdk turns any other OS_* variable into
    # a bogus "envvars" cloud, which would show up in get_cloud_names.
    raw = env.pop(CONFIG_DIR_ENV, "").strip()
    if not raw:
        return None

    directory = Path(raw).expanduser()
    if not directory.is_dir():
        raise ConfigDirError(f"{CONFIG_DIR_ENV}={directory}: not a directory")

    clouds = _find(directory, "clouds")
    if clouds is None:
        raise ConfigDirError(
            f"{CONFIG_DIR_ENV}={directory}: no clouds.yaml "
            f"(or .yml/.json) in the directory"
        )
    env.setdefault("OS_CLIENT_CONFIG_FILE", str(clouds))

    secure = _find(directory, "secure")
    if secure is not None:
        env.setdefault("OS_CLIENT_SECURE_FILE", str(secure))
        if secure.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
            _stderr(
                f"[mcp-openstack] WARNING {secure} is accessible "
                f"by group/others; run 'chmod 600 {secure}'"
            )
    return directory


def canonical_cloud_name(name: str) -> str:
    """Resolve ``name`` against the configured clouds, ignoring case.

    openstacksdk cloud names are case-sensitive. An exact match wins; a
    single case-insensitive match is mapped to its real spelling;
    anything else (no match, ambiguous, config unreadable) is returned
    unchanged so the existing "no cloud selected" guard reports it.
    """
    try:
        from openstack.config.loader import OpenStackConfig

        names = list(OpenStackConfig().get_cloud_names())
    except Exception:  # noqa: BLE001 - best-effort normalisation
        return name
    if name in names:
        return name
    matches = [n for n in names if n.casefold() == name.casefold()]
    return matches[0] if len(matches) == 1 else name
