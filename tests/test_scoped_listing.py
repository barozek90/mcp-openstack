"""Project / user scoped listing (admin view) through the MCP protocol.

Everything runs against a fake SDK connection that records the query each
tool sends, so these tests pin down *what is asked from OpenStack*:
no argument keeps the old scope, ``project`` / ``user`` / ``all_projects``
translate to the right keywords, and results come back in the
``{total, returned, truncated, limit, items}`` envelope.
"""

from __future__ import annotations

from types import SimpleNamespace as NS

import pytest
from fastmcp import Client

from openstack_mcp_guarded.extra_tools.helpers import (
    DEFAULT_LIMIT,
    compute_scope,
    envelope,
    paged_get,
    resolve_project_id,
    resolve_user_id,
)
from openstack_mcp_guarded.policy import Policy
from openstack_mcp_guarded.server import create_mcp

PROJECT_ID = "a" * 32
OTHER_PROJECT_ID = "c" * 32
USER_ID = "b" * 32


# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------


class FakeProxy:
    """Records every call; per-method results are set in ``results``.

    A list result is returned as an iterator (like an SDK generator), a
    callable result is invoked with the call arguments, anything else is
    returned as is.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []
        self.results: dict[str, object] = {}

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)

        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            result = self.results.get(name, [])
            if callable(result):
                return result(*args, **kwargs)
            return iter(result) if isinstance(result, list) else result

        return call

    def kwargs(self, method: str) -> dict:
        """Keyword arguments of the last call to ``method``."""
        for name, _args, kwargs in reversed(self.calls):
            if name == method:
                return kwargs
        raise AssertionError(f"{method}() was never called")

    def called(self, method: str) -> bool:
        return any(name == method for name, _a, _k in self.calls)


class FakeConn:
    def __init__(self) -> None:
        for service in (
            "identity", "compute", "block_storage", "network", "image",
            "load_balancer", "dns", "orchestration",
        ):
            setattr(self, service, FakeProxy())
        # name -> project / user, used by find_project / find_user
        self.identity.results["find_project"] = lambda name, **kw: NS(
            id=PROJECT_ID if name == "demo" else OTHER_PROJECT_ID
        )
        self.identity.results["find_user"] = lambda name, **kw: NS(id=USER_ID)


class FakeResponse:
    status_code = 200

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def json(self) -> dict:
        return self._payload


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
def conn(monkeypatch) -> FakeConn:
    """One fake connection shared by every module that opens a connection."""
    import openstack_mcp_guarded.extra_tools.designate_tools as _designate
    import openstack_mcp_guarded.extra_tools.octavia_tools as _octavia
    import openstack_mcp_guarded.extra_tools.ops_tools as _ops
    import openstack_mcp_guarded.extra_tools.scoped_tools as _scoped
    import openstack_mcp_server.tools.network_tools as _network
    from openstack_mcp_server.tools.connection import ConnectionManager

    fake = FakeConn()
    for module in (_designate, _octavia, _ops, _scoped, _network):
        monkeypatch.setattr(module, "get_openstack_conn", lambda: fake)
    monkeypatch.setattr(ConnectionManager, "_cloud_name", "RegionOne")
    return fake


@pytest.fixture()
def mcp(conn):
    return create_mcp(policy=Policy(mode="read-only", source="test"))


async def call(mcp, tool: str, **arguments):
    async with Client(mcp) as client:
        result = await client.call_tool(tool, arguments)
    return result.data


class _Resource(dict):
    """Mapping *and* attribute access, like an SDK resource."""

    def __getattr__(self, name: str):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name) from None


def _server(**extra):
    base = {
        "id": "fake-uuid",
        "name": "vm-1",
        "status": "ACTIVE",
        "project_id": PROJECT_ID,
        "user_id": USER_ID,
        "compute_host": "hv-1",
        "hypervisor_hostname": "hv-1.example",
        "availability_zone": "nova",
    }
    base.update(extra)
    return base


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def test_envelope_default_limit_is_5000():
    assert DEFAULT_LIMIT == 5000
    out = envelope(range(3))
    assert out == {
        "total": 3, "returned": 3, "truncated": False, "limit": 5000,
        "items": [0, 1, 2],
    }


def test_envelope_truncates_but_counts_everything():
    out = envelope(range(10), limit=4)
    assert (out["total"], out["returned"], out["truncated"]) == (10, 4, True)
    assert out["items"] == [0, 1, 2, 3]
    assert out["limit"] == 4


def test_envelope_limit_zero_is_unlimited():
    out = envelope(range(7), limit=0)
    assert out["returned"] == 7
    assert out["truncated"] is False
    assert out["limit"] is None


def test_envelope_rejects_negative_limit():
    with pytest.raises(ValueError):
        envelope([], limit=-1)


def test_resolve_project_id_passes_ids_without_lookup():
    conn = FakeConn()
    assert resolve_project_id(conn, PROJECT_ID) == PROJECT_ID
    assert resolve_project_id(conn, None) is None
    assert not conn.identity.called("find_project")


def test_resolve_project_id_looks_names_up():
    conn = FakeConn()
    assert resolve_project_id(conn, "demo") == PROJECT_ID
    assert conn.identity.called("find_project")
    assert conn.identity.kwargs("find_project") == {"ignore_missing": False}


def test_resolve_user_id():
    conn = FakeConn()
    assert resolve_user_id(conn, USER_ID) == USER_ID
    assert resolve_user_id(conn, "tester") == USER_ID
    assert resolve_user_id(conn, None) is None


def test_compute_scope_is_empty_without_arguments():
    assert compute_scope(FakeConn(), None, None, False) == {}


def test_compute_scope_naming_a_project_implies_all_projects():
    scope = compute_scope(FakeConn(), "demo", None, False)
    assert scope == {"project_id": PROJECT_ID, "all_projects": True}


def test_compute_scope_user_and_all_projects():
    assert compute_scope(FakeConn(), None, "tester", False) == {
        "user_id": USER_ID, "all_projects": True,
    }
    assert compute_scope(FakeConn(), None, None, True) == {"all_projects": True}


def test_paged_get_follows_marker():
    pages = [
        {"rows": [{"id": "r1"}, {"id": "r2"}]},
        {"rows": [{"id": "r3"}]},
    ]
    seen: list[dict] = []

    class Proxy:
        def get(self, path, params=None, headers=None):
            seen.append(dict(params))
            return FakeResponse(pages[len(seen) - 1])

    rows = list(paged_get(Proxy(), "/x", "rows", page_size=2))
    assert [r["id"] for r in rows] == ["r1", "r2", "r3"]
    assert "marker" not in seen[0]
    assert seen[1]["marker"] == "r2"


# ---------------------------------------------------------------------------
# tool schema
# ---------------------------------------------------------------------------


async def test_scoped_tools_expose_new_parameters(mcp):
    async with Client(mcp) as client:
        tools = {t.name: t for t in await client.list_tools()}

    servers = tools["get_servers"].input_schema["properties"]
    assert {"project", "user", "all_projects", "limit"} <= set(servers)
    assert servers["limit"]["default"] == 5000
    assert "get_users" in tools
    for name in ("get_volumes", "get_dns_zones", "get_heat_stacks"):
        props = tools[name].input_schema["properties"]
        assert {"project", "all_projects", "limit"} <= set(props), name
    for name in ("get_networks", "get_load_balancers", "get_images"):
        assert "project" in tools[name].input_schema["properties"], name


# ---------------------------------------------------------------------------
# compute / block storage
# ---------------------------------------------------------------------------


async def test_get_servers_without_arguments_keeps_current_scope(conn, mcp):
    conn.compute.results["servers"] = [_Resource(_server())]
    out = await call(mcp, "get_servers")
    assert conn.compute.kwargs("servers") == {}
    assert out["total"] == 1
    item = out["items"][0]
    assert item["id"] == "fake-uuid"
    assert item["project_id"] == PROJECT_ID


async def test_get_servers_by_project_name(conn, mcp):
    conn.compute.results["servers"] = [_Resource(_server())]
    out = await call(mcp, "get_servers", project="demo")
    assert conn.compute.kwargs("servers") == {
        "project_id": PROJECT_ID, "all_projects": True,
    }
    item = out["items"][0]
    assert item["project_id"] == PROJECT_ID
    assert item["user_id"] == USER_ID
    assert item["compute_host"] == "hv-1"
    assert item["hypervisor_hostname"] == "hv-1.example"


async def test_get_servers_by_project_id_skips_lookup(conn, mcp):
    await call(mcp, "get_servers", project=PROJECT_ID)
    assert not conn.identity.called("find_project")
    assert conn.compute.kwargs("servers")["project_id"] == PROJECT_ID


async def test_get_servers_all_projects_with_filters(conn, mcp):
    await call(
        mcp, "get_servers", all_projects=True, status="active", host="hv-1",
        name="vm-.*",
    )
    assert conn.compute.kwargs("servers") == {
        "all_projects": True,
        "status": "ACTIVE",
        "compute_host": "hv-1",
        "name": "vm-.*",
    }


async def test_get_servers_by_user(conn, mcp):
    await call(mcp, "get_servers", user="tester")
    assert conn.compute.kwargs("servers") == {
        "user_id": USER_ID, "all_projects": True,
    }


async def test_get_servers_limit_reports_truncation(conn, mcp):
    conn.compute.results["servers"] = [
        _Resource(_server(id=f"fake-uuid-{i}")) for i in range(5)
    ]
    out = await call(mcp, "get_servers", all_projects=True, limit=2)
    assert (out["total"], out["returned"], out["truncated"]) == (5, 2, True)
    assert len(out["items"]) == 2


async def test_get_volumes_scoping_and_fields(conn, mcp):
    conn.block_storage.results["volumes"] = [
        NS(
            id="fake-uuid", name="data", status="in-use", size=10,
            volume_type="hdd", availability_zone="nova",
            created_at="2026-01-01T00:00:00", is_bootable=False,
            is_encrypted=False, description=None, project_id=PROJECT_ID,
            user_id=USER_ID, host="cinder@hdd",
            attachments=[{"server_id": "fake-uuid", "device": "/dev/vdb",
                          "attachment_id": "fake-uuid"}],
        )
    ]
    out = await call(mcp, "get_volumes", project="demo", status="in-use")
    assert conn.block_storage.kwargs("volumes") == {
        "project_id": PROJECT_ID, "all_projects": True, "status": "in-use",
    }
    item = out["items"][0]
    assert item["project_id"] == PROJECT_ID
    assert item["host"] == "cinder@hdd"
    assert item["attachments"][0]["device"] == "/dev/vdb"


async def test_get_volumes_without_arguments(conn, mcp):
    await call(mcp, "get_volumes")
    assert conn.block_storage.kwargs("volumes") == {}


async def test_get_keypairs_by_user_filters_name_client_side(conn, mcp):
    conn.compute.results["keypairs"] = [
        NS(id="k1", name="k1", user_id=USER_ID),
        NS(id="k2", name="k2", user_id=USER_ID),
    ]
    out = await call(mcp, "get_keypairs", user="tester", name="k2")
    assert conn.compute.kwargs("keypairs") == {"user_id": USER_ID}
    assert [k["name"] for k in out["items"]] == ["k2"]


async def test_get_server_groups_by_project(conn, mcp):
    conn.compute.results["server_groups"] = [
        NS(id="g1", name="mine", project_id=PROJECT_ID),
        NS(id="g2", name="theirs", project_id=OTHER_PROJECT_ID),
    ]
    out = await call(mcp, "get_server_groups", project="demo")
    assert conn.compute.kwargs("server_groups") == {"all_projects": True}
    assert [g["name"] for g in out["items"]] == ["mine"]


async def test_get_compute_quotas_uses_the_project_argument(conn, mcp):
    """Regression: the tool used an undefined name and raised NameError."""
    conn.compute.results["get_quota_set"] = NS(instances=10, cores=20)
    out = await call(mcp, "get_compute_quotas", project_id="demo", usage=True)
    name, args, kwargs = conn.compute.calls[-1]
    assert name == "get_quota_set"
    assert args == (PROJECT_ID,)
    assert kwargs == {"usage": True}
    assert out["instances"] == 10


# ---------------------------------------------------------------------------
# identity
# ---------------------------------------------------------------------------


async def test_get_projects_filters(conn, mcp):
    conn.identity.results["projects"] = [
        NS(id=PROJECT_ID, name="demo", description=None, is_enabled=True,
           domain_id="default", parent_id=None),
    ]
    out = await call(
        mcp, "get_projects", name="demo", domain_id="default", enabled=True,
    )
    assert conn.identity.kwargs("projects") == {
        "name": "demo", "domain_id": "default", "is_enabled": True,
    }
    assert out["items"][0]["id"] == PROJECT_ID


async def test_get_projects_limit(conn, mcp):
    conn.identity.results["projects"] = [
        NS(id=f"p{i}", name=f"p{i}") for i in range(6)
    ]
    out = await call(mcp, "get_projects", limit=3)
    assert (out["total"], out["returned"], out["truncated"]) == (6, 3, True)


async def test_get_users(conn, mcp):
    conn.identity.results["users"] = [
        NS(id=USER_ID, name="tester", is_enabled=True, domain_id="default"),
    ]
    out = await call(mcp, "get_users", name="tester", enabled=True)
    assert conn.identity.kwargs("users") == {
        "name": "tester", "is_enabled": True,
    }
    assert out["items"][0]["name"] == "tester"


# ---------------------------------------------------------------------------
# network / image
# ---------------------------------------------------------------------------


def _network(project_id: str):
    return NS(
        id="fake-uuid", name="net", status="ACTIVE", description=None,
        is_admin_state_up=True, is_shared=False, mtu=1500,
        provider_network_type=None, provider_physical_network=None,
        provider_segmentation_id=None, project_id=project_id,
    )


async def test_get_networks_by_project(conn, mcp):
    conn.network.results["networks"] = [_network(PROJECT_ID)]
    out = await call(mcp, "get_networks", project="demo", shared_only=True)
    assert conn.network.kwargs("networks") == {
        "is_shared": True, "project_id": PROJECT_ID,
    }
    assert out["items"][0]["project_id"] == PROJECT_ID


async def test_get_networks_without_project_has_no_project_filter(conn, mcp):
    conn.network.results["networks"] = [_network(PROJECT_ID)]
    await call(mcp, "get_networks")
    assert conn.network.kwargs("networks") == {}


async def test_get_ports_by_project(conn, mcp):
    await call(mcp, "get_ports", project="demo", network_id="fake-uuid")
    assert conn.network.kwargs("ports") == {
        "network_id": "fake-uuid", "project_id": PROJECT_ID,
    }


@pytest.mark.parametrize(
    ("tool", "method"),
    [
        ("get_subnets", "subnets"),
        ("get_routers", "routers"),
        ("get_security_groups", "security_groups"),
        ("get_floating_ips", "ips"),
    ],
)
async def test_neutron_tools_accept_project_name_and_old_project_id(
    conn, mcp, tool, method
):
    out = await call(mcp, tool, project="demo")
    assert conn.network.kwargs(method) == {"project_id": PROJECT_ID}
    assert out["total"] == 0

    conn.network.calls.clear()
    await call(mcp, tool, project_id=OTHER_PROJECT_ID)
    assert conn.network.kwargs(method) == {"project_id": OTHER_PROJECT_ID}


async def test_get_images_by_project_filters_on_owner(conn, mcp):
    await call(mcp, "get_images", project="demo", visibility="private")
    assert conn.image.kwargs("images") == {
        "visibility": "private", "owner": PROJECT_ID,
    }


# ---------------------------------------------------------------------------
# Octavia
# ---------------------------------------------------------------------------


async def test_get_load_balancers_by_project_returns_project_id(conn, mcp):
    conn.load_balancer.results["load_balancers"] = [
        NS(id="fake-uuid", name="lb", project_id=PROJECT_ID,
           provisioning_status="ACTIVE"),
    ]
    out = await call(
        mcp, "get_load_balancers", project="demo",
        provisioning_status="error",
    )
    assert conn.load_balancer.kwargs("load_balancers") == {
        "provisioning_status": "ERROR", "project_id": PROJECT_ID,
    }
    assert out["items"][0]["project_id"] == PROJECT_ID


@pytest.mark.parametrize(
    ("tool", "method"),
    [
        ("get_listeners", "listeners"),
        ("get_pools", "pools"),
        ("get_health_monitors", "health_monitors"),
    ],
)
async def test_octavia_children_filter_by_project(conn, mcp, tool, method):
    await call(mcp, tool, project="demo")
    assert conn.load_balancer.kwargs(method) == {"project_id": PROJECT_ID}


# ---------------------------------------------------------------------------
# Designate
# ---------------------------------------------------------------------------


async def test_get_dns_zones_defaults_to_current_project(conn, mcp):
    await call(mcp, "get_dns_zones")
    assert conn.dns.kwargs("zones") == {}


async def test_get_dns_zones_by_project_and_all_projects(conn, mcp):
    await call(mcp, "get_dns_zones", project="demo")
    assert conn.dns.kwargs("zones") == {"project_id": PROJECT_ID}

    await call(mcp, "get_dns_zones", all_projects=True, zone_type="primary")
    assert conn.dns.kwargs("zones") == {"type": "PRIMARY", "all_projects": True}


async def test_get_dns_recordsets_with_zone_uses_the_sdk_listing(conn, mcp):
    await call(
        mcp, "get_dns_recordsets", zone_id="fake-uuid", all_projects=True,
        record_type="a",
    )
    assert conn.dns.kwargs("recordsets") == {
        "zone": "fake-uuid", "type": "A", "all_projects": True,
    }
    assert not conn.dns.called("get")


async def test_get_dns_recordsets_without_zone_pages_by_hand(conn, mcp):
    """Regression: the SDK raises KeyError: 'zone_id' for a zone-less list."""
    conn.dns.results["get"] = FakeResponse(
        {
            "recordsets": [
                {"id": "fake-uuid", "zone_id": "fake-uuid", "name": "a.example.",
                 "type": "A", "records": ["192.0.2.1"],
                 "project_id": PROJECT_ID},
            ]
        }
    )
    out = await call(mcp, "get_dns_recordsets", project="demo", record_type="a")
    assert not conn.dns.called("recordsets")
    _name, args, kwargs = conn.dns.calls[-1]
    assert args == ("/recordsets",)
    assert kwargs["params"]["type"] == "A"
    assert kwargs["headers"] == {"x-auth-sudo-project-id": PROJECT_ID}
    item = out["items"][0]
    assert item["name"] == "a.example."
    assert item["project_id"] == PROJECT_ID


async def test_get_dns_recordsets_all_projects_sends_the_header(conn, mcp):
    conn.dns.results["get"] = FakeResponse({"recordsets": []})
    await call(mcp, "get_dns_recordsets", all_projects=True)
    assert conn.dns.kwargs("get")["headers"] == {"x-auth-all-projects": "True"}


# ---------------------------------------------------------------------------
# Heat
# ---------------------------------------------------------------------------


async def test_get_heat_stacks_defaults_to_current_project(conn, mcp):
    conn.orchestration.results["get"] = FakeResponse(
        {
            "stacks": [
                {"id": "fake-uuid", "stack_name": "st",
                 "stack_status": "CREATE_COMPLETE",
                 "creation_time": "2026-01-01T00:00:00Z"},
            ]
        }
    )
    out = await call(mcp, "get_heat_stacks", status="create_complete")
    params = conn.orchestration.kwargs("get")["params"]
    assert params["status"] == "CREATE_COMPLETE"
    assert "global_tenant" not in params
    assert "tenant" not in params
    # Regression: every field except the ID used to come back null.
    item = out["items"][0]
    assert item["stack_name"] == "st"
    assert item["stack_status"] == "CREATE_COMPLETE"
    assert item["creation_time"] == "2026-01-01T00:00:00Z"


async def test_get_heat_stacks_all_projects_uses_global_tenant(conn, mcp):
    conn.orchestration.results["get"] = FakeResponse(
        {
            "stacks": [
                {"id": "fake-uuid", "stack_name": "st",
                 "stack_status": "CREATE_COMPLETE", "project": PROJECT_ID},
            ]
        }
    )
    out = await call(mcp, "get_heat_stacks", all_projects=True)
    assert not conn.orchestration.called("stacks")
    _name, args, kwargs = conn.orchestration.calls[-1]
    assert args == ("/stacks",)
    assert kwargs["params"]["global_tenant"] == "true"
    assert "tenant" not in kwargs["params"]
    assert out["items"][0]["stack_name"] == "st"
    assert out["items"][0]["project_id"] == PROJECT_ID


async def test_get_heat_stacks_by_project_sends_tenant(conn, mcp):
    conn.orchestration.results["get"] = FakeResponse({"stacks": []})
    await call(mcp, "get_heat_stacks", project="demo")
    params = conn.orchestration.kwargs("get")["params"]
    assert params["global_tenant"] == "true"
    assert params["tenant"] == PROJECT_ID


# ---------------------------------------------------------------------------
# policy
# ---------------------------------------------------------------------------


def test_read_only_policy_allows_the_scoped_reads():
    policy = Policy(mode="read-only", source="test")
    for tool in ("get_users", "get_servers", "get_projects", "get_dns_zones"):
        assert policy.is_allowed(tool)
