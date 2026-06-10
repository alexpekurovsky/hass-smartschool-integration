"""DataUpdateCoordinator for SmartSchool Israel."""
from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api_client import SmartSchoolAuthError, SmartSchoolClient, SmartSchoolError
from .const import CALENDAR_WEEKS_AHEAD, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

# Refresh settings cache every 24 hours
SETTINGS_CACHE_REFRESH_HOURS = 24


class SmartSchoolCoordinator(DataUpdateCoordinator):
    """Coordinator to fetch SmartSchool data."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: SmartSchoolClient,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {entry.title}",
            update_interval=timedelta(minutes=DEFAULT_SCAN_INTERVAL),
        )
        self.client = client
        self.entry = entry
        self._settings_cache: dict[str, Any] | None = None
        self._settings_cache_time: datetime | None = None

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from SmartSchool API."""
        try:
            # Ensure authenticated
            await self.client.async_login()

            # Get settings list (refresh every 24 hours to catch year/period changes)
            now = datetime.now()
            if (
                self._settings_cache is None
                or self._settings_cache_time is None
                or (now - self._settings_cache_time).total_seconds() > SETTINGS_CACHE_REFRESH_HOURS * 3600
            ):
                # Calculate study year: if we're in September or later, it's next calendar year's study year
                # e.g., September 2025 = study year 2026 (2025/2026 school year)
                current_year = now.year
                if now.month >= 9:  # September or later
                    study_year = current_year + 1
                else:  # January to August
                    study_year = current_year

                self._settings_cache = await self.client.async_get_settings_list(study_year)
                self._settings_cache_time = now
                _LOGGER.info("Refreshed settings cache for study year %s (calendar year %s, month %s)",
                            study_year, current_year, now.month)

            # Get list of students
            students = await self.client.async_get_students()

            if not students:
                raise UpdateFailed("No students found for this account")

            _LOGGER.info("Fetching data for %d students", len(students))

            # Prepare data structure
            data: dict[str, Any] = {
                "students": students,
                "by_student": {},
            }

            # Fetch data for each student
            for student in students:
                student_id = student["id"]  # API ID (changes per session)
                stable_id = student["stable_id"]  # Stable identifier
                student_name = student["fullName"]
                class_code = student["classCode"]
                class_num = student.get("classNum")

                _LOGGER.debug("Fetching data for student: %s (stable_id: %s, api_id: %s)",
                              student_name, stable_id, student_id)

                student_data: dict[str, Any] = {
                    "info": student,
                    "grades": [],
                    "behavior_events": [],
                    "schedule_weeks": [],
                }

                # Fetch grades
                try:
                    student_data["grades"] = await self.client.async_get_grades(
                        student_id=student_id,
                        class_code=class_code,
                    )
                except SmartSchoolError as err:
                    _LOGGER.warning("Failed to fetch grades for %s: %s", student_name, err)

                # Fetch behavior events
                try:
                    student_data["behavior_events"] = await self.client.async_get_behavior_events(
                        student_id=student_id,
                        class_code=class_code,
                    )
                except SmartSchoolError as err:
                    _LOGGER.warning("Failed to fetch behavior events for %s: %s", student_name, err)

                # Fetch schedule for multiple weeks (for calendar)
                # Get dynamic settings from cache - these must be present
                study_year = self._settings_cache.get("study_year")
                period_id = self._settings_cache.get("period_id")
                period_name = self._settings_cache.get("period_name")
                module_id = self._settings_cache.get("module_id")

                # Skip schedule fetching if any required setting is missing
                if not all([study_year, period_id, period_name, module_id]):
                    _LOGGER.warning(
                        "Skipping schedule fetch for %s: Missing required settings "
                        "(study_year: %s, period_id: %s, period_name: %s, module_id: %s)",
                        student_name, study_year, period_id, period_name, module_id
                    )
                else:
                    for week_index in range(CALENDAR_WEEKS_AHEAD):
                        try:
                            schedule_data = await self.client.async_get_schedule(
                                student_id=student_id,
                                student_name=student_name,
                                class_code=class_code,
                                week_index=week_index,
                                study_year=study_year,
                                period_id=period_id,
                                period_name=period_name,
                                module_id=module_id,
                            )
                            student_data["schedule_weeks"].append(schedule_data)
                        except SmartSchoolError as err:
                            _LOGGER.warning(
                                "Failed to fetch schedule week %d for %s: %s",
                                week_index,
                                student_name,
                                err,
                            )

                # Store by stable_id (not API id which changes)
                data["by_student"][stable_id] = student_data

            _LOGGER.info("Successfully fetched data for all students")
            return data

        except SmartSchoolAuthError as exc:
            raise UpdateFailed(f"Authentication failed: {exc}") from exc
        except SmartSchoolError as exc:
            raise UpdateFailed(f"Error fetching data: {exc}") from exc
        except Exception as exc:
            _LOGGER.exception("Unexpected error fetching data")
            raise UpdateFailed(f"Unexpected error: {exc}") from exc
