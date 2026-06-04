"""Sensor platform for SmartSchool Israel."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, get_hebrew_grade
from .coordinator import SmartSchoolCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class SmartSchoolSensorEntityDescription(SensorEntityDescription):
    """Describes SmartSchool sensor entity."""

    value_fn: Callable[[dict[str, Any]], Any] | None = None
    attributes_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


def _get_homework_count(student_data: dict[str, Any]) -> int:
    """Get count of homework items across all weeks."""
    count = 0
    for week in student_data.get("schedule_weeks", []):
        for day in week.get("days", []):
            for hour_data in day.get("hoursData", []):
                for lesson in hour_data.get("scheduale", []):
                    homework = lesson.get("homeWork")
                    if homework and homework.strip():
                        count += 1
    return count


def _get_homework_list(student_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Get list of all homework items."""
    homework_list = []
    for week in student_data.get("schedule_weeks", []):
        for day in week.get("days", []):
            date = day.get("date", "")
            for hour_data in day.get("hoursData", []):
                hour = hour_data.get("hour")
                for lesson in hour_data.get("scheduale", []):
                    homework = lesson.get("homeWork")
                    if homework and homework.strip():
                        homework_list.append({
                            "subject": lesson.get("subject_name", ""),
                            "homework": homework,
                            "teacher": lesson.get("teacher", ""),
                            "date": date,
                            "hour": hour,
                            "description": lesson.get("descClass", ""),
                        })
    return homework_list


def _get_latest_grade(student_data: dict[str, Any]) -> datetime | None:
    """Get the date of the most recent grade."""
    grades = student_data.get("grades", [])
    if not grades:
        return None

    # Sort grades by date descending to get the most recent first
    sorted_grades = sorted(
        grades,
        key=lambda g: g.get("date", ""),
        reverse=True
    )
    # Parse the date string to datetime object
    date_str = sorted_grades[0].get("date", "")
    if date_str:
        try:
            # Parse ISO format date and convert to Home Assistant's local timezone
            dt = datetime.fromisoformat(date_str)
            return dt_util.as_local(dt) if dt.tzinfo else dt_util.as_local(dt.replace(tzinfo=dt_util.UTC))
        except (ValueError, AttributeError):
            return None
    return None


def _get_latest_grade_attributes(student_data: dict[str, Any]) -> dict[str, Any]:
    """Get attributes for latest grade."""
    grades = student_data.get("grades", [])
    if not grades:
        return {}

    # Sort grades by date descending to get the most recent first
    sorted_grades = sorted(
        grades,
        key=lambda g: g.get("date", ""),
        reverse=True
    )
    latest = sorted_grades[0]
    return {
        "grade": latest.get("grade", ""),  # Move grade value to attribute
        "subject": latest.get("subject", ""),
        "title": latest.get("title", ""),
        "evaluation_id": latest.get("evaluationID", ""),
    }


def _get_grade_average(student_data: dict[str, Any]) -> float | None:
    """Calculate average grade."""
    grades = student_data.get("grades", [])
    if not grades:
        return None

    valid_grades = []
    for grade_item in grades:
        try:
            grade_value = float(grade_item.get("grade", 0))
            if grade_value > 0:
                valid_grades.append(grade_value)
        except (ValueError, TypeError):
            continue

    if not valid_grades:
        return None

    return round(sum(valid_grades) / len(valid_grades), 1)


def _get_behavior_count(student_data: dict[str, Any]) -> int:
    """Get count of behavior events."""
    return len(student_data.get("behavior_events", []))


def _get_behavior_attributes(student_data: dict[str, Any]) -> dict[str, Any]:
    """Get behavior events list."""
    events = student_data.get("behavior_events", [])
    return {
        "events": events[:10],  # Limit to 10 most recent to avoid bloat
        "total": len(events),
    }


def _get_next_lesson(student_data: dict[str, Any]) -> str | None:
    """Find the next upcoming lesson."""
    # Use Home Assistant's timezone-aware now
    now = dt_util.now()

    # Search through schedule weeks
    for week in student_data.get("schedule_weeks", []):
        for day in week.get("days", []):
            try:
                # Parse ISO date string with timezone
                date_str = day.get("date", "")
                if not date_str:
                    continue
                day_date = datetime.fromisoformat(date_str)
                # Convert to Home Assistant's local timezone
                if day_date.tzinfo:
                    day_date = dt_util.as_local(day_date)
                else:
                    # If naive, assume it's already in local time
                    day_date = dt_util.as_local(day_date.replace(tzinfo=dt_util.UTC))

                # Skip past days
                if day_date.date() < now.date():
                    continue

                for hour_data in day.get("hoursData", []):
                    for lesson in hour_data.get("scheduale", []):
                        # For today, check if lesson is in the future
                        if day_date.date() == now.date():
                            hour = hour_data.get("hour", 0)
                            # Rough check - if we're past hour 6 (13:00), skip
                            if hour < now.hour - 7:  # Approximate
                                continue

                        # Return first valid lesson found
                        subject = lesson.get("subject_name")
                        if subject:
                            return subject

            except (ValueError, AttributeError):
                continue

    return None


