"""Assembly of the guarded OpenStack MCP server.

Reuses tool classes from the upstream ``python-openstackmcp-server``
package (PyPI) and registers them into our own FastMCP instance with
the policy middleware (fuses) applied on top.

The upstream ``serve()`` is NOT reused because we need to inject our
middleware into the pipeline.
"""

import os
import sys

from fastmcp import FastMCP

from openstack_mcp_guarded.compat import patch_upstream_quirks
from openstack_mcp_guarded.config_dir import (
    ConfigDirError,
    apply_config_dir,
    canonical_cloud_name,
)
from openstack_mcp_guarded.middleware import PolicyMiddleware
from openstack_mcp_guarded.policy import Policy


def create_mcp(policy: Policy | None = None) -> FastMCP:
    """Build the guarded FastMCP server instance.

    :param policy: Optional pre-loaded policy (tests inject custom ones).
                   When omitted, the policy is loaded from the standard
                   location / environment override.
    :return: Configured FastMCP instance (not yet running).
    """
    if policy is None:
        policy = Policy.load()

    # Cloud config injection: OS_MCP_GUARD_CONFIG_DIR -> OS_CLIENT_*_FILE.
    # Must run before the first OpenStackConfig() is instantiated.
    apply_config_dir()

    # Upstream picks the initial cloud from CLOUD_NAME (case-sensitive,
    # read at import time). Normalise the spelling against the real
    # clouds.yaml and set it explicitly, independent of import order.
    configured_cloud = os.environ.get("CLOUD_NAME", "").strip()
    if configured_cloud:
        from openstack_mcp_server.tools.connection import ConnectionManager

        ConnectionManager.set_cloud_name(canonical_cloud_name(configured_cloud))

    # Order-independent (mutates the shared model class in place; see
    # compat.py), but applied as early as possible on principle.
    patch_upstream_quirks()

    mcp = FastMCP("openstack_mcp_guarded")

    # Upstream tools (compute, image, identity, network, block storage,
    # connection/cloud session) registered into OUR instance.
    from openstack_mcp_server.tools import register_tool

    register_tool(mcp)

    # Extra tools missing from upstream: Octavia (load balancers),
    # Designate (DNS), and ops/heat (keypairs, server groups, AZs,
    # hypervisors, services, stacks). Same convention: get_* = read.
    from openstack_mcp_guarded.extra_tools.designate_tools import DesignateTools
    from openstack_mcp_guarded.extra_tools.octavia_tools import OctaviaTools
    from openstack_mcp_guarded.extra_tools.ops_tools import OpsTools

    OctaviaTools().register_tools(mcp)
    DesignateTools().register_tools(mcp)
    OpsTools().register_tools(mcp)

    # Fuses: policy middleware added LAST (outermost) so it sees every
    # tools/call before anything else touches it.
    mcp.add_middleware(PolicyMiddleware(policy))

    return mcp


def main() -> None:
    """Console entry point: run the guarded server over stdio."""
    try:
        mcp = create_mcp()
    except ConfigDirError as exc:
        print(f"[mcp-openstack] ERROR {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1) from exc
    mcp.run(transport="stdio")
