# Copyright 2017 Red Hat, Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import collections

from oslo_log import log
from oslo_utils import importutils

from ironic.common import boot_devices
from ironic.common import boot_modes
from ironic.common import components
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import indicator_states
from ironic.conductor import task_manager
from ironic.drivers import base
from ironic.drivers.modules.redfish import utils as redfish_utils

LOG = log.getLogger(__name__)

sushy = importutils.try_import('sushy')

if sushy:
    BOOT_DEVICE_MAP = {
        sushy.BOOT_SOURCE_TARGET_PXE: boot_devices.PXE,
        sushy.BOOT_SOURCE_TARGET_HDD: boot_devices.DISK,
        sushy.BOOT_SOURCE_TARGET_CD: boot_devices.CDROM,
        sushy.BOOT_SOURCE_TARGET_BIOS_SETUP: boot_devices.BIOS
    }

    BOOT_DEVICE_MAP_REV = {v: k for k, v in BOOT_DEVICE_MAP.items()}

    BOOT_MODE_MAP = {
        sushy.BOOT_SOURCE_MODE_UEFI: boot_modes.UEFI,
        sushy.BOOT_SOURCE_MODE_BIOS: boot_modes.LEGACY_BIOS
    }

    BOOT_MODE_MAP_REV = {v: k for k, v in BOOT_MODE_MAP.items()}

    BOOT_DEVICE_PERSISTENT_MAP = {
        sushy.BOOT_SOURCE_ENABLED_CONTINUOUS: True,
        sushy.BOOT_SOURCE_ENABLED_ONCE: False
    }

    BOOT_DEVICE_PERSISTENT_MAP_REV = {v: k for k, v in
                                      BOOT_DEVICE_PERSISTENT_MAP.items()}

    INDICATOR_MAP = {
        sushy.INDICATOR_LED_LIT: indicator_states.ON,
        sushy.INDICATOR_LED_OFF: indicator_states.OFF,
        sushy.INDICATOR_LED_BLINKING: indicator_states.BLINKING,
        sushy.INDICATOR_LED_UNKNOWN: indicator_states.UNKNOWN
    }

    INDICATOR_MAP_REV = {
        v: k for k, v in INDICATOR_MAP.items()}


