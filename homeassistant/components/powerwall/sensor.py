"""Support for powerwall sensors."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from tesla_powerwall import MeterResponse, MeterType

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, POWERWALL_COORDINATOR
from .entity import PowerWallEntity
from .models import PowerwallRuntimeData

_METER_DIRECTION_EXPORT = "export"
_METER_DIRECTION_IMPORT = "import"


@dataclass(frozen=True)
class PowerwallRequiredKeysMixin:
    """Mixin for required keys."""

    value_fn: Callable[[MeterResponse], float]


@dataclass(frozen=True)
class PowerwallSensorEntityDescription(
    SensorEntityDescription, PowerwallRequiredKeysMixin
):
    """Describes Powerwall entity."""


def _get_meter_power(meter: MeterResponse) -> float:
    """Get the current value in kW."""
    return meter.get_power(precision=3)


def _get_meter_frequency(meter: MeterResponse) -> float:
    """Get the current value in Hz."""
    return round(meter.frequency, 1)


def _get_meter_total_current(meter: MeterResponse) -> float:
    """Get the current value in A."""
    return meter.get_instant_total_current()


def _get_meter_average_voltage(meter: MeterResponse) -> float:
    """Get the current value in V."""
    return round(meter.instant_average_voltage, 1)


POWERWALL_INSTANT_SENSORS = (
    PowerwallSensorEntityDescription(
        key="instant_power",
        translation_key="instant_power",
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        value_fn=_get_meter_power,
    ),
    PowerwallSensorEntityDescription(
        key="instant_frequency",
        translation_key="instant_frequency",
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.FREQUENCY,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        entity_registry_enabled_default=False,
        value_fn=_get_meter_frequency,
    ),
    PowerwallSensorEntityDescription(
        key="instant_current",
        translation_key="instant_current",
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        entity_registry_enabled_default=False,
        value_fn=_get_meter_total_current,
    ),
    PowerwallSensorEntityDescription(
        key="instant_voltage",
        translation_key="instant_voltage",
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        entity_registry_enabled_default=False,
        value_fn=_get_meter_average_voltage,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the powerwall sensors."""
    powerwall_data: PowerwallRuntimeData = hass.data[DOMAIN][config_entry.entry_id]
    coordinator = powerwall_data[POWERWALL_COORDINATOR]
    assert coordinator is not None
    data = coordinator.data
    entities: list[PowerWallEntity] = [
        PowerWallChargeSensor(powerwall_data),
    ]

    if data.backup_reserve is not None:
        entities.append(PowerWallBackupReserveSensor(powerwall_data))

    for meter in data.meters.meters:
        entities.append(PowerWallExportSensor(powerwall_data, meter))
        entities.append(PowerWallImportSensor(powerwall_data, meter))
        entities.extend(
            PowerWallEnergySensor(powerwall_data, meter, description)
            for description in POWERWALL_INSTANT_SENSORS
        )

    async_add_entities(entities)


class PowerWallChargeSensor(PowerWallEntity, SensorEntity):
    """Representation of an Powerwall charge sensor."""

    _attr_translation_key = "charge"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.BATTERY

    @property
    def unique_id(self) -> str:
        """Device Uniqueid."""
        return f"{self.base_unique_id}_charge"

    @property
    def native_value(self) -> int:
        """Get the current value in percentage."""
        return round(self.data.charge)


class PowerWallEnergySensor(PowerWallEntity, SensorEntity):
    """Representation of an Powerwall Energy sensor."""

    entity_description: PowerwallSensorEntityDescription

    def __init__(
        self,
        powerwall_data: PowerwallRuntimeData,
        meter: MeterType,
        description: PowerwallSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        super().__init__(powerwall_data)
        self._meter = meter
        self._attr_translation_key = f"{meter.value}_{description.translation_key}"
        self._attr_unique_id = f"{self.base_unique_id}_{meter.value}_{description.key}"

    @property
    def native_value(self) -> float | None:
        """Get the current value."""
        meter = self.data.meters.get_meter(self._meter)
        if meter is not None:
            return self.entity_description.value_fn(meter)

        return None


class PowerWallBackupReserveSensor(PowerWallEntity, SensorEntity):
    """Representation of the Powerwall backup reserve setting."""

    _attr_translation_key = "backup_reserve"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.BATTERY

    @property
    def unique_id(self) -> str:
        """Device Uniqueid."""
        return f"{self.base_unique_id}_backup_reserve"

    @property
    def native_value(self) -> int | None:
        """Get the current value in percentage."""
        if self.data.backup_reserve is None:
            return None
        return round(self.data.backup_reserve)


class PowerWallEnergyDirectionSensor(PowerWallEntity, SensorEntity):
    """Representation of an Powerwall Direction Energy sensor."""

    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY

    def __init__(
        self,
        powerwall_data: PowerwallRuntimeData,
        meter: MeterType,
        meter_direction: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(powerwall_data)
        self._meter = meter
        self._attr_translation_key = f"{meter.value}_{meter_direction}"
        self._attr_unique_id = f"{self.base_unique_id}_{meter.value}_{meter_direction}"

    @property
    def available(self) -> bool:
        """Check if the reading is actually available.

        The device reports 0 when something goes wrong which
        we do not want to include in statistics and its a
        transient data error.
        """
        return super().available and self.meter is not None

    @property
    def meter(self) -> MeterResponse | None:
        """Get the meter for the sensor."""
        return self.data.meters.get_meter(self._meter)


class PowerWallExportSensor(PowerWallEnergyDirectionSensor):
    """Representation of an Powerwall Export sensor."""

    def __init__(
        self,
        powerwall_data: PowerwallRuntimeData,
        meter: MeterType,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(powerwall_data, meter, _METER_DIRECTION_EXPORT)

    @property
    def native_value(self) -> float | None:
        """Get the current value in kWh."""
        meter = self.meter
        if TYPE_CHECKING:
            assert meter is not None
        return meter.get_energy_exported()


class PowerWallImportSensor(PowerWallEnergyDirectionSensor):
    """Representation of an Powerwall Import sensor."""

    def __init__(
        self,
        powerwall_data: PowerwallRuntimeData,
        meter: MeterType,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(powerwall_data, meter, _METER_DIRECTION_IMPORT)

    @property
    def native_value(self) -> float | None:
        """Get the current value in kWh."""
        meter = self.meter
        if TYPE_CHECKING:
            assert meter is not None
        return meter.get_energy_imported()
