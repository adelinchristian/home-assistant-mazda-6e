from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import ControlCommandSigningError
from .const import (
    DOMAIN,
    FLASH_HONK_CAPABILITY_CANDIDATES,
    FLASH_LIGHTS_ACTION_TYPE,
    FUNCTION_CODE_FLASH_HONK,
    HONK_HORN_ACTION_TYPE,
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


def _supports_flash_honk(vehicle: Mazda6eVehicle) -> bool:
    if not vehicle.functions:
        return True
    return any(code in vehicle.functions for code in FLASH_HONK_CAPABILITY_CANDIDATES)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []

    for data in coordinator.data.values():
        vehicle: Mazda6eVehicle = data["vehicle"]
        if not _supports_flash_honk(vehicle):
            continue

        entities.extend(
            [
                Mazda6eFlashLightsButton(coordinator=coordinator, vehicle=vehicle),
                Mazda6eHonkHornButton(coordinator=coordinator, vehicle=vehicle),
            ]
        )

    async_add_entities(entities)


class _Mazda6eFlashHonkButton(Mazda6eEntity, ButtonEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _action_type: int

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

    async def async_press(self) -> None:
        params = {
            "command": "flash_bee",
            "type": self._action_type,
        }

        sign_omit_keys = {"command"}

        try:
            result = await self.coordinator.async_execute_control_command(
                self.vehicle.vehicle_id,
                FUNCTION_CODE_FLASH_HONK,
                params=params,
                require_security_code=False,
                max_attempts=10,
                interval_seconds=2.0,
                sign_omit_keys=sign_omit_keys,
            )
            self._last_command_result = _redact_sensitive(result)
            self.async_write_ha_state()
        except ControlCommandSigningError as err:
            raise HomeAssistantError(
                "Control signing is not configured yet. Please enable/configure the experimental signer first."
            ) from err
        except Exception as err:
            _LOGGER.warning("Mazda6e flash/honk command failed: %s", err)
            raise HomeAssistantError(f"Flash/honk command failed: {err}") from err


class Mazda6eFlashLightsButton(_Mazda6eFlashHonkButton):
    _attr_translation_key = "flash_lights"
    _attr_icon = "mdi:car-light-alert"
    _action_type = FLASH_LIGHTS_ACTION_TYPE

    def __init__(self, coordinator, vehicle: Mazda6eVehicle):
        super().__init__(coordinator, vehicle, key="flash_lights")


class Mazda6eHonkHornButton(_Mazda6eFlashHonkButton):
    _attr_translation_key = "honk_horn"
    _attr_icon = "mdi:bullhorn"
    _action_type = HONK_HORN_ACTION_TYPE

    def __init__(self, coordinator, vehicle: Mazda6eVehicle):
        super().__init__(coordinator, vehicle, key="honk_horn")