def _get_next_lesson_attributes(student_data: dict[str, Any]) -> dict[str, Any]:
    """Get attributes for next lesson."""
    # Use Home Assistant's timezone-aware now
    now = dt_util.now()

    for week in student_data.get("schedule_weeks", []):
        for day in week.get("days", []):
            try:
                # Parse ISO date string with timezone
                date_str = day.get("date", "")
                if not date_str:
                    continue
                day_date = datetime.fromisoformat(date_str)
                # Convert to Home Assistant's local timezone
                if day_date.tzinfo:
                    day_date = dt_util.as_local(day_date)
                else:
                    # If naive, assume it's already in local time
                    day_date = dt_util.as_local(day_date.replace(tzinfo=dt_util.UTC))

                if day_date.date() < now.date():
                    continue

                for hour_data in day.get("hoursData", []):
                    for lesson in hour_data.get("scheduale", []):
                        if day_date.date() == now.date():
                            hour = hour_data.get("hour", 0)
                            if hour < now.hour - 7:
                                continue

                        subject = lesson.get("subject_name")
                        if subject:
                            return {
                                "subject": subject,
                                "teacher": lesson.get("teacher", ""),
                                "date": day.get("date", ""),
                                "hour": hour_data.get("hour", ""),
                                "description": lesson.get("descClass", ""),
                                "homework": lesson.get("homeWork", ""),
                            }

            except (ValueError, AttributeError):
                continue

    return {}


SENSOR_TYPES: tuple[SmartSchoolSensorEntityDescription, ...] = (
    SmartSchoolSensorEntityDescription(
        key="homework_count",
        name="Homework Count",
        icon="mdi:book-open-page-variant",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_get_homework_count,
        attributes_fn=lambda data: {"homework": _get_homework_list(data)},
    ),
    SmartSchoolSensorEntityDescription(
        key="latest_grade",
        name="Latest Grade",
        icon="mdi:school",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_get_latest_grade,
        attributes_fn=_get_latest_grade_attributes,
    ),
    SmartSchoolSensorEntityDescription(
        key="grade_average",
        name="Grade Average",
        icon="mdi:chart-line",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_get_grade_average,
    ),
    SmartSchoolSensorEntityDescription(
        key="behavior_events",
        name="Behavior Events",
        icon="mdi:emoticon",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_get_behavior_count,
        attributes_fn=_get_behavior_attributes,
    ),
    SmartSchoolSensorEntityDescription(
        key="next_lesson",
        name="Next Lesson",
        icon="mdi:clock-outline",
        value_fn=_get_next_lesson,
        attributes_fn=_get_next_lesson_attributes,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SmartSchool sensors."""
    coordinator: SmartSchoolCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    entities: list[SmartSchoolSensor] = []

    # Create sensors for each student
    students = coordinator.data.get("students", [])
    for student in students:
        student_id = student["id"]
        student_name = student["fullName"]

        for description in SENSOR_TYPES:
            entities.append(
                SmartSchoolSensor(
                    coordinator=coordinator,
                    student_id=student_id,
                    student_name=student_name,
                    student_info=student,
                    description=description,
                )
            )

    async_add_entities(entities)


class SmartSchoolSensor(CoordinatorEntity[SmartSchoolCoordinator], SensorEntity):
    """Representation of a SmartSchool sensor."""

    entity_description: SmartSchoolSensorEntityDescription

    def __init__(
        self,
        coordinator: SmartSchoolCoordinator,
        student_id: str,
        student_name: str,
        student_info: dict[str, Any],
        description: SmartSchoolSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._student_id = student_id
        self._student_name = student_name
        self._student_info = student_info

        # Use only description name for entity_id generation
        # Full name will show in UI via device grouping
        self._attr_name = description.name
        self._attr_unique_id = f"{DOMAIN}_{student_id}_{description.key}"

        # Device info - group sensors by student
        class_code = student_info.get('classCode', '')
        class_num = student_info.get('classNum', '')
        hebrew_grade = get_hebrew_grade(class_code)

        self._attr_device_info = {
            "identifiers": {(DOMAIN, student_id)},
            "name": student_info.get('fullName', 'SmartSchool Student'),
            "manufacturer": "SmartSchool Israel",
            "model": f"Class {class_code}-{class_num} ({hebrew_grade}{class_num})",
            "suggested_area": "School",
        }

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        student_data = self.coordinator.data.get("by_student", {}).get(self._student_id, {})

        if self.entity_description.value_fn:
            return self.entity_description.value_fn(student_data)

        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        student_data = self.coordinator.data.get("by_student", {}).get(self._student_id, {})

        if self.entity_description.attributes_fn:
            return self.entity_description.attributes_fn(student_data)

        return {}
