"""Config flow for SmartSchool Israel integration."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api_client import SmartSchoolAuthError, SmartSchoolClient, SmartSchoolError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Configuration option keys
CONF_HOUR_1 = "hour_1_times"
CONF_HOUR_2 = "hour_2_times"
CONF_HOUR_3 = "hour_3_times"
CONF_HOUR_4 = "hour_4_times"
CONF_HOUR_5 = "hour_5_times"
CONF_HOUR_6 = "hour_6_times"
CONF_HOUR_7 = "hour_7_times"
CONF_HOUR_8 = "hour_8_times"
CONF_HOUR_9 = "hour_9_times"

# Default lesson times
DEFAULT_HOUR_TIMES = {
    CONF_HOUR_1: "8:00-8:50",
    CONF_HOUR_2: "8:50-9:35",
    CONF_HOUR_3: "10:05-10:55",
    CONF_HOUR_4: "10:55-11:45",
    CONF_HOUR_5: "11:55-12:40",
    CONF_HOUR_6: "12:40-13:30",
    CONF_HOUR_7: "14:00-14:45",
    CONF_HOUR_8: "15:00-15:45",
    CONF_HOUR_9: "16:00-16:45",
}

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
    session = async_get_clientsession(hass)
    client = SmartSchoolClient(
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        session=session,
    )

    # Test the credentials by attempting to login and get students
    user_data = await client.async_login()
    students = await client.async_get_students()

    if not students:
        raise SmartSchoolError("No students found for this account")

    # Return info that you want to store in the config entry.
    return {
        "title": user_data.get("fullName", data[CONF_USERNAME]),
        "students_count": len(students),
    }


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SmartSchool Israel."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except SmartSchoolAuthError:
                errors["base"] = "invalid_auth"
            except SmartSchoolError as err:
                _LOGGER.error("Error connecting to SmartSchool: %s", err)
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                # Set unique ID to prevent duplicate entries
                await self.async_set_unique_id(user_input[CONF_USERNAME].lower())
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=info["title"],
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OptionsFlowHandler:
        """Get the options flow for this handler."""
        return OptionsFlowHandler()


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for SmartSchool Israel."""

    def __init__(self) -> None:
        """Initialize options flow."""
        self._selected_student_id: str | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options - select which student to configure."""
        # Get students from coordinator
        coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id]["coordinator"]
        students = coordinator.data.get("students", [])

        if not students:
            return self.async_abort(reason="no_students")

        if user_input is not None:
            # Store selected student and move to lesson times configuration
            self._selected_student_id = user_input["student"]
            return await self.async_step_lesson_times()

        # Create student selection schema - use device registry names
        device_reg = dr.async_get(self.hass)
        student_options = {}

        for student in students:
            student_id = student["id"]
            # Try to get customized device name from registry
            device = device_reg.async_get_device(identifiers={(DOMAIN, student_id)})
            if device:
                # Use name_by_user if set, otherwise use device name
                display_name = device.name_by_user or device.name
            else:
                # Fallback to API name if device not found
                display_name = student["fullName"]

            student_options[student_id] = display_name

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required("student"): vol.In(student_options),
            }),
        )

    async def async_step_lesson_times(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure lesson times for selected student."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate time formats
            time_fields = [CONF_HOUR_1, CONF_HOUR_2, CONF_HOUR_3, CONF_HOUR_4, CONF_HOUR_5,
                          CONF_HOUR_6, CONF_HOUR_7, CONF_HOUR_8, CONF_HOUR_9]
            for field in time_fields:
                if field in user_input:
                    if not self._validate_time_format(user_input[field]):
                        errors[field] = "invalid_time_format"

            if not errors:
                # Get existing options
                options = dict(self.config_entry.options)

                # Store lesson times for this student
                if self._selected_student_id:
                    options[self._selected_student_id] = user_input

                return self.async_create_entry(title="", data=options)

        # Get current values for this student or use defaults
        options = self.config_entry.options
        student_options = options.get(self._selected_student_id, {}) if self._selected_student_id else {}

        # Get student name for title
        coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id]["coordinator"]
        students = coordinator.data.get("students", [])
        student_name = next(
            (s["fullName"] for s in students if s["id"] == self._selected_student_id),
            "Student"
        )

        return self.async_show_form(
            step_id="lesson_times",
            description_placeholders={"student_name": student_name},
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_HOUR_1,
                        default=student_options.get(CONF_HOUR_1, DEFAULT_HOUR_TIMES[CONF_HOUR_1]),
                    ): str,
                    vol.Optional(
                        CONF_HOUR_2,
                        default=student_options.get(CONF_HOUR_2, DEFAULT_HOUR_TIMES[CONF_HOUR_2]),
                    ): str,
                    vol.Optional(
                        CONF_HOUR_3,
                        default=student_options.get(CONF_HOUR_3, DEFAULT_HOUR_TIMES[CONF_HOUR_3]),
                    ): str,
                    vol.Optional(
                        CONF_HOUR_4,
                        default=student_options.get(CONF_HOUR_4, DEFAULT_HOUR_TIMES[CONF_HOUR_4]),
                    ): str,
                    vol.Optional(
                        CONF_HOUR_5,
                        default=student_options.get(CONF_HOUR_5, DEFAULT_HOUR_TIMES[CONF_HOUR_5]),
                    ): str,
                    vol.Optional(
                        CONF_HOUR_6,
                        default=student_options.get(CONF_HOUR_6, DEFAULT_HOUR_TIMES[CONF_HOUR_6]),
                    ): str,
                    vol.Optional(
                        CONF_HOUR_7,
                        default=student_options.get(CONF_HOUR_7, DEFAULT_HOUR_TIMES[CONF_HOUR_7]),
                    ): str,
                    vol.Optional(
                        CONF_HOUR_8,
                        default=student_options.get(CONF_HOUR_8, DEFAULT_HOUR_TIMES[CONF_HOUR_8]),
                    ): str,
                    vol.Optional(
                        CONF_HOUR_9,
                        default=student_options.get(CONF_HOUR_9, DEFAULT_HOUR_TIMES[CONF_HOUR_9]),
                    ): str,
                }
            ),
            errors=errors,
        )

    @staticmethod
    def _validate_time_format(time_str: str) -> bool:
        """Validate time format (e.g., '8:00-8:50')."""
        try:
            start_str, end_str = time_str.split("-")
            start_h, start_m = map(int, start_str.split(":"))
            end_h, end_m = map(int, end_str.split(":"))

            # Validate ranges
            if not (0 <= start_h < 24 and 0 <= start_m < 60):
                return False
            if not (0 <= end_h < 24 and 0 <= end_m < 60):
                return False

            # Ensure end time is after start time
            start_minutes = start_h * 60 + start_m
            end_minutes = end_h * 60 + end_m
            if end_minutes <= start_minutes:
                return False

            return True
        except (ValueError, AttributeError):
            return False

