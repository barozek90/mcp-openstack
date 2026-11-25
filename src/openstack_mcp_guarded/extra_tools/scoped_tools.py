"""Project / user scoped list tools that replace their upstream twins.

Upstream ``python-openstackmcp-server`` lists only what the current token
sees (Nova, Cinder) or dumps everything without a way to narrow it down
(Neutron), and its response models drop ``project_id``/``user_id``. For an
admin session that is not enough, so these tools take over the upstream
names (the server registers them with ``on_duplicate="replace"``) and add:

* ``project`` - project name or ID,
* ``user`` - user name or ID (where the service can filter by user),
* ``all_projects`` - resources of every project (Nova, Cinder),
* ``limit`` - cap on returned items (``0`` = unlimited).

Called without arguments they behave like upstream (same scope), only the
result is wrapped in :func:`~.helpers.envelope`. All of them are plain
reads, so the ``get_*`` read-only policy keeps allowing them.
"""

from __future__ import annotations

from fastmcp import FastMCP

from openstack_mcp_server.tools.base import get_openstack_conn
from openstack_mcp_server.tools.network_tools import NetworkTools
from openstack_mcp_server.tools.response.compute import Server
from openstack_mcp_server.tools.response.image import Image

from .helpers import (
    DEFAULT_LIMIT,
    _pick,
    compute_scope,
    envelope,
    resolve_project_id,
)

# Admin-visible attributes that upstream's ``Server`` model leaves out.
_SERVER_EXTRA = (
    "project_id", "user_id", "compute_host", "hypervisor_hostname",
    "availability_zone", "created_at", "launched_at", "vm_state",
    "task_state",
)

# Connection details safe to show (upstream's ConnectionInfo allowlist).
_CONNECTION_INFO_FIELDS = (
    "access_mode", "cacheable", "driver_volume_type", "encrypted",
    "qos_specs", "target_discovered", "target_iqn", "target_lun",
    "target_portal",
)

_VOLUME_FIELDS = (
    "id", "name", "status", "size", "volume_type", "availability_zone",
    "is_bootable", "is_encrypted", "description", "project_id", "user_id",
    "host",
)


def _project_arg(conn, project: str | None, project_id: str | None):
    """``project`` (name or ID) wins; ``project_id`` is the upstream alias."""
    return resolve_project_id(conn, project or project_id)


