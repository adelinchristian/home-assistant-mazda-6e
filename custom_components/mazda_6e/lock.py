from __future__ import annotations

import logging

from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import ControlCommandSigningError
from .const import (
    DOMAIN,
    FUNCTION_CODE_LOCK,
    FUNCTION_CODE_UNLOCK,
    LOCK_CAPABILITY_CANDIDATES,
)
from .entity import Mazda6eEntity
from .models import LOCK_UNLOCKED, Mazda6eVehicle

_LOGGER = logging.getLogger(__name__)
_SENSITIVE_RESULT_KEYS = {"token", "rctoken", "safecode", "securitycode", "sign"}


def _redact_sensitive(value):
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            if key.lower() in _SENSITIVE_RESULT_KEYS:
                redacted[key] = "REDACTED"
            else:
                redacted[key] = _redact_sensitive(item)
        return redacted

    if isinstance(value, list):
        return [_redact_sensitive(item) for item in value]

    return value


def _supports_lock_commands(vehicle: Mazda6eVehicle) -> bool:
    if not vehicle.functions:
        return True
    return any(code in vehicle.functions for code in LOCK_CAPABILITY_CANDIDATES)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []

    for data in coordinator.data.values():
        vehicle: Mazda6eVehicle = data["vehicle"]
        if not _supports_lock_commands(vehicle):
            continue

        try:
            data["status"]["door"]["driverLock"]
            data["status"]["door"]["passengerLock"]
        except Exception:
            continue

        entities.append(Mazda6eVehicleLock(coordinator=coordinator, vehicle=vehicle))

    async_add_entities(entities)


class Mazda6eVehicleLock(Mazda6eEntity, LockEntity):
    _attr_translation_key = "vehicle_lock"
    _attr_icon = "mdi:car-door-lock"

    def __init__(self, coordinator, vehicle: Mazda6eVehicle):
        class _Description:
            key = "vehicle_lock"

        super().__init__(coordinator=coordinator, vehicle=vehicle, description=_Description())
        self._last_command_result: dict | None = None

    @property
    def is_locked(self):
        data = self.vehicle_data
        if not data:
            return None

        try:
            door_data = data["status"]["door"]
            driver_unlocked = door_data["driverLock"] == LOCK_UNLOCKED
            passenger_unlocked = door_data["passengerLock"] == LOCK_UNLOCKED
            return not (driver_unlocked or passenger_unlocked)
        except Exception as err:
            _LOGGER.warning("Mazda6eLock could not read lock state: %s", err)
            return None

    @property
    def available(self) -> bool:
        if not super().available:
            return False

        data = self.vehicle_data
        if not data:
            return False

        try:
            return bool(data["status"]["vehicleStatus"]["connectStatus"])
        except Exception:
            return True

    @property
    def extra_state_attributes(self) -> dict:
        attributes = self.vehicle_attributes
        if self._last_command_result is not None:
            attributes["last_control_result"] = self._last_command_result
        return attributes

    async def async_lock(self, **kwargs):
        await self._async_run_control(FUNCTION_CODE_LOCK, require_security_code=True)

    async def async_unlock(self, **kwargs):
        await self._async_run_control(FUNCTION_CODE_UNLOCK, require_security_code=True)

    async def _async_run_control(self, function_code: str, require_security_code: bool):
        try:
            result = await self.coordinator.async_execute_control_command(
                self.vehicle.vehicle_id,
                function_code,
                require_security_code=require_security_code,
            )
            self._last_command_result = _redact_sensitive(result)
            self.async_write_ha_state()
        except ControlCommandSigningError as err:
            raise HomeAssistantError(
                "Control signing is not configured yet. Please implement the sign hook first."
            ) from err
        except ValueError as err:
            raise HomeAssistantError(
                "Encrypted security code is missing. Add security_code_enc in integration options."
            ) from err
