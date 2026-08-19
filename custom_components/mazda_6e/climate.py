from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature, HVACMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import ControlCommandSigningError
from .const import (
    DOMAIN,
    FUNCTION_CODE_HVAC,
    FUNCTION_CODE_HVAC_OFF,
    HVAC_CAPABILITY_CANDIDATES,
)
from .entity import Mazda6eEntity
from .helpers.validators import temperature
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


def _supports_hvac_commands(vehicle: Mazda6eVehicle) -> bool:
    if not vehicle.functions:
        return True
    return any(code in vehicle.functions for code in HVAC_CAPABILITY_CANDIDATES)


def _to_celsius(value: Any) -> float | None:
    celsius = temperature(value)
    if celsius is None:
        return None
    return float(celsius)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []

    for data in coordinator.data.values():
        vehicle: Mazda6eVehicle = data["vehicle"]
        if not _supports_hvac_commands(vehicle):
            continue

        try:
            data["status"]["hvac"]["acStatus"]
        except Exception:
            continue

        entities.append(Mazda6eClimate(coordinator=coordinator, vehicle=vehicle))

    async_add_entities(entities)


class Mazda6eClimate(Mazda6eEntity, ClimateEntity):
    _attr_translation_key = "cabin_climate"
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT_COOL]
    _attr_min_temp = 16.0
    _attr_max_temp = 30.0
    _attr_target_temperature_step = 0.5
    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator, vehicle: Mazda6eVehicle):
        class _Description:
            key = "cabin_climate"

        super().__init__(coordinator=coordinator, vehicle=vehicle, description=_Description())
        self._last_command_result: dict | None = None

    @property
    def supported_features(self) -> ClimateEntityFeature:
        return ClimateEntityFeature.TARGET_TEMPERATURE

    @property
    def hvac_mode(self) -> HVACMode | None:
        data = self.vehicle_data
        if not data:
            return None

        try:
            ac_status = data["status"]["hvac"].get("acStatus")
        except Exception:
            return None

        if ac_status is None:
            return None
        return HVACMode.HEAT_COOL if int(ac_status) != 0 else HVACMode.OFF

    @property
    def current_temperature(self) -> float | None:
        data = self.vehicle_data
        if not data:
            return None

        try:
            return _to_celsius(data["status"]["hvac"].get("insideTemp"))
        except Exception:
            return None

    @property
    def target_temperature(self) -> float | None:
        data = self.vehicle_data
        if not data:
            return None

        try:
            return _to_celsius(data["status"]["hvac"].get("remoteTemp"))
        except Exception:
            return None

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
        data = self.vehicle_data or {}
        hvac = (data.get("status") or {}).get("hvac") or {}

        attributes = self.vehicle_attributes
        attributes.update(
            {
                "inside_humidity": hvac.get("insideHumidity"),
                "defrost_status": hvac.get("defrostStatus"),
                "inside_pm25": hvac.get("insidePm25"),
            }
        )
        if self._last_command_result is not None:
            attributes["last_control_result"] = self._last_command_result
        return attributes

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self.async_turn_off()
            return

        if hvac_mode == HVACMode.HEAT_COOL:
            await self.async_turn_on()
            return

        raise HomeAssistantError(f"Unsupported HVAC mode: {hvac_mode}")

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature_c = kwargs.get("temperature")
        if temperature_c is None:
            return

        await self._async_send_hvac(enabled=True, target_temp_c=float(temperature_c))

    async def async_turn_on(self) -> None:
        await self._async_send_hvac(
            enabled=True,
            target_temp_c=self.target_temperature or 21.0,
        )

    async def async_turn_off(self) -> None:
        await self._async_send_hvac(
            enabled=False,
            target_temp_c=self.target_temperature or 21.0,
        )

    async def _async_send_hvac(self, *, enabled: bool, target_temp_c: float) -> None:
        function_code = FUNCTION_CODE_HVAC if enabled else FUNCTION_CODE_HVAC_OFF
        target_tenths = int(round(float(target_temp_c) * 10))

        params = {
            "enabled": bool(enabled),
            "targetTemp": target_tenths,
            "command": "air",
        }

        sign_omit_keys = {"command", "rcToken"}

        try:
            result = await self.coordinator.async_execute_control_command(
                self.vehicle.vehicle_id,
                function_code,
                params=params,
                require_security_code=False,
                max_attempts=12,
                interval_seconds=2.0,
                sign_omit_keys=sign_omit_keys,
            )
            self._last_command_result = _redact_sensitive(result)
            self.async_write_ha_state()
        except ControlCommandSigningError as err:
            raise HomeAssistantError(
                "Control signing is not configured yet. Please enable/configure the experimental signer first."
            ) from err
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        except Exception as err:
            _LOGGER.warning("Mazda6e climate command failed: %s", err)
            raise HomeAssistantError(f"HVAC command failed: {err}") from err