class ScopedListTools:
    """List tools with project / user / all-projects scoping."""

    def __init__(self) -> None:
        self._network = NetworkTools()

    def register_tools(self, mcp: FastMCP) -> None:
        # identity
        mcp.tool()(self.get_projects)
        mcp.tool()(self.get_users)
        # compute / block storage
        mcp.tool()(self.get_servers)
        mcp.tool()(self.get_volumes)
        mcp.tool()(self.get_attachments)
        # network
        mcp.tool()(self.get_networks)
        mcp.tool()(self.get_subnets)
        mcp.tool()(self.get_ports)
        mcp.tool()(self.get_routers)
        mcp.tool()(self.get_security_groups)
        mcp.tool()(self.get_floating_ips)
        # image
        mcp.tool()(self.get_images)

    # ------------------------------------------------------------------
    # identity
    # ------------------------------------------------------------------

    def get_projects(
        self,
        name: str | None = None,
        domain_id: str | None = None,
        parent_id: str | None = None,
        enabled: bool | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> dict:
        """List Identity projects, optionally filtered (limit=0: no limit).

        Large clouds have thousands of projects: prefer the filters.
        """
        conn = get_openstack_conn()
        query: dict = {}
        if name:
            query["name"] = name
        if domain_id:
            query["domain_id"] = domain_id
        if parent_id:
            query["parent_id"] = parent_id
        if enabled is not None:
            query["is_enabled"] = enabled
        return envelope(
            (
                _pick(
                    p, "id", "name", "description", "is_enabled",
                    "domain_id", "parent_id",
                )
                for p in conn.identity.projects(**query)
            ),
            limit,
        )

    def get_users(
        self,
        name: str | None = None,
        domain_id: str | None = None,
        enabled: bool | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> dict:
        """List Identity users, optionally filtered (limit=0: no limit).

        Use it to find the user to pass as ``user`` to get_servers,
        get_volumes or get_keypairs.
        """
        conn = get_openstack_conn()
        query: dict = {}
        if name:
            query["name"] = name
        if domain_id:
            query["domain_id"] = domain_id
        if enabled is not None:
            query["is_enabled"] = enabled
        return envelope(
            (
                _pick(
                    u, "id", "name", "description", "domain_id",
                    "is_enabled", "default_project_id", "email",
                )
                for u in conn.identity.users(**query)
            ),
            limit,
        )

    # ------------------------------------------------------------------
    # compute / block storage
    # ------------------------------------------------------------------

    def get_servers(
        self,
        project: str | None = None,
        user: str | None = None,
        all_projects: bool = False,
        name: str | None = None,
        status: str | None = None,
        host: str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> dict:
        """List Compute servers (limit=0: no limit).

        Without arguments only the project of the current token is listed.
        ``project`` (name or ID) and ``user`` (name or ID) narrow the list
        to that project/user in any project, ``all_projects=True`` lists
        every project (admin). ``name`` is a Nova regex, ``host`` the
        compute host. Each item carries project_id, user_id, host and
        hypervisor.
        """
        conn = get_openstack_conn()
        query = compute_scope(conn, project, user, all_projects)
        if name:
            query["name"] = name
        if status:
            query["status"] = status.upper()
        if host:
            query["compute_host"] = host
        items = []
        for server in conn.compute.servers(**query):
            item = Server(**server).model_dump(mode="json", by_alias=True)
            item.update(_pick(server, *_SERVER_EXTRA))
            items.append(item)
        return envelope(items, limit)

    def get_volumes(
        self,
        project: str | None = None,
        user: str | None = None,
        all_projects: bool = False,
        name: str | None = None,
        status: str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> dict:
        """List Block Storage volumes (limit=0: no limit).

        Without arguments only the project of the current token is listed.
        ``project``/``user`` (name or ID) narrow the list, ``all_projects``
        lists every project (admin). Items carry project_id, user_id and
        the storage host.
        """
        conn = get_openstack_conn()
        query = compute_scope(conn, project, user, all_projects)
        if name:
            query["name"] = name
        if status:
            query["status"] = status
        items = []
        for volume in conn.block_storage.volumes(**query):
            item = _pick(volume, *_VOLUME_FIELDS)
            created = getattr(volume, "created_at", None)
            item["created_at"] = str(created) if created else None
            item["attachments"] = [
                {
                    "server_id": a.get("server_id"),
                    "device": a.get("device"),
                    "attachment_id": a.get("attachment_id"),
                }
                for a in (getattr(volume, "attachments", None) or [])
            ]
            items.append(item)
        return envelope(items, limit)

    def get_attachments(
        self,
        volume_id: str | None = None,
        instance: str | None = None,
        project: str | None = None,
        all_projects: bool = False,
        limit: int = DEFAULT_LIMIT,
    ) -> dict:
        """List volume attachments (limit=0: no limit).

        ``project`` (name or ID) or ``all_projects`` look beyond the
        project of the current token (admin).
        """
        conn = get_openstack_conn()
        query = compute_scope(conn, project, None, all_projects)
        if volume_id:
            query["volume_id"] = volume_id
        if instance:
            query["instance"] = instance
        # Built by hand instead of through upstream's ``Attachment`` model:
        # it types ``connection_info.qos_specs`` as a string, while Cinder
        # returns a dict, so one such attachment failed the whole listing.
        items = []
        for att in conn.block_storage.attachments(**query):
            item = _pick(
                att, "id", "instance", "volume_id", "status", "attach_mode",
                "attached_at", "detached_at", "connector", "project_id",
            )
            info = getattr(att, "connection_info", None)
            # Same allowlist as upstream's ConnectionInfo: no auth_* secrets.
            item["connection_info"] = (
                {key: info.get(key) for key in _CONNECTION_INFO_FIELDS}
                if info
                else None
            )
            items.append(item)
        return envelope(items, limit)

    # ------------------------------------------------------------------
    # network (Neutron lists every project for an admin; narrow by project)
    # ------------------------------------------------------------------

    def get_networks(
        self,
        status_filter: str | None = None,
        shared_only: bool = False,
        project: str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> dict:
        """List Networks (limit=0: no limit).

        An admin sees the networks of all projects; ``project`` (name or
        ID) narrows the list to one project.
        """
        conn = get_openstack_conn()
        filters: dict = {}
        if status_filter:
            filters["status"] = status_filter.upper()
        if shared_only:
            filters["is_shared"] = True
        project_id = resolve_project_id(conn, project)
        if project_id:
            filters["project_id"] = project_id
        return envelope(
            (
                self._network._convert_to_network_model(n)
                for n in conn.network.networks(**filters)
            ),
            limit,
        )

    def get_subnets(
        self,
        network_id: str | None = None,
        ip_version: int | None = None,
        project: str | None = None,
        has_gateway: bool | None = None,
        is_dhcp_enabled: bool | None = None,
        project_id: str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> dict:
        """List Subnets (limit=0: no limit).

        ``project`` is a project name or ID; ``project_id`` is the older
        ID-only spelling of the same filter.
        """
        conn = get_openstack_conn()
        return envelope(
            self._network.get_subnets(
                network_id=network_id,
                ip_version=ip_version,
                project_id=_project_arg(conn, project, project_id),
                has_gateway=has_gateway,
                is_dhcp_enabled=is_dhcp_enabled,
            ),
            limit,
        )

    def get_ports(
        self,
        status_filter: str | None = None,
        device_id: str | None = None,
        network_id: str | None = None,
        project: str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> dict:
        """List Ports (limit=0: no limit).

        ``project`` is a project name or ID.
        """
        conn = get_openstack_conn()
        filters: dict = {}
        if status_filter:
            filters["status"] = status_filter.upper()
        if device_id:
            filters["device_id"] = device_id
        if network_id:
            filters["network_id"] = network_id
        project_id = resolve_project_id(conn, project)
        if project_id:
            filters["project_id"] = project_id
        return envelope(
            (
                self._network._convert_to_port_model(p)
                for p in conn.network.ports(**filters)
            ),
            limit,
        )

    def get_routers(
        self,
        status_filter: str | None = None,
        project: str | None = None,
        is_admin_state_up: bool | None = None,
        project_id: str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> dict:
        """List Routers (limit=0: no limit).

        ``project`` is a project name or ID; ``project_id`` is the older
        ID-only spelling of the same filter.
        """
        conn = get_openstack_conn()
        return envelope(
            self._network.get_routers(
                status_filter=status_filter,
                project_id=_project_arg(conn, project, project_id),
                is_admin_state_up=is_admin_state_up,
            ),
            limit,
        )

    def get_security_groups(
        self,
        project: str | None = None,
        name: str | None = None,
        id: str | None = None,
        project_id: str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> dict:
        """List Security Groups (limit=0: no limit).

        ``project`` is a project name or ID; ``project_id`` is the older
        ID-only spelling of the same filter.
        """
        conn = get_openstack_conn()
        return envelope(
            self._network.get_security_groups(
                project_id=_project_arg(conn, project, project_id),
                name=name,
                id=id,
            ),
            limit,
        )

    def get_floating_ips(
        self,
        status_filter: str | None = None,
        project: str | None = None,
        port_id: str | None = None,
        floating_network_id: str | None = None,
        unassigned_only: bool | None = None,
        project_id: str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> dict:
        """List Floating IPs (limit=0: no limit).

        ``project`` is a project name or ID; ``project_id`` is the older
        ID-only spelling of the same filter.
        """
        conn = get_openstack_conn()
        return envelope(
            self._network.get_floating_ips(
                status_filter=status_filter,
                project_id=_project_arg(conn, project, project_id),
                port_id=port_id,
                floating_network_id=floating_network_id,
                unassigned_only=unassigned_only,
            ),
            limit,
        )

    # ------------------------------------------------------------------
    # image
    # ------------------------------------------------------------------

    def get_images(
        self,
        name: str | None = None,
        status: str | None = None,
        visibility: str | None = None,
        project: str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> dict:
        """List Images (limit=0: no limit).

        ``project`` (name or ID) keeps only images owned by that project.
        """
        conn = get_openstack_conn()
        filters: dict = {}
        if name and name.strip():
            filters["name"] = name.strip()
        if status and status.strip():
            filters["status"] = status.strip()
        if visibility and visibility.strip():
            filters["visibility"] = visibility.strip()
        owner = resolve_project_id(conn, project)
        if owner:
            filters["owner"] = owner
        return envelope(
            (Image(**image) for image in conn.image.images(**filters)),
            limit,
        )
