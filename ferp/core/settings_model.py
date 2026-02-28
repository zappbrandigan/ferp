from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ScriptVersions(BaseModel):
    model_config = ConfigDict(extra="allow")

    core: str = ""
    namespaces: dict[str, str] = Field(default_factory=dict)


class UserPreferences(BaseModel):
    model_config = ConfigDict(extra="allow")

    theme: str = ""
    startupPath: str = ""
    hideFilteredEntries: bool = True
    scriptNamespace: str = ""
    scriptVersions: ScriptVersions = Field(default_factory=ScriptVersions)
    favorites: list[str] = Field(default_factory=list)


class LogPreferences(BaseModel):
    model_config = ConfigDict(extra="allow")

    maxFiles: int = 50
    maxAgeDays: int = 14


class Integrations(BaseModel):
    model_config = ConfigDict(extra="allow")

    monday: dict[str, Any] = Field(default_factory=dict)


class DriveInventoryCache(BaseModel):
    model_config = ConfigDict(extra="allow")

    entries: list[dict[str, Any]] = Field(default_factory=list)
    lastCheckedAt: float = 0.0


class SettingsModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 1
    userPreferences: UserPreferences = Field(default_factory=UserPreferences)
    logs: LogPreferences = Field(default_factory=LogPreferences)
    integrations: Integrations = Field(default_factory=Integrations)
    driveInventory: DriveInventoryCache = Field(default_factory=DriveInventoryCache)
