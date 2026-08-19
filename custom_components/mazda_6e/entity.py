from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .models import Mazda6eVehicle


class Mazda6eEntity(CoordinatorEntity):
    """Base entity tying an entity description to one vehicle of the coordinator."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, vehicle: Mazda6eVehicle, description):
        super().__init__(coordinator)
        self.entity_description = description
        self.vehicle = vehicle

        self._attr_unique_id = f"{vehicle.vehicle_id}_{description.key}"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(vehicle.vehicle_id))},
            name=f"{vehicle.car_name or 'Mazda 6e'} ({vehicle.vehicle_id})",
            serial_number=vehicle.vin,
            manufacturer="Mazda",
            model=vehicle.series_name or vehicle.model_name or "6e",
        )

    @property
    def vehicle_data(self) -> dict | None:
        return self.coordinator.data.get(self.vehicle.vehicle_id)
