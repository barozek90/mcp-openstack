"""Regression test for the upstream ``delete_on_termination`` null bug.

Nova can return ``null`` for a volume attachment's ``delete_on_termination``,
but upstream's ``Server.VolumeAttachment`` model required a ``bool``, so
``get_servers``/``get_server`` raised a hard ``pydantic.ValidationError`` for
any server with such a volume (observed on one cloud). See ``compat.py``.

``get_servers`` is now our own scoped tool (``extra_tools/scoped_tools.py``)
that still validates through the same upstream ``Server`` model, while
``get_server`` is still the upstream tool; both are covered here.
"""

from __future__ import annotations

import pytest
from fastmcp import Client

from openstack_mcp_guarded.policy import Policy
from openstack_mcp_guarded.server import create_mcp


@pytest.fixture(autouse=True)
def fake_clouds(monkeypatch):
    """Hermetic cloud catalogue (see test_server.py for rationale)."""
    import openstack.config.loader as _loader
    import openstack_mcp_server.tools.connection as _conn

    class FakeOpenStackConfig:
        cloud_config: dict = {"clouds": {"RegionOne": {}}}

        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def get_cloud_names(self) -> list[str]:
            return list(self.cloud_config["clouds"])

    monkeypatch.setattr(_conn, "OpenStackConfig", FakeOpenStackConfig)
    monkeypatch.setattr(_loader, "OpenStackConfig", FakeOpenStackConfig)


@pytest.fixture()
def cloud_selected(monkeypatch):
    from openstack_mcp_server.tools.connection import ConnectionManager

    # monkeypatch reverts this automatically at teardown; no manual reset.
    monkeypatch.setattr(ConnectionManager, "_cloud_name", "RegionOne")


class _FakeComputeProxy:
    def __init__(self, servers: list[dict]) -> None:
        self._servers = servers

    def servers(self, **query):
        return iter(self._servers)

    def get_server(self, server_id):
        return self._servers[0]


class _FakeConn:
    def __init__(self, servers: list[dict]) -> None:
        self.compute = _FakeComputeProxy(servers)


_SERVER_WITH_NULL_DELETE_ON_TERMINATION = [
    {
        "id": "srv-1",
        "name": "vm-1",
        "attached_volumes": [
            {"id": "vol-1", "delete_on_termination": None},
        ],
    }
]


def _patch_conn(monkeypatch) -> None:
    """Point both the scoped get_servers and upstream get_server at a fake."""
    import openstack_mcp_guarded.extra_tools.scoped_tools as _scoped
    import openstack_mcp_server.tools.compute_tools as _compute_tools

    def fake_conn():
        return _FakeConn(_SERVER_WITH_NULL_DELETE_ON_TERMINATION)

    monkeypatch.setattr(_scoped, "get_openstack_conn", fake_conn)
    monkeypatch.setattr(_compute_tools, "get_openstack_conn", fake_conn)


async def test_get_servers_tolerates_null_delete_on_termination(
    cloud_selected, monkeypatch
):
    policy = Policy(mode="read-only", source="test")
    mcp = create_mcp(policy=policy)
    _patch_conn(monkeypatch)

    async with Client(mcp) as client:
        result = await client.call_tool("get_servers", {})

    servers_out = result.data["items"]
    assert len(servers_out) == 1
    assert servers_out[0]["attached_volumes"][0]["delete_on_termination"] is None


async def test_get_server_tolerates_null_delete_on_termination(
    cloud_selected, monkeypatch
):
    """The single-server tool is still upstream's and relies on the patch."""
    policy = Policy(mode="read-only", source="test")
    mcp = create_mcp(policy=policy)
    _patch_conn(monkeypatch)

    async with Client(mcp) as client:
        result = await client.call_tool("get_server", {"id": "srv-1"})

    assert result.data.attached_volumes[0].delete_on_termination is None


async def test_patch_is_order_independent(cloud_selected, monkeypatch):
    """The patch must mutate the shared model class in place.

    Importing compute_tools *before* create_mcp() binds its `Server`
    reference to whatever class object exists at that moment. If the
    patch swapped in a new class instead of mutating in place, this
    reference would stay stale and this test would reproduce the
    original ValidationError.
    """
    import openstack_mcp_server.tools.compute_tools  # noqa: F401  (import order is the point)

    policy = Policy(mode="read-only", source="test")
    mcp = create_mcp(policy=policy)
    _patch_conn(monkeypatch)

    async with Client(mcp) as client:
        result = await client.call_tool("get_servers", {})

    assert (
        result.data["items"][0]["attached_volumes"][0]["delete_on_termination"]
        is None
    )
