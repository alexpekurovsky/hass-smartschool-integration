"""Calendar platform for SmartSchool Israel."""
from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, HOUR_TIMES, parse_hour_times, get_hebrew_grade
from .coordinator import SmartSchoolCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SmartSchool calendar."""
    coordinator: SmartSchoolCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    entities: list[SmartSchoolCalendar] = []

    # Create calendar for each student
    students = coordinator.data.get("students", [])
    for student in students:
        student_id = student["id"]
        student_name = student["fullName"]

        entities.append(
            SmartSchoolCalendar(
                coordinator=coordinator,
                student_id=student_id,
                student_name=student_name,
                student_info=student,
            )
        )

    async_add_entities(entities)


class SmartSchoolCalendar(CoordinatorEntity[SmartSchoolCoordinator], CalendarEntity):
    """Representation of a SmartSchool calendar."""

    def __init__(
        self,
        coordinator: SmartSchoolCoordinator,
        student_id: str,
        student_name: str,
        student_info: dict[str, Any],
    ) -> None:
        """Initialize the calendar."""
        super().__init__(coordinator)
        self._student_id = student_id
        self._student_name = student_name
        self._student_info = student_info

        # Get hour times from options or use defaults (per-student)
        options = coordinator.entry.options
        self._hour_times = parse_hour_times(options, student_id) if options else HOUR_TIMES

        # Use only "Schedule" for entity_id generation
        # Device name will be prepended by Home Assistant
        self._attr_name = "Schedule"
        self._attr_unique_id = f"{DOMAIN}_{student_id}_schedule"

        # Device info - group calendar with student's sensors
        class_code = student_info.get('classCode', '')
        class_num = student_info.get('classNum', '')
        hebrew_grade = get_hebrew_grade(class_code)

        self._attr_device_info = {
            "identifiers": {(DOMAIN, student_id)},
            "manufacturer": "SmartSchool Israel",
            "model": f"Class {class_code}-{class_num} ({hebrew_grade}{class_num})",
            "suggested_area": "School",
        }

        self._events: list[CalendarEvent] = []
        self._update_events()

    def _update_events(self) -> None:
        """Update the list of calendar events from coordinator data."""
        student_data = self.coordinator.data.get("by_student", {}).get(self._student_id, {})
        schedule_weeks = student_data.get("schedule_weeks", [])

        _LOGGER.debug(
            "Updating calendar events for student %s, found %d weeks of schedule data",
            self._student_name,
            len(schedule_weeks)
        )

        events: list[CalendarEvent] = []

        for week in schedule_weeks:
            for day in week.get("days", []):
                try:
                    # Parse the day date (keep timezone info)
                    day_date_str = day.get("date", "")
                    day_date = datetime.fromisoformat(day_date_str)

                    # Ensure timezone-aware (use Home Assistant's default timezone if needed)
                    if day_date.tzinfo is None:
                        day_date = dt_util.as_local(day_date)

                    for hour_data in day.get("hoursData", []):
                        hour = hour_data.get("hour")
                        scheduale_items = hour_data.get("scheduale", [])

                        if not scheduale_items:
                            continue

                        # Get hour times (start and end)
                        hour_times = self._hour_times.get(hour, ((8, 0), (8, 45)))
                        start_time = day_date.replace(
                            hour=hour_times[0][0],
                            minute=hour_times[0][1],
                            second=0,
                            microsecond=0
                        )
                        end_time = day_date.replace(
                            hour=hour_times[1][0],
                            minute=hour_times[1][1],
                            second=0,
                            microsecond=0
                        )

                        # Handle multiple lessons in same time slot (like splits/groups)
                        for lesson in scheduale_items:
                            subject = lesson.get("subject_name", "")
                            if not subject:
                                continue

                            teacher = lesson.get("teacher", "")
                            desc_class = lesson.get("descClass", "")
                            homework = lesson.get("homeWork", "")

                            # Build event title - add homework icon if homework exists
                            title = f"{subject}"
                            if teacher:
                                title += f" - {teacher}"

                            # Add homework icon to title if homework is assigned
                            if homework and homework.strip():
                                title = f"📝 {title}"

                            description_parts = []
                            if teacher:
                                description_parts.append(f"Teacher: {teacher}")
                            if desc_class:
                                description_parts.append(f"Taught: {desc_class}")
                            if homework:
                                description_parts.append(f"Homework: {homework}")

                            description = "\n".join(description_parts) if description_parts else None

                            # Create calendar event
                            event = CalendarEvent(
                                start=start_time,
                                end=end_time,
                                summary=title,
                                description=description,
                            )
                            events.append(event)

                except (ValueError, AttributeError, KeyError) as err:
                    _LOGGER.warning("Failed to parse lesson data: %s", err)
                    continue

        self._events = events

    @property
    def event(self) -> CalendarEvent | None:
        """Return the next upcoming event."""
        # Ensure events are up to date
        if not self._events:
            self._update_events()

        now = dt_util.now()

        upcoming_events = [
            event for event in self._events
            if event.start >= now
        ]

        if not upcoming_events:
            return None

        # Sort by start time and return the earliest
        upcoming_events.sort(key=lambda e: e.start)
        return upcoming_events[0]

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return calendar events within a datetime range."""
        self._update_events()

        _LOGGER.debug(
            "Calendar async_get_events called for %s - %s, found %d total events",
            start_date,
            end_date,
            len(self._events)
        )

        filtered = [
            event
            for event in self._events
            if event.start < end_date and event.end > start_date
        ]

        _LOGGER.debug("Returning %d filtered events", len(filtered))

        return filtered

    async def async_update(self) -> None:
        """Update the entity."""
        await super().async_update()
        self._update_events()
