import logging
import uuid

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers import aiohttp_client

from .const import (
    CONF_COMMAND_SIGNER_MODE,
    CONF_COMMAND_SIGNER_PRIVATE_KEY_PEM,
    CONF_ENABLE_EXPERIMENTAL_SIGNER,
    CONF_SECURITY_CODE_ENC,
    DOMAIN,
    SIGNER_MODE_RSA_PKCS1V15_SHA256,
)
from .api import Mazda6EApi

_LOGGER = logging.getLogger(__name__)

STEP1_SCHEMA = vol.Schema({
    vol.Required(CONF_EMAIL): str,
    vol.Required(CONF_PASSWORD): str,
    vol.Required("deviceid", default=str(uuid.uuid4())): str,
    vol.Optional(CONF_SECURITY_CODE_ENC): str,
})

STEP3_SCHEMA = vol.Schema({
    vol.Required("verification_code"): str
})


class Mazda6eConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self.device_name = None
        self.token = None
        self.deviceid = None
        self.email_enc = None
        self.security_code_enc = None
        self.api = None
        self.reauth_entry = None  # <--- for Reauth

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return Mazda6eOptionsFlow(config_entry)

    def _existing_security_code(self):
        if self.reauth_entry:
            return self.reauth_entry.options.get(
                CONF_SECURITY_CODE_ENC,
                self.reauth_entry.data.get(CONF_SECURITY_CODE_ENC),
            )
        return self.security_code_enc

    # ------------------------------------------------------------------
    # STEP 0: Re-Auth starten
    # ------------------------------------------------------------------
    async def async_step_reauth(self, user_input=None):
        """starts reauth, showing ui hint."""
        self.reauth_entry = self._get_reauth_entry()
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        """reauth have to ask for E-Mail + Password + DeviceID again."""
        if user_input is None:
            existing_security_code = self._existing_security_code()
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=vol.Schema({
                    vol.Required(CONF_EMAIL): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Required(
                        "deviceid",
                        default=self.reauth_entry.data.get("deviceid"),
                    ): str,
                    vol.Optional(
                        CONF_SECURITY_CODE_ENC,
                        default=existing_security_code or "",
                    ): str,
                }),
                description_placeholders={
                    "email": self.reauth_entry.data.get("email_enc", "<unknown>")
                }
            )

        return await self.async_step_user(user_input)

    def _get_reauth_entry(self):
        """Helper function for Reauth."""
        return self.hass.config_entries.async_get_entry(self.context["entry_id"])

    # ------------------------------------------------------------------
    # STEP 1: Login with mail + password
    # ------------------------------------------------------------------
    async def async_step_user(self, user_input=None):
        """Step 1: Email + Password + DeviceID """
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=STEP1_SCHEMA)

        self.api = Mazda6EApi(aiohttp_client.async_get_clientsession(self.hass), None, None, user_input["deviceid"])

        try:
            data = await self.api.login_email_password(
                user_input[CONF_EMAIL],
                user_input[CONF_PASSWORD]
            )
        except Exception as err:
            _LOGGER.error("Login failed: %s", err)
            return self.async_show_form(
                step_id="user",
                data_schema=STEP1_SCHEMA,
                errors={"base": "login_failed"},
            )

        self.email_enc = user_input[CONF_EMAIL]
        self.deviceid = user_input["deviceid"]
        self.security_code_enc = user_input.get(CONF_SECURITY_CODE_ENC) or self._existing_security_code()
        self.token = data["token"]

        try:
            await self.api.send_device_login(
                self.token,
                self.email_enc
            )
        except Exception as ex:
            _LOGGER.exception(
                "Unknown error occurred during device login request: %s", ex
            )
            return self.async_abort(reason="device_login_failed")

        return await self.async_step_verify()

    # ------------------------------------------------------------------
    # STEP 2: confirm device with code
    # ------------------------------------------------------------------
    async def async_step_verify(self, user_input=None):
        """Step 3: insert code from mail"""
        if user_input is None:
            return self.async_show_form(step_id="verify", data_schema=STEP3_SCHEMA)

        code = user_input["verification_code"]

        try:
            await self.api.verify_device_code(
                self.token,
                self.email_enc,
                code
            )
        except Exception as ex:
            _LOGGER.exception(
                "Unknown error occurred during email verify request: %s", ex
            )
            return self.async_show_form(
                step_id="verify",
                data_schema=STEP3_SCHEMA,
                errors={"base": "verification_failed"}
            )

        if self.reauth_entry:
            return self._handle_reauth_success()

        return self.async_create_entry(
            title="Mazda 6e Extended",
            data={
                "token": self.token,
                "refresh": self.api.refresh,
                "email_enc": self.email_enc,
                "deviceid": self.deviceid,
                CONF_SECURITY_CODE_ENC: self.security_code_enc,
            }
        )

    # ------------------------------------------------------------------
    #  finish Reauth
    # ------------------------------------------------------------------
    def _handle_reauth_success(self):
        """update entry & finish Flow."""
        self.hass.config_entries.async_update_entry(
            self.reauth_entry,
            data={
                "token": self.token,
                "refresh": self.api.refresh,
                "email_enc": self.email_enc,
                "deviceid": self.deviceid,
                CONF_SECURITY_CODE_ENC: self.security_code_enc,
            }
        )

        self.hass.async_create_task(
            self.hass.config_entries.async_reload(self.reauth_entry.entry_id)
        )

        return self.async_abort(reason="reauth_successful")


