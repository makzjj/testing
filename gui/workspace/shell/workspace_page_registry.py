"""Builds first-level navigation items for the workspace shell."""

from __future__ import annotations

from myconfig.project_models import ProjectDefinition

from ..constants import NAVIGATION_ITEMS, ROUTE_APPLICATION, ROUTE_FIRMWARE, ROUTE_MECHANICAL
from ..models import NavigationItem


def build_navigation_items(project_definition: ProjectDefinition) -> list[NavigationItem]:
    """Build first-level navigation metadata from shared constants and feature flags."""
    items: list[NavigationItem] = []
    for route_id, label, description in NAVIGATION_ITEMS:
        enabled = _route_enabled(project_definition, route_id)
        items.append(NavigationItem(route_id=route_id, label=label, description=description, enabled=enabled))
    return items


def get_route_label(items: list[NavigationItem], route_id: str) -> str:
    """Resolve one route id to a user-facing label."""
    for item in items:
        if item.route_id == route_id:
            return item.label
    return route_id


def _route_enabled(project_definition: ProjectDefinition, route_id: str) -> bool:
    if route_id == ROUTE_FIRMWARE:
        return project_definition.features.firmware_tools
    if route_id == ROUTE_MECHANICAL:
        return project_definition.features.mechanical_tools
    if route_id == ROUTE_APPLICATION:
        return project_definition.features.application_tools
    return True
