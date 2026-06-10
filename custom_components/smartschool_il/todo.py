"""Todo platform for SmartSchool Israel homework."""
from __future__ import annotations

import hashlib
import logging
from typing import Any

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.storage import Store

from .const import DOMAIN, get_hebrew_grade
from .coordinator import SmartSchoolCoordinator

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = "smartschool_homework_completion"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SmartSchool todo lists."""
    coordinator: SmartSchoolCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    # Create storage for completion state
    store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}_{entry.entry_id}")

    entities: list[SmartSchoolHomeworkTodoList] = []

    # Create todo list for each student
    students = coordinator.data.get("students", [])
    for student in students:
        stable_id = student["stable_id"]  # Use stable identifier for devices
        student_name = student["fullName"]

        entities.append(
            SmartSchoolHomeworkTodoList(
                coordinator=coordinator,
                student_id=stable_id,  # Pass stable_id as student_id
                student_name=student_name,
                student_info=student,
                store=store,
            )
        )

    async_add_entities(entities)


class SmartSchoolHomeworkTodoList(CoordinatorEntity[SmartSchoolCoordinator], TodoListEntity):
    """Todo list for student homework."""

    _attr_has_entity_name = True
    _attr_supported_features = (
        TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
    )

    def __init__(
        self,
        coordinator: SmartSchoolCoordinator,
        student_id: str,
        student_name: str,
        student_info: dict[str, Any],
        store: Store,
    ) -> None:
        """Initialize the todo list."""
        super().__init__(coordinator)
        self._student_id = student_id
        self._student_name = student_name
        self._student_info = student_info
        self._store = store
        self._completion_state: dict[str, bool] = {}

        # Entity attributes
        self._attr_name = "Homework"
        self._attr_unique_id = f"{DOMAIN}_{student_id}_homework_todo"

        # Device info - group with student's sensors
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

    async def async_added_to_hass(self) -> None:
        """Load completion state when entity is added."""
        await super().async_added_to_hass()
        data = await self._store.async_load()
        if data:
            self._completion_state = data.get(self._student_id, {})

    def _generate_uid(self, homework_item: dict[str, Any]) -> str:
        """Generate a unique ID for a homework item."""
        # Create UID from date + subject + homework text with null safety
        date = homework_item.get('date', '')
        subject = homework_item.get('subject', '')
        homework = homework_item.get('homework', '')
        unique_string = f"{date}_{subject}_{homework}"
        return hashlib.md5(unique_string.encode()).hexdigest()

    def _get_homework_items(self) -> list[dict[str, Any]]:
        """Get all homework items from coordinator data."""
        student_data = self.coordinator.data.get("by_student", {}).get(self._student_id, {})
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

    @property
    def todo_items(self) -> list[TodoItem]:
        """Return the current todo items."""
        homework_items = self._get_homework_items()
        todo_items = []

        for hw in homework_items:
            uid = self._generate_uid(hw)

            # Get completion state
            is_completed = self._completion_state.get(uid, False)
            status = TodoItemStatus.COMPLETED if is_completed else TodoItemStatus.NEEDS_ACTION

            # Create summary
            summary = f"{hw['subject']}: {hw['homework']}"

            # Parse due date
            try:
                due_date_str = hw['date'][:10]  # Get YYYY-MM-DD part
            except (IndexError, KeyError):
                due_date_str = None

            todo_items.append(
                TodoItem(
                    uid=uid,
                    summary=summary,
                    status=status,
                    due=due_date_str,
                )
            )

        return todo_items

    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Create a new todo item (not supported - homework comes from API)."""
        raise NotImplementedError("Cannot create homework items manually")

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Update a todo item (mark as complete/incomplete)."""
        # Update completion state
        is_completed = item.status == TodoItemStatus.COMPLETED
        self._completion_state[item.uid] = is_completed

        # Save to storage
        await self._save_completion_state()

        # Trigger update
        self.async_write_ha_state()

    async def async_delete_todo_item(self, uid: str) -> None:
        """Delete a todo item (mark as complete)."""
        # When user deletes, we treat it as marking complete
        self._completion_state[uid] = True

        # Save to storage
        await self._save_completion_state()

        # Trigger update
        self.async_write_ha_state()

    async def _save_completion_state(self) -> None:
        """Save completion state to storage."""
        data = await self._store.async_load() or {}
        data[self._student_id] = self._completion_state
        await self._store.async_save(data)

    async def async_update(self) -> None:
        """Update the entity."""
        await super().async_update()
        # Clean up completion state for homework that no longer exists
        current_homework = self._get_homework_items()
        current_uids = {self._generate_uid(hw) for hw in current_homework}

        # Remove completion state for items that no longer exist in the API
        self._completion_state = {
            uid: completed
            for uid, completed in self._completion_state.items()
            if uid in current_uids
        }
