"""Shared helpers for extra tool modules.

Besides the attribute projection (``_pick``) this module holds the pieces
that make admin-style listing uniform across services:

* ``envelope`` - the common result shape of every list tool that can be
  scoped (``{total, returned, truncated, limit, items}``),
* ``resolve_project_id`` / ``resolve_user_id`` - accept a name *or* an ID,
* ``compute_scope`` - translate ``project`` / ``user`` / ``all_projects``
  into the query keywords understood by Nova and Cinder.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from typing import Any

#: Default cap on returned items. ``limit=0`` disables the cap.
DEFAULT_LIMIT = 5000

# Keystone IDs are 32 hex characters; some resources also use dashed UUIDs.
_ID_RE = re.compile(
    r"^(?:[0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$",
    re.IGNORECASE,
)


def _pick(obj: Any, *fields: str) -> dict[str, Any]:
    """Project selected attributes of an SDK resource into a dict.

    Missing attributes are set to ``None`` instead of raising, so the
    tool output stays stable across OpenStack releases that add or drop
    response fields.
    """
    return {f: getattr(obj, f, None) for f in fields}


def _plain(item: Any) -> Any:
    """Turn pydantic models into JSON-friendly dicts, leave the rest alone."""
    if hasattr(item, "model_dump"):
        return item.model_dump(mode="json", by_alias=True)
    return item


def envelope(
    items: Iterable[Any],
    limit: int | None = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Wrap a listing into ``{total, returned, truncated, limit, items}``.

    ``total`` counts every matched item (the SDK paginates in the
    background), ``items`` is cut to ``limit``. ``limit=0`` means no cap;
    ``None`` falls back to :data:`DEFAULT_LIMIT`.
    """
    cap = DEFAULT_LIMIT if limit is None else limit
    if cap < 0:
        raise ValueError("limit must be >= 0 (0 means no limit)")
    rows = list(items)
    kept = rows[:cap] if cap else rows
    return {
        "total": len(rows),
        "returned": len(kept),
        "truncated": len(kept) < len(rows),
        "limit": cap or None,
        "items": [_plain(row) for row in kept],
    }


def paged_get(
    proxy: Any,
    path: str,
    key: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    page_size: int = 500,
    max_pages: int = 1000,
) -> Iterator[dict[str, Any]]:
    """Yield the rows of a ``limit``/``marker`` paginated REST listing.

    For the few listings the SDK cannot express: Designate recordsets
    without a zone (the SDK drops the ``/recordsets`` base path) and Heat
    stacks of all projects (``global_tenant`` is not a known query key).
    Errors are raised as the SDK's own exceptions.
    """
    from openstack import exceptions

    query = dict(params or {})
    query["limit"] = page_size
    for _ in range(max_pages):
        response = proxy.get(path, params=query, headers=headers)
        exceptions.raise_from_response(response)
        rows = response.json().get(key) or []
        yield from rows
        if len(rows) < page_size:
            return
        query["marker"] = rows[-1]["id"]


def resolve_project_id(conn: Any, project: str | None) -> str | None:
    """Return the project ID for a project name or ID (``None`` stays ``None``).

    Anything that looks like an ID is used as is (no Keystone round trip);
    other values are looked up by name. An unknown or ambiguous name raises
    the SDK exception instead of guessing.
    """
    if not project:
        return None
    project = project.strip()
    if _ID_RE.match(project):
        return project
    return conn.identity.find_project(project, ignore_missing=False).id


def resolve_user_id(conn: Any, user: str | None) -> str | None:
    """Return the user ID for a user name or ID (``None`` stays ``None``)."""
    if not user:
        return None
    user = user.strip()
    if _ID_RE.match(user):
        return user
    return conn.identity.find_user(user, ignore_missing=False).id


def compute_scope(
    conn: Any,
    project: str | None,
    user: str | None,
    all_projects: bool,
) -> dict[str, Any]:
    """Build the scoping query for Nova/Cinder style ``all_tenants`` APIs.

    Without any argument the result is empty, so the SDK keeps listing the
    project of the current token. Naming a project or a user implies
    ``all_projects`` because both services ignore ``project_id``/``user_id``
    for foreign projects unless ``all_tenants`` is set.
    """
    scope: dict[str, Any] = {}
    project_id = resolve_project_id(conn, project)
    user_id = resolve_user_id(conn, user)
    if project_id:
        scope["project_id"] = project_id
    if user_id:
        scope["user_id"] = user_id
    if all_projects or project_id or user_id:
        scope["all_projects"] = True
    return scope
