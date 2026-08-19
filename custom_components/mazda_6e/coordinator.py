import logging

from datetime import timedelta
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.exceptions import ConfigEntryAuthFailed

from .const import DOMAIN, UPDATE_INTERVAL
from .models import Mazda6eVehicle

_LOGGER = logging.getLogger(__name__)


class Mazda6eCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, config_entry, mazda6e_api):
        """Initialize my coordinator."""
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            config_entry=config_entry,
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )
        self.api = mazda6e_api
        self._function_config: dict[int, set[str]] = {}

    async def _async_get_function_config(self, vehicle_id: int) -> set[str]:
        """Fetch the vehicle's supported functions once and cache them."""
        if vehicle_id not in self._function_config:
            try:
                self._function_config[vehicle_id] = await self.api.async_get_function_config(vehicle_id)
            except Exception as err:
                _LOGGER.debug("Could not read function config for %s: %s", vehicle_id, err)
                self._function_config[vehicle_id] = set()

        return self._function_config[vehicle_id]

    async def _async_update_data(self):
        """Fetch data from API"""

        # get vehicles
        vehicles_response = await self.api.async_get_vehicles()

        _LOGGER.debug("vehicles_response: %s", vehicles_response)

        vehicles: list[Mazda6eVehicle] = vehicles_response
        vehicle_status = {}

        # get status for each vehicle
        for veh in vehicles:
            veh.functions = await self._async_get_function_config(veh.vehicle_id)
            status_response = await self.api.async_get_vehicle_status(veh.vehicle_id)

            vehicle_status[veh.vehicle_id] = {
                "vehicle": veh,
                "status": status_response,
            }

        _LOGGER.debug("vehicle_status: %s", vehicle_status)
        return vehicle_status
