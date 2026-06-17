"""Base entity class for the Roulez Électrique (BETA) integration.

Each physical charger becomes one HA Device. All entity types (sensor,
binary_sensor, switch) inherit from RoulezElectriqueEntity and share:

  - DeviceInfo derived from the charger dict
  - Coordinator reference for data access
  - Availability tied to coordinator success + charger `online` flag
"""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import RoulezElectriqueCoordinator


class RoulezElectriqueEntity(CoordinatorEntity[RoulezElectriqueCoordinator]):
    """Base class for all Roulez Électrique entities.

    Subclasses must set `_attr_unique_id` and `_attr_translation_key`.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: RoulezElectriqueCoordinator,
        charger_id: int,
    ) -> None:
        super().__init__(coordinator)
        self._charger_id = charger_id
        # Device: one per charger
        charger = self._charger_data
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(charger_id))},
            name=charger.get("name") or charger.get("serial_number") or f"Charger {charger_id}",
            manufacturer=charger.get("vendor_label") or charger.get("vendor"),
            model=charger.get("vendor_label"),
            serial_number=charger.get("serial_number"),
        )

    @property
    def _charger_data(self) -> dict[str, Any]:
        """Return the latest data dict for this charger.

        Returns an empty dict if the coordinator has no data for this charger
        (the entity will be unavailable until the next successful refresh).
        """
        if self.coordinator.data is None:
            return {}
        return self.coordinator.data.get(self._charger_id, {})

    @property
    def available(self) -> bool:
        """Mark unavailable when the coordinator failed its last refresh."""
        return super().available and bool(self._charger_data)
