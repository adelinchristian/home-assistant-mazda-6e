"""Button controls for Mazda 6e vehicles."""

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .entity import Mazda6eEntity

DESCRIPTION = ButtonEntityDescription(
    key="find_vehicle",
    translation_key="find_vehicle",
    icon="mdi:car-search",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up vehicle find buttons."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        Mazda6eFindVehicleButton(coordinator, item["vehicle"])
        for item in coordinator.data.values()
        if item["vehicle"].supports("FlashHonk")
    )


class Mazda6eFindVehicleButton(Mazda6eEntity, ButtonEntity):
    """Trigger Mazda's flashing-and-honking find-vehicle command."""

    def __init__(self, coordinator, vehicle) -> None:
        super().__init__(coordinator, vehicle, DESCRIPTION)

    @property
    def available(self) -> bool:
        return super().available and bool(self.coordinator.api.control_private_key)

    async def async_press(self) -> None:
        await self.coordinator.api.async_find_vehicle(self.vehicle.vehicle_id)
        await self.coordinator.async_request_refresh()