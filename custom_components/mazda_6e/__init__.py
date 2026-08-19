import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import aiohttp_client
from homeassistant.const import Platform
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.exceptions import HomeAssistantError

from .api import Mazda6EApi
from .const import (
    ATTR_VEHICLE_ID,
    CONF_COMMAND_SIGNER_MODE,
    CONF_COMMAND_SIGNER_PRIVATE_KEY_PEM,
    CONF_ENABLE_EXPERIMENTAL_SIGNER,
    CONF_SECURITY_CODE_ENC,
    DOMAIN,
    SIGNER_MODE_RSA_PKCS1V15_SHA256,
    SERVICE_SECURITY_CODE_STATUS,
    SERVICE_VALIDATE_SECURITY_CODE,
)
from .coordinator import Mazda6eCoordinator
from .signers import build_command_signer

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.DEVICE_TRACKER,
    Platform.LOCK,
    Platform.SENSOR,
]

_LOGGER = logging.getLogger(__name__)

SERVICE_SCHEMA = vol.Schema({vol.Optional(ATTR_VEHICLE_ID): vol.Coerce(int)})
SENSITIVE_RESULT_KEYS = {"token", "rctoken", "safecode", "securitycode", "sign"}


def _redact_sensitive(value):
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            if key.lower() in SENSITIVE_RESULT_KEYS:
                redacted[key] = "REDACTED"
            else:
                redacted[key] = _redact_sensitive(item)
        return redacted

    if isinstance(value, list):
        return [_redact_sensitive(item) for item in value]

    return value


def _iter_target_vehicles(hass: HomeAssistant, target_vehicle_id: int | None):
    for coordinator in hass.data.get(DOMAIN, {}).values():
        for vehicle_id in coordinator.data.keys():
            if target_vehicle_id is not None and vehicle_id != target_vehicle_id:
                continue
            yield coordinator, vehicle_id


async def _async_handle_security_code_status(hass: HomeAssistant, call: ServiceCall):
    target_vehicle_id = call.data.get(ATTR_VEHICLE_ID)
    payload = []

    for coordinator, vehicle_id in _iter_target_vehicles(hass, target_vehicle_id):
        try:
            status = await coordinator.api.async_get_security_code_status(vehicle_id)
            payload.append(
                {
                    "vehicle_id": vehicle_id,
                    "ok": True,
                    "status": _redact_sensitive(status),
                }
            )
        except Exception as err:
            payload.append(
                {
                    "vehicle_id": vehicle_id,
                    "ok": False,
                    "error": str(err),
                }
            )

    if not payload:
        raise HomeAssistantError("No matching vehicle found")

    _LOGGER.info("Security code status response: %s", payload)
    hass.bus.async_fire(f"{DOMAIN}_security_code_status", {"results": payload})


async def _async_handle_validate_security_code(hass: HomeAssistant, call: ServiceCall):
    target_vehicle_id = call.data.get(ATTR_VEHICLE_ID)
    payload = []

    for coordinator, vehicle_id in _iter_target_vehicles(hass, target_vehicle_id):
        try:
            result = await coordinator.api.async_check_security_code(vehicle_id)
            payload.append(
                {
                    "vehicle_id": vehicle_id,
                    "ok": True,
                    "result": _redact_sensitive(result),
                }
            )
        except Exception as err:
            payload.append(
                {
                    "vehicle_id": vehicle_id,
                    "ok": False,
                    "error": str(err),
                }
            )

    if not payload:
        raise HomeAssistantError("No matching vehicle found")

    _LOGGER.info("Security code validation response: %s", payload)
    hass.bus.async_fire(f"{DOMAIN}_validate_security_code", {"results": payload})


def _async_register_services(hass: HomeAssistant) -> None:
    async def _handle_security_code_status(call: ServiceCall):
        await _async_handle_security_code_status(hass, call)

    async def _handle_validate_security_code(call: ServiceCall):
        await _async_handle_validate_security_code(hass, call)

    if not hass.services.has_service(DOMAIN, SERVICE_SECURITY_CODE_STATUS):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SECURITY_CODE_STATUS,
            _handle_security_code_status,
            schema=SERVICE_SCHEMA,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_VALIDATE_SECURITY_CODE):
        hass.services.async_register(
            DOMAIN,
            SERVICE_VALIDATE_SECURITY_CODE,
            _handle_validate_security_code,
            schema=SERVICE_SCHEMA,
        )


def _async_unregister_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_SECURITY_CODE_STATUS):
        hass.services.async_remove(DOMAIN, SERVICE_SECURITY_CODE_STATUS)
    if hass.services.has_service(DOMAIN, SERVICE_VALIDATE_SECURITY_CODE):
        hass.services.async_remove(DOMAIN, SERVICE_VALIDATE_SECURITY_CODE)


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    _LOGGER.info("Setting up Mazda 6E integration")

    security_code_enc = config_entry.options.get(
        CONF_SECURITY_CODE_ENC,
        config_entry.data.get(CONF_SECURITY_CODE_ENC),
    )

    mazda6e_api = Mazda6EApi(
        aiohttp_client.async_get_clientsession(hass),
        config_entry.data["token"],
        config_entry.data["refresh"],
        config_entry.data["deviceid"],
        security_code_enc,
    )

    enable_experimental_signer = bool(
        config_entry.options.get(
            CONF_ENABLE_EXPERIMENTAL_SIGNER,
            config_entry.data.get(CONF_ENABLE_EXPERIMENTAL_SIGNER, False),
        )
    )
    if enable_experimental_signer:
        signer_mode = config_entry.options.get(
            CONF_COMMAND_SIGNER_MODE,
            config_entry.data.get(CONF_COMMAND_SIGNER_MODE, SIGNER_MODE_RSA_PKCS1V15_SHA256),
        )
        private_key_pem = config_entry.options.get(
            CONF_COMMAND_SIGNER_PRIVATE_KEY_PEM,
            config_entry.data.get(CONF_COMMAND_SIGNER_PRIVATE_KEY_PEM),
        )

        if not private_key_pem:
            _LOGGER.warning(
                "Experimental command signer enabled but private key is missing; control signing remains unavailable"
            )
        else:
            try:
                mazda6e_api.set_control_signer(build_command_signer(signer_mode, private_key_pem))
                _LOGGER.info("Experimental command signer enabled: %s", signer_mode)
            except Exception as err:
                _LOGGER.warning(
                    "Failed to initialize experimental command signer (%s): %s",
                    signer_mode,
                    err,
                )

    coordinator = Mazda6eCoordinator(hass, config_entry, mazda6e_api)

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:
        if getattr(err, "status", None) in (401, 403):
            _LOGGER.warning("Authentication failed: %s – triggering reauth", err)
            raise ConfigEntryAuthFailed from err

        raise

    hass.data.setdefault(DOMAIN, {})[config_entry.entry_id] = coordinator
    _async_register_services(hass)

    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    hass.data[DOMAIN].pop(entry.entry_id)

    if not hass.data[DOMAIN]:
        _async_unregister_services(hass)
        hass.data.pop(DOMAIN)

    return True
