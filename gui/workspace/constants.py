"""Shared constants for the Phase 2 workspace shell."""

from __future__ import annotations

from pathlib import Path


PRODUCT_NAME = "BioBot Robot Arm Tester"
WORKSPACE_TITLE_PREFIX = "BBS Test Platform"

ROUTE_PROJECT_CONFIG = "project_config"
ROUTE_PRODUCTION = "production"
ROUTE_FIRMWARE = "firmware"
ROUTE_MECHANICAL = "mechanical"
ROUTE_APPLICATION = "application"
ROUTE_RUNTIME = "runtime"
ROUTE_SETTINGS = "settings"

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RESOURCES_DIR = PROJECT_ROOT / "resources"
BRAND_IMAGE_PATH = RESOURCES_DIR / "biobot_logo.png"

NAVIGATION_ITEMS = (
    (ROUTE_PRODUCTION, "Production", "Simple node-based quality control testing"),
    (ROUTE_FIRMWARE, "Firmware", "Protocol and debug"),
    (ROUTE_MECHANICAL, "Mechanical", "Motion and observation"),
    (ROUTE_APPLICATION, "Application", "Integration and setup"),
    (ROUTE_RUNTIME, "Runtime", "Live runtime controls and monitoring"),
    (ROUTE_PROJECT_CONFIG, "Project Config", "YAML editor and feature flags"),
)
