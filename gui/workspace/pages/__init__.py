"""Workspace pages."""

from .application_production_page import ApplicationProductionPage, PlotsPage
from .firmware_page import FirmwarePage
from .mechanical_page import MechanicalPage
from .project_config_page import ProjectConfigPage
from .production_page import ProductionPage
from .runtime_page import RuntimePage
from .settings_page import SettingsPage

__all__ = [
    "ApplicationProductionPage",
    "PlotsPage",
    "FirmwarePage",
    "MechanicalPage",
    "ProjectConfigPage",
    "ProductionPage",
    "RuntimePage",
    "SettingsPage",
]