class RedfishManagement(base.ManagementInterface):

    def __init__(self):
        """Initialize the Redfish management interface.

        :raises: DriverLoadError if the driver can't be loaded due to
            missing dependencies
        """
        super(RedfishManagement, self).__init__()
        if not sushy:
            raise exception.DriverLoadError(
                driver='redfish',
                reason=_('Unable to import the sushy library'))

    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """
        return redfish_utils.COMMON_PROPERTIES.copy()

    def validate(self, task):
        """Validates the driver information needed by the redfish driver.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue on malformed parameter(s)
        :raises: MissingParameterValue on missing parameter(s)
        """
        redfish_utils.parse_driver_info(task.node)

    def get_supported_boot_devices(self, task):
        """Get a list of the supported boot devices.

        :param task: a task from TaskManager.
        :returns: A list with the supported boot devices defined
                  in :mod:`ironic.common.boot_devices`.
        """
        return list(BOOT_DEVICE_MAP_REV)

    @task_manager.require_exclusive_lock
    def set_boot_device(self, task, device, persistent=False):
        """Set the boot device for a node.

        Set the boot device to use on next reboot of the node.

        :param task: a task from TaskManager.
        :param device: the boot device, one of
                       :mod:`ironic.common.boot_devices`.
        :param persistent: Boolean value. True if the boot device will
                           persist to all future boots, False if not.
                           Default: False.
        :raises: InvalidParameterValue on malformed parameter(s)
        :raises: MissingParameterValue on missing parameter(s)
        :raises: RedfishConnectionError when it fails to connect to Redfish
        :raises: RedfishError on an error from the Sushy library
        """
        system = redfish_utils.get_system(task.node)

        desired_persistence = BOOT_DEVICE_PERSISTENT_MAP_REV[persistent]
        current_persistence = system.boot.get('enabled')

        # NOTE(etingof): this can be racy, esp if BMC is not RESTful
        enabled = (desired_persistence
                   if desired_persistence != current_persistence else None)

        try:
            system.set_system_boot_options(
                BOOT_DEVICE_MAP_REV[device], enabled=enabled)

        except sushy.exceptions.SushyError as e:
            error_msg = (_('Redfish set boot device failed for node '
                           '%(node)s. Error: %(error)s') %
                         {'node': task.node.uuid, 'error': e})
            LOG.error(error_msg)
            raise exception.RedfishError(error=error_msg)

    def get_boot_device(self, task):
        """Get the current boot device for a node.

        :param task: a task from TaskManager.
        :raises: InvalidParameterValue on malformed parameter(s)
        :raises: MissingParameterValue on missing parameter(s)
        :raises: RedfishConnectionError when it fails to connect to Redfish
        :raises: RedfishError on an error from the Sushy library
        :returns: a dictionary containing:

            :boot_device:
                the boot device, one of :mod:`ironic.common.boot_devices` or
                None if it is unknown.
            :persistent:
                Boolean value or None, True if the boot device persists,
                False otherwise. None if it's unknown.


        """
        system = redfish_utils.get_system(task.node)
        return {'boot_device': BOOT_DEVICE_MAP.get(system.boot.get('target')),
                'persistent': BOOT_DEVICE_PERSISTENT_MAP.get(
                    system.boot.get('enabled'))}

    def get_supported_boot_modes(self, task):
        """Get a list of the supported boot modes.

        :param task: A task from TaskManager.
        :returns: A list with the supported boot modes defined
                  in :mod:`ironic.common.boot_modes`. If boot
                  mode support can't be determined, empty list
                  is returned.
        """
        return list(BOOT_MODE_MAP_REV)

    @task_manager.require_exclusive_lock
    def set_boot_mode(self, task, mode):
        """Set the boot mode for a node.

        Set the boot mode to use on next reboot of the node.

        :param task: A task from TaskManager.
        :param mode: The boot mode, one of
                     :mod:`ironic.common.boot_modes`.
        :raises: InvalidParameterValue if an invalid boot mode is
                 specified.
        :raises: MissingParameterValue if a required parameter is missing
        :raises: RedfishConnectionError when it fails to connect to Redfish
        :raises: RedfishError on an error from the Sushy library
        """
        system = redfish_utils.get_system(task.node)

        boot_device = system.boot.get('target')
        if not boot_device:
            error_msg = (_('Cannot change boot mode on node %(node)s '
                           'because its boot device is not set.') %
                         {'node': task.node.uuid})
            LOG.error(error_msg)
            raise exception.RedfishError(error_msg)

        boot_override = system.boot.get('enabled')
        if not boot_override:
            error_msg = (_('Cannot change boot mode on node %(node)s '
                           'because its boot source override is not set.') %
                         {'node': task.node.uuid})
            LOG.error(error_msg)
            raise exception.RedfishError(error_msg)

        try:
            system.set_system_boot_source(
                boot_device,
                enabled=boot_override,
                mode=BOOT_MODE_MAP_REV[mode])

        except sushy.exceptions.SushyError as e:
            error_msg = (_('Setting boot mode to %(mode)s '
                           'failed for node %(node)s. '
                           'Error: %(error)s') %
                         {'node': task.node.uuid, 'mode': mode,
                          'error': e})
            LOG.error(error_msg)
            raise exception.RedfishError(error=error_msg)

    def get_boot_mode(self, task):
        """Get the current boot mode for a node.

        Provides the current boot mode of the node.

        :param task: A task from TaskManager.
        :raises: MissingParameterValue if a required parameter is missing
        :raises: DriverOperationError or its  derivative in case
                 of driver runtime error.
        :returns: The boot mode, one of :mod:`ironic.common.boot_mode` or
                  None if it is unknown.
        """
        system = redfish_utils.get_system(task.node)

        return BOOT_MODE_MAP.get(system.boot.get('mode'))

    @staticmethod
    def _sensor2dict(resource, *fields):
        return {field: getattr(resource, field)
                for field in fields
                if hasattr(resource, field)}

    @classmethod
    def _get_sensors_fan(cls, chassis):
        """Get fan sensors reading.

        :param chassis: Redfish `chassis` object
        :returns: returns a dict of sensor data.
        """
        sensors = {}

        for fan in chassis.thermal.fans:
            sensor = cls._sensor2dict(
                fan, 'identity', 'max_reading_range',
                'min_reading_range', 'reading', 'reading_units',
                'serial_number', 'physical_context')
            sensor.update(cls._sensor2dict(fan.status, 'state', 'health'))
            unique_name = '%s@%s' % (fan.identity, chassis.identity)
            sensors[unique_name] = sensor

        return sensors

    @classmethod
    def _get_sensors_temperatures(cls, chassis):
        """Get temperature sensors reading.

        :param chassis: Redfish `chassis` object
        :returns: returns a dict of sensor data.
        """
        sensors = {}

        for temps in chassis.thermal.temperatures:
            sensor = cls._sensor2dict(
                temps, 'identity', 'max_reading_range_temp',
                'min_reading_range_temp', 'reading_celsius',
                'physical_context', 'sensor_number')
            sensor.update(cls._sensor2dict(temps.status, 'state', 'health'))
            unique_name = '%s@%s' % (temps.identity, chassis.identity)
            sensors[unique_name] = sensor

        return sensors

    @classmethod
    def _get_sensors_power(cls, chassis):
        """Get power supply sensors reading.

        :param chassis: Redfish `chassis` object
        :returns: returns a dict of sensor data.
        """
        sensors = {}

        for power in chassis.power.power_supplies:
            sensor = cls._sensor2dict(
                power, 'power_capacity_watts',
                'line_input_voltage', 'last_power_output_watts',
                'serial_number')
            sensor.update(cls._sensor2dict(power.status, 'state', 'health'))
            sensor.update(cls._sensor2dict(
                power.input_ranges, 'minimum_voltage',
                'maximum_voltage', 'minimum_frequency_hz',
                'maximum_frequency_hz', 'output_wattage'))
            unique_name = '%s:%s@%s' % (
                power.identity, chassis.power.identity,
                chassis.identity)
            sensors[unique_name] = sensor

        return sensors

    @classmethod
    def _get_sensors_drive(cls, system):
        """Get storage drive sensors reading.

        :param chassis: Redfish `system` object
        :returns: returns a dict of sensor data.
        """
        sensors = {}

        for storage in system.simple_storage.get_members():
            for drive in storage.devices:
                sensor = cls._sensor2dict(
                    drive, 'name', 'model', 'capacity_bytes')
                sensor.update(
                    cls._sensor2dict(drive.status, 'state', 'health'))
                unique_name = '%s:%s@%s' % (
                    drive.name, storage.identity, system.identity)
                sensors[unique_name] = sensor

        return sensors

    def get_sensors_data(self, task):
        """Get sensors data.

        :param task: a TaskManager instance.
        :raises: FailedToGetSensorData when getting the sensor data fails.
        :raises: FailedToParseSensorData when parsing sensor data fails.
        :raises: InvalidParameterValue if required parameters
                 are missing.
        :raises: MissingParameterValue if a required parameter is missing.
        :returns: returns a dict of sensor data grouped by sensor type.
        """
        node = task.node

        sensors = collections.defaultdict(dict)

        system = redfish_utils.get_system(node)

        for chassis in system.chassis:
            try:
                sensors['Fan'].update(self._get_sensors_fan(chassis))

            except sushy.exceptions.SushyError as exc:
                LOG.debug("Failed reading fan information for node "
                          "%(node)s: %(error)s", {'node': node.uuid,
                                                  'error': exc})

            try:
                sensors['Temperature'].update(
                    self._get_sensors_temperatures(chassis))

            except sushy.exceptions.SushyError as exc:
                LOG.debug("Failed reading temperature information for node "
                          "%(node)s: %(error)s", {'node': node.uuid,
                                                  'error': exc})

            try:
                sensors['Power'].update(self._get_sensors_power(chassis))

            except sushy.exceptions.SushyError as exc:
                LOG.debug("Failed reading power information for node "
                          "%(node)s: %(error)s", {'node': node.uuid,
                                                  'error': exc})

        try:
            sensors['Drive'].update(self._get_sensors_drive(system))

        except sushy.exceptions.SushyError as exc:
            LOG.debug("Failed reading drive information for node "
                      "%(node)s: %(error)s", {'node': node.uuid,
                                              'error': exc})

        LOG.debug("Gathered sensor data: %(sensors)s", {'sensors': sensors})

        return sensors

    @task_manager.require_exclusive_lock
    def inject_nmi(self, task):
        """Inject NMI, Non Maskable Interrupt.

        Inject NMI (Non Maskable Interrupt) for a node immediately.

        :param task: A TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue on malformed parameter(s)
        :raises: MissingParameterValue on missing parameter(s)
        :raises: RedfishConnectionError when it fails to connect to Redfish
        :raises: RedfishError on an error from the Sushy library
        """
        system = redfish_utils.get_system(task.node)
        try:
            system.reset_system(sushy.RESET_NMI)
        except sushy.exceptions.SushyError as e:
            error_msg = (_('Redfish inject NMI failed for node %(node)s. '
                           'Error: %(error)s') % {'node': task.node.uuid,
                                                  'error': e})
            LOG.error(error_msg)
            raise exception.RedfishError(error=error_msg)

    def get_supported_indicators(self, task, component=None):
        """Get a map of the supported indicators (e.g. LEDs).

        :param task: A task from TaskManager.
        :param component: If not `None`, return indicator information
            for just this component, otherwise return indicators for
            all existing components.
        :returns: A dictionary of hardware components
            (:mod:`ironic.common.components`) as keys with values
            being dictionaries having indicator IDs as keys and indicator
            properties as values.

            ::

             {
                 'chassis': {
                     'enclosure-0': {
                         "readonly": true,
                         "states": [
                             "OFF",
                             "ON"
                         ]
                     }
                 },
                 'system':
                     'blade-A': {
                         "readonly": true,
                         "states": [
                             "OFF",
                             "ON"
                         ]
                     }
                 },
                 'drive':
                     'ssd0': {
                         "readonly": true,
                         "states": [
                             "OFF",
                             "ON"
                         ]
                     }
                 }
             }
        """
        properties = {
            "readonly": False,
            "states": [
                indicator_states.BLINKING,
                indicator_states.OFF,
                indicator_states.ON
            ]
        }

        indicators = {}

        system = redfish_utils.get_system(task.node)

        try:
            if component in (None, components.CHASSIS) and system.chassis:
                indicators[components.CHASSIS] = {
                    chassis.uuid: properties for chassis in system.chassis
                    if chassis.indicator_led
                }

        except sushy.exceptions.SushyError as e:
            LOG.debug('Chassis indicator not available for node %(node)s: '
                      '%(error)s', {'node': task.node.uuid, 'error': e})

        try:
            if component in (None, components.SYSTEM) and system.indicator_led:
                indicators[components.SYSTEM] = {
                    system.uuid: properties
                }

        except sushy.exceptions.SushyError as e:
            LOG.debug('System indicator not available for node %(node)s: '
                      '%(error)s', {'node': task.node.uuid, 'error': e})

        try:
            if (component in (None, components.DISK) and
                    system.simple_storage and system.simple_storage.drives):
                indicators[components.DISK] = {
                    drive.uuid: properties
                    for drive in system.simple_storage.drives
                    if drive.indicator_led
                }

        except sushy.exceptions.SushyError as e:
            LOG.debug('Drive indicator not available for node %(node)s: '
                      '%(error)s', {'node': task.node.uuid, 'error': e})

        return indicators

    def set_indicator_state(self, task, component, indicator, state):
        """Set indicator on the hardware component to the desired state.

        :param task: A task from TaskManager.
        :param component: The hardware component, one of
            :mod:`ironic.common.components`.
        :param indicator: Indicator ID (as reported by
            `get_supported_indicators`).
        :param state: Desired state of the indicator, one of
            :mod:`ironic.common.indicator_states`.
        :raises: InvalidParameterValue if an invalid component, indicator
                 or state is specified.
        :raises: MissingParameterValue if a required parameter is missing
        :raises: RedfishError on an error from the Sushy library
        """
        system = redfish_utils.get_system(task.node)

        try:
            if (component == components.SYSTEM
                    and indicator == system.uuid):
                system.set_indicator_led(INDICATOR_MAP_REV[state])
                return

            elif (component == components.CHASSIS
                    and system.chassis):
                for chassis in system.chassis:
                    if chassis.uuid == indicator:
                        chassis.set_indicator_led(
                            INDICATOR_MAP_REV[state])
                        return

            elif (component == components.DISK and
                  system.simple_storage and system.simple_storage.drives):
                for drive in system.simple_storage.drives:
                    if drive.uuid == indicator:
                        drive.set_indicator_led(
                            INDICATOR_MAP_REV[state])
                        return

        except sushy.exceptions.SushyError as e:
            error_msg = (_('Redfish set %(component)s indicator %(indicator)s '
                           'state %(state)s failed for node %(node)s. Error: '
                           '%(error)s') % {'component': component,
                                           'indicator': indicator,
                                           'state': state,
                                           'node': task.node.uuid,
                                           'error': e})
            LOG.error(error_msg)
            raise exception.RedfishError(error=error_msg)

        raise exception.MissingParameterValue(_(
            "Unknown indicator %(indicator)s for component %(component)s of "
            "node %(uuid)s") % {'indicator': indicator,
                                'component': component,
                                'uuid': task.node.uuid})

    def get_indicator_state(self, task, component, indicator):
        """Get current state of the indicator of the hardware component.

        :param task: A task from TaskManager.
        :param component: The hardware component, one of
            :mod:`ironic.common.components`.
        :param indicator: Indicator ID (as reported by
            `get_supported_indicators`).
        :raises: MissingParameterValue if a required parameter is missing
        :raises: RedfishError on an error from the Sushy library
        :returns: Current state of the indicator, one of
            :mod:`ironic.common.indicator_states`.
        """
        system = redfish_utils.get_system(task.node)

        try:
            if (component == components.SYSTEM
                    and indicator == system.uuid):
                return INDICATOR_MAP[system.indicator_led]

            if (component == components.CHASSIS
                    and system.chassis):
                for chassis in system.chassis:
                    if chassis.uuid == indicator:
                        return INDICATOR_MAP[chassis.indicator_led]

            if (component == components.DISK and
                    system.simple_storage and system.simple_storage.drives):
                for drive in system.simple_storage.drives:
                    if drive.uuid == indicator:
                        return INDICATOR_MAP[drive.indicator_led]

        except sushy.exceptions.SushyError as e:
            error_msg = (_('Redfish get %(component)s indicator %(indicator)s '
                           'state failed for node %(node)s. Error: '
                           '%(error)s') % {'component': component,
                                           'indicator': indicator,
                                           'node': task.node.uuid,
                                           'error': e})
            LOG.error(error_msg)
            raise exception.RedfishError(error=error_msg)

        raise exception.MissingParameterValue(_(
            "Unknown indicator %(indicator)s for component %(component)s of "
            "node %(uuid)s") % {'indicator': indicator,
                                'component': component,
                                'uuid': task.node.uuid})
