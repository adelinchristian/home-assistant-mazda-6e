from __future__ import annotations

import logging

from homeassistant.components.cover import CoverDeviceClass, CoverEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import ControlCommandSigningError
from .const import (
    DOMAIN,
    FUNCTION_CODE_TRUNK,
    FUNCTION_CODE_WINDOWS,
    TRUNK_CAPABILITY_CANDIDATES,
    WINDOWS_CAPABILITY_CANDIDATES,
    WINDOWS_OPEN_TYPE_ALL,
)
from .entity import Mazda6eEntity
from .models import Mazda6eVehicle

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


def _supports_capability(vehicle: Mazda6eVehicle, candidates: tuple[str, ...]) -> bool:
    if not vehicle.functions:
        return True
    return any(code in vehicle.functions for code in candidates)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []

    for data in coordinator.data.values():
        vehicle: Mazda6eVehicle = data["vehicle"]

        if _supports_capability(vehicle, WINDOWS_CAPABILITY_CANDIDATES):
            try:
                data["status"]["window"]["windows"]
            except Exception:
                pass
            else:
                entities.append(Mazda6eWindowsCover(coordinator=coordinator, vehicle=vehicle))

        if _supports_capability(vehicle, TRUNK_CAPABILITY_CANDIDATES):
            try:
                data["status"]["door"]["trunk"]
            except Exception:
                pass
            else:
                entities.append(Mazda6eTrunkCover(coordinator=coordinator, vehicle=vehicle))

    async_add_entities(entities)


class _Mazda6eControlCover(Mazda6eEntity, CoverEntity):
    _function_code: str
    _command_name: str

    def __init__(self, coordinator, vehicle: Mazda6eVehicle, key: str):
        class _Description:
            def __init__(self, local_key: str):
                self.key = local_key

        super().__init__(coordinator=coordinator, vehicle=vehicle, description=_Description(key))
        self._last_command_result: dict | None = None

    @property
    def available(self) -> bool:
        if not super().available:
            return False

        data = self.vehicle_data
        if not data:
            return False

        try:
            return bool(data["status"]["vehicleStatus"].get("connectStatus"))
        except Exception:
            return True

    @property
    def extra_state_attributes(self) -> dict:
        attributes = self.vehicle_attributes
        if self._last_command_result is not None:
            attributes["last_control_result"] = self._last_command_result
        return attributes

    async def _async_send(self, open_value: bool, *, params: dict | None = None) -> None:
        payload = {
            "command": self._command_name,
            "open": bool(open_value),
            **(params or {}),
        }

        try:
            result = await self.coordinator.async_execute_control_command(
                self.vehicle.vehicle_id,
                self._function_code,
                params=payload,
                require_security_code=True,
                max_attempts=10,
                interval_seconds=2.0,
                sign_omit_keys={"command"},
            )
            self._last_command_result = _redact_sensitive(result)
            self.async_write_ha_state()
        except ControlCommandSigningError as err:
            raise HomeAssistantError(
                "Control signing is not configured yet. Please enable/configure the experimental signer first."
            ) from err
        except ValueError as err:
            raise HomeAssistantError(
                "Encrypted security code is missing. Add security_code_enc in integration options."
            ) from err
        except Exception as err:
            _LOGGER.warning("Mazda6e cover command failed: %s", err)
            raise HomeAssistantError(f"Cover command failed: {err}") from err


class Mazda6eWindowsCover(_Mazda6eControlCover):
    _attr_translation_key = "vehicle_windows"
    _attr_icon = "mdi:car-door"
    _attr_device_class = CoverDeviceClass.WINDOW
    _function_code = FUNCTION_CODE_WINDOWS
    _command_name = "window"

    def __init__(self, coordinator, vehicle: Mazda6eVehicle):
        super().__init__(coordinator, vehicle, key="vehicle_windows")

    @property
    def is_closed(self) -> bool | None:
        data = self.vehicle_data
        if not data:
            return None

        try:
            windows = data["status"]["window"]["windows"]
            return not any(bool(item) for item in windows)
        except Exception:
            return None

    async def async_open_cover(self, **kwargs):
        await self._async_send(True, params={"openType": WINDOWS_OPEN_TYPE_ALL})

    async def async_close_cover(self, **kwargs):
        await self._async_send(False, params={"openType": WINDOWS_OPEN_TYPE_ALL})


class Mazda6eTrunkCover(_Mazda6eControlCover):
    _attr_translation_key = "vehicle_trunk"
    _attr_icon = "mdi:car-back"
    _attr_device_class = CoverDeviceClass.DOOR
    _function_code = FUNCTION_CODE_TRUNK
    _command_name = "trunk"

    def __init__(self, coordinator, vehicle: Mazda6eVehicle):
        super().__init__(coordinator, vehicle, key="vehicle_trunk")

    @property
    def is_closed(self) -> bool | None:
        data = self.vehicle_data
        if not data:
            return None

        try:
            return not bool(data["status"]["door"].get("trunk"))
        except Exception:
            return None

    async def async_open_cover(self, **kwargs):
        await self._async_send(True)

    async def async_close_cover(self, **kwargs):
        await self._async_send(False)
