import aiohttp
import asyncio
import time
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from .const import PUB_KEY, DEVICE_NAME
from .models import Mazda6eVehicle
from homeassistant.exceptions import ConfigEntryAuthFailed

_LOGGER = logging.getLogger(__name__)

BASE = "https://cma-m.iov.changanauto.com.de/cma-app-gw"

HEADERS_BASE = {
    "content-type": "application/json",
    "devicetype": "iPhone",
    "apptype": "IOS",
    "appid": "cma",
    "accept": "*/*",
    "appversion": "V1.2.2",
    "accept-language": "en-US;q=1.0",
    "user-agent": "overseas/1.2.2 (com.mazda.mazda6e; build:6; iPhone 17 Pro Max; iOS 26.6) Alamofire/5.5.0",
    "language": "en_US",
}


CONTROL_SERIAL_ENDPOINT = f"{BASE}/cma-app-user/api/serial-no/get"
CONTROL_SUBMIT_ENDPOINT = f"{BASE}/cma-app-user/api/control-command/send"
CONTROL_RESULT_ENDPOINT = f"{BASE}/cma-app-user/api/control-command/result"


def now_ts():
    return str(int(time.time()))


class ControlCommandSigningError(Exception):
    """Raised when a control command cannot be signed."""


class Mazda6EApi:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        token=None,
        refresh=None,
        deviceid=None,
        security_code_enc: str | None = None,
    ):
        self.session = session
        self.token = token
        self.refresh = refresh
        self.deviceid = deviceid
        self.security_code_enc = security_code_enc
        self._signer: Callable[[dict[str, Any]], str | Awaitable[str]] | None = None

    def set_control_signer(self, signer: Callable[[dict[str, Any]], str | Awaitable[str]]) -> None:
        """Set a signer function that returns the control-command signature."""
        self._signer = signer

    async def _async_sign_control_payload(self, payload: dict[str, Any]) -> str:
        """Sign control payload using configured signer hook."""
        if self._signer is None:
            raise ControlCommandSigningError(
                "Control signer not configured. Implement set_control_signer() first."
            )

        sign_result = self._signer(payload)
        if asyncio.iscoroutine(sign_result):
            sign_result = await sign_result

        if not sign_result:
            raise ControlCommandSigningError("Control signer returned an empty signature")

        return sign_result

    async def _request(self, url: str, headers: dict, body: dict, retry: bool = True):
        """generic request method with token refresh handling"""
        async with self.session.post(url, headers=headers, json=body) as resp:
            raw = await resp.json()

        if raw.get("success") is True:
            return raw

        # token expired
        if raw.get("code") == "APP_1_1_02_004":
            if not retry:
                raise ConfigEntryAuthFailed("Token expired and refresh failed")

            _LOGGER.debug("Token expired -> refreshing token...")
            await self.refresh_token()

            headers = {**headers, "authorization": self.token}

            # try again once
            return await self._request(url, headers, body, retry=False)
        raise Exception(f"Mazda API error: {raw}")

    async def login_email_password(self, email_enc, password_enc):
        url = f"{BASE}/cma-app-auth/api/login/email-pass-in/v2"
        payload = {
            "loginTime": now_ts(),
            "email": email_enc,
            "password": password_enc,
            "pubKey": PUB_KEY
        }
        headers = {**HEADERS_BASE, "deviceid": self.deviceid}

        async with self.session.post(url, json=payload, headers=headers) as resp:
            data = await resp.json()

            if not data.get("success"):
                raise Exception("Email/Password Login failed")

            self.token = data["data"]["token"]
            self.refresh = data["data"]["refreshToken"]
            return data["data"]

    async def send_device_login(self, token, email_enc):
        url = f"{BASE}/cma-app-user/api/send-email/device-login/send"
        payload = {
            "email": email_enc,
            "deviceName": DEVICE_NAME,
            "loginTime": now_ts(),
            "type": "1"
        }
        headers = {**HEADERS_BASE, "authorization": token, "deviceid": self.deviceid}

        await self._request(url, headers, payload)
        return True

    async def verify_device_code(self, token, email_enc, code):
        url = f"{BASE}/cma-app-user/api/login-device/email-verify"
        payload = {
            "authCode": code,
            "email": email_enc,
            "deviceName": DEVICE_NAME,
            "lastLoginTime": now_ts(),
            "type": "3",
            "deviceModel": DEVICE_NAME
        }
        headers = {**HEADERS_BASE, "authorization": token, "deviceid": self.deviceid}

        await self._request(url, headers, payload)
        return True

    async def refresh_token(self):
        url = f"{BASE}/cma-app-auth/api/auth/refresh-token"
        headers = {**HEADERS_BASE, "authorization": self.token}

        body = {"refreshToken": self.refresh}

        async with self.session.post(url, headers=headers, json=body) as resp:
            raw = await resp.json()

        _LOGGER.debug("refresh-token response: %s", raw)

        if not raw.get("success"):
            raise ConfigEntryAuthFailed("Token refresh failed")

        self.token = raw["data"]["token"]
        self.refresh = raw["data"]["refreshToken"]
        return self.token

    async def async_get_vehicles(self) -> list[Mazda6eVehicle]:
        headers = {
            **HEADERS_BASE,
            "authorization": self.token,
            "deviceid": self.deviceid,
        }

        try:
            raw = await self._request(
                f"{BASE}/cma-app-user/api/vehicle/vehicles",
                headers,
                {},
            )
        except Exception as err:
            _LOGGER.debug("Legacy vehicle endpoint unavailable: %s", err)
            raw = await self._request(
                f"{BASE}/cma-app-user/api/car/vehicles",
                headers,
                {},
            )

        vehicles = []
        for v in raw.get("data", []):
            vehicles.append(
                Mazda6eVehicle(
                    vehicle_id=v.get("carId") or v["vehicleId"],
                    vin=v["vin"],
                    model_name=v["modelName"],
                    car_name=v.get("carName"),
                    plate_number=v.get("plateNumber"),
                    series_name=v.get("seriesName"),
                )
            )
        return vehicles

    async def async_get_function_config(self, vehicle_id: int) -> set[str]:
        """Return the function codes the vehicle supports (e.g. '#findCar', 'ACSW')."""
        url = f"{BASE}/cma-app-user/api/vehicle/function-config"
        headers = {
            **HEADERS_BASE,
            "authorization": self.token,
            "deviceid": self.deviceid,
        }

        raw = await self._request(url, headers, {"vehicleId": vehicle_id})
        return set((raw.get("data") or {}).get("confList") or [])

    async def async_get_vehicle_status(self, vehicle_id: int):
        url = f"{BASE}/cma-app-car-condition/api/vehicle/condition/v2"
        headers = {
            **HEADERS_BASE,
            "authorization": self.token,
            "deviceid": self.deviceid,
        }

        body = {
            "vechileCriteria": {
                "seat": "1",
                "tire": "1",
                "charge": "1",
                "vehicleStatus": "1",
                "hvac": "1",
                "departurePlan": "0",
                "fuel": "0",
                "window": "1",
                "door": "1",
                "airConditionPlan": "0",
                "lamp": "1",
                "warmCoolingBox": "0",
                "welcome": "0",
                "location": "1"
            },
            "vehicleId": vehicle_id
        }

        raw = await self._request(url, headers, body)
        return raw.get("data")

    async def async_get_security_code_status(self, vehicle_id: int) -> dict:
        """Get security-code status from backend for a specific vehicle."""
        url = f"{BASE}/cma-app-user/api/security-code/get-status"
        headers = {
            **HEADERS_BASE,
            "authorization": self.token,
            "deviceid": self.deviceid,
        }

        raw = await self._request(url, headers, {"vehicleId": vehicle_id})
        return raw.get("data") or {}

    async def async_check_security_code(self, vehicle_id: int, security_code_enc: str | None = None) -> dict:
        """Validate an encrypted security code and retrieve the returned code token data."""
        safe_code = security_code_enc or self.security_code_enc
        if not safe_code:
            raise ValueError("Missing encrypted security code")

        url = f"{BASE}/cma-app-user/api/security-code/check-code"
        headers = {
            **HEADERS_BASE,
            "authorization": self.token,
            "deviceid": self.deviceid,
        }

        raw = await self._request(
            url,
            headers,
            {
                "vehicleId": vehicle_id,
                "safeCode": safe_code,
            },
        )
        return raw.get("data") or {}

    async def async_get_control_serial_no(self, vehicle_id: int) -> str:
        """Request a serial number for control-command submission."""
        headers = {
            **HEADERS_BASE,
            "authorization": self.token,
            "deviceid": self.deviceid,
        }

        raw = await self._request(CONTROL_SERIAL_ENDPOINT, headers, {"vehicleId": vehicle_id})
        data = raw.get("data") or {}
        serial_no = data.get("serialNo") or data.get("serialNO") or data.get("serial")
        if not serial_no:
            raise Exception(f"Control serial number missing in response: {data}")
        return str(serial_no)

    async def async_submit_control_command(
        self,
        vehicle_id: int,
        function_code: str,
        *,
        params: dict[str, Any] | None = None,
        require_security_code: bool = False,
        security_code_enc: str | None = None,
        submit_endpoint: str = CONTROL_SUBMIT_ENDPOINT,
        sign_omit_keys: set[str] | None = None,
    ) -> dict:
        """Submit a control command using serial + sign (+ optional rcToken) flow."""
        headers = {
            **HEADERS_BASE,
            "authorization": self.token,
            "deviceid": self.deviceid,
        }

        serial_no = await self.async_get_control_serial_no(vehicle_id)

        command_payload = {
            "vehicleId": vehicle_id,
            "functionCode": function_code,
            "serialNo": serial_no,
            **(params or {}),
        }

        if require_security_code:
            security_data = await self.async_check_security_code(vehicle_id, security_code_enc=security_code_enc)
            rc_token = security_data.get("rcToken") or security_data.get("token")
            if not rc_token:
                raise Exception(f"Control rcToken missing in security-code response: {security_data}")
            command_payload["rcToken"] = rc_token

        sign_payload = dict(command_payload)
        if sign_omit_keys:
            for key in sign_omit_keys:
                sign_payload.pop(key, None)

        command_payload["sign"] = await self._async_sign_control_payload(sign_payload)

        raw = await self._request(submit_endpoint, headers, command_payload)
        return raw.get("data") or {}

    async def async_poll_control_command_result(
        self,
        *,
        vehicle_id: int,
        serial_no: str,
        poll_endpoint: str = CONTROL_RESULT_ENDPOINT,
        max_attempts: int = 12,
        interval_seconds: float = 2.0,
    ) -> dict:
        """Poll command result endpoint until a final state is returned or timeout occurs."""
        headers = {
            **HEADERS_BASE,
            "authorization": self.token,
            "deviceid": self.deviceid,
        }

        last_data: dict[str, Any] = {}
        for _ in range(max_attempts):
            raw = await self._request(
                poll_endpoint,
                headers,
                {
                    "vehicleId": vehicle_id,
                    "serialNo": serial_no,
                },
            )
            data = raw.get("data") or {}
            last_data = data

            if data.get("finished") is True or data.get("done") is True:
                return data

            status = str(data.get("status", "")).upper()
            if status in {"SUCCESS", "FAILED", "ERROR", "TIMEOUT", "CANCELLED"}:
                return data

            await asyncio.sleep(interval_seconds)

        return {
            "status": "TIMEOUT",
            "message": "Control command result polling timed out",
            "last": last_data,
        }

    async def async_submit_and_poll_control_command(
        self,
        vehicle_id: int,
        function_code: str,
        *,
        params: dict[str, Any] | None = None,
        require_security_code: bool = False,
        security_code_enc: str | None = None,
        submit_endpoint: str = CONTROL_SUBMIT_ENDPOINT,
        poll_endpoint: str = CONTROL_RESULT_ENDPOINT,
        max_attempts: int = 12,
        interval_seconds: float = 2.0,
        sign_omit_keys: set[str] | None = None,
    ) -> dict:
        """Submit a control command and wait for final status through polling."""
        submit_data = await self.async_submit_control_command(
            vehicle_id,
            function_code,
            params=params,
            require_security_code=require_security_code,
            security_code_enc=security_code_enc,
            submit_endpoint=submit_endpoint,
            sign_omit_keys=sign_omit_keys,
        )

        serial_no = (
            submit_data.get("serialNo")
            or submit_data.get("serialNO")
            or submit_data.get("serial")
        )
        if not serial_no:
            raise Exception(f"Control submit response does not include serial number: {submit_data}")

        result_data = await self.async_poll_control_command_result(
            vehicle_id=vehicle_id,
            serial_no=str(serial_no),
            poll_endpoint=poll_endpoint,
            max_attempts=max_attempts,
            interval_seconds=interval_seconds,
        )

        return {
            "submit": submit_data,
            "result": result_data,
        }