class Mazda6eOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            security_code_enc = user_input.get(CONF_SECURITY_CODE_ENC, "").strip()
            private_key_pem = user_input.get(CONF_COMMAND_SIGNER_PRIVATE_KEY_PEM, "").strip()
            options = dict(self.config_entry.options)

            if security_code_enc:
                options[CONF_SECURITY_CODE_ENC] = security_code_enc
            else:
                options.pop(CONF_SECURITY_CODE_ENC, None)

            options[CONF_ENABLE_EXPERIMENTAL_SIGNER] = bool(user_input.get(CONF_ENABLE_EXPERIMENTAL_SIGNER, False))

            signer_mode = user_input.get(CONF_COMMAND_SIGNER_MODE, SIGNER_MODE_RSA_PKCS1V15_SHA256)
            if signer_mode:
                options[CONF_COMMAND_SIGNER_MODE] = signer_mode
            else:
                options.pop(CONF_COMMAND_SIGNER_MODE, None)

            if private_key_pem:
                options[CONF_COMMAND_SIGNER_PRIVATE_KEY_PEM] = private_key_pem
            else:
                options.pop(CONF_COMMAND_SIGNER_PRIVATE_KEY_PEM, None)

            return self.async_create_entry(title="", data=options)

        current_value = self.config_entry.options.get(
            CONF_SECURITY_CODE_ENC,
            self.config_entry.data.get(CONF_SECURITY_CODE_ENC, ""),
        )
        current_private_key_pem = self.config_entry.options.get(
            CONF_COMMAND_SIGNER_PRIVATE_KEY_PEM,
            self.config_entry.data.get(CONF_COMMAND_SIGNER_PRIVATE_KEY_PEM, ""),
        )
        current_signer_mode = self.config_entry.options.get(
            CONF_COMMAND_SIGNER_MODE,
            self.config_entry.data.get(CONF_COMMAND_SIGNER_MODE, SIGNER_MODE_RSA_PKCS1V15_SHA256),
        )
        current_enable_signer = self.config_entry.options.get(
            CONF_ENABLE_EXPERIMENTAL_SIGNER,
            self.config_entry.data.get(CONF_ENABLE_EXPERIMENTAL_SIGNER, False),
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(CONF_SECURITY_CODE_ENC, default=current_value): str,
                vol.Optional(CONF_ENABLE_EXPERIMENTAL_SIGNER, default=current_enable_signer): bool,
                vol.Optional(CONF_COMMAND_SIGNER_MODE, default=current_signer_mode): vol.In(
                    [SIGNER_MODE_RSA_PKCS1V15_SHA256]
                ),
                vol.Optional(CONF_COMMAND_SIGNER_PRIVATE_KEY_PEM, default=current_private_key_pem): str,
            }),
        )
