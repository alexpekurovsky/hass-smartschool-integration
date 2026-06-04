"""Constants for the SmartSchool Israel integration."""
from typing import Final

DOMAIN: Final = "smartschool_il"

# Configuration keys
CONF_USERNAME: Final = "username"
CONF_PASSWORD: Final = "password"

# Default values
DEFAULT_SCAN_INTERVAL: Final = 30  # minutes

# Data keys for coordinator
DATA_STUDENTS: Final = "students"
DATA_HOMEWORK: Final = "homework"
DATA_GRADES: Final = "grades"
DATA_SCHEDULE: Final = "schedule"
DATA_MESSAGES: Final = "messages"

# Sensor keys
SENSOR_KEY_HOMEWORK: Final = "homework"
SENSOR_KEY_GRADES: Final = "grades"
SENSOR_KEY_SCHEDULE: Final = "schedule"
SENSOR_KEY_MESSAGES: Final = "messages"

# API endpoints
API_BASE_URL: Final = "https://webtopserver.smartschool.co.il"

# Hour to time mapping (start and end times per lesson)
# Format: hour_number: ((start_hour, start_minute), (end_hour, end_minute))
HOUR_TIMES: Final = {
    1: ((8, 0), (8, 50)),    # 8:00-8:50
    2: ((8, 50), (9, 35)),   # 8:50-9:35
    3: ((10, 5), (10, 55)),  # 10:05-10:55
    4: ((10, 55), (11, 45)), # 10:55-11:45
    5: ((11, 55), (12, 40)), # 11:55-12:40
    6: ((12, 40), (13, 30)), # 12:40-13:30
    7: ((14, 0), (14, 45)),  # 14:00-14:45 (placeholder)
    8: ((15, 0), (15, 45)),  # 15:00-15:45 (placeholder)
    9: ((16, 0), (16, 45)),  # 16:00-16:45 (placeholder)
    10: ((17, 0), (17, 45)), # 17:00-17:45 (placeholder)
}

# Number of weeks to fetch for calendar
CALENDAR_WEEKS_AHEAD: Final = 4


def get_hebrew_grade(class_code: str) -> str:
    """Convert numeric grade (class code) to Hebrew letter.

    Args:
        class_code: Numeric grade as string (1-12)

    Returns:
        Hebrew letter representation (א-יב)
    """
    grade_map = {
        "1": "א", "2": "ב", "3": "ג", "4": "ד", "5": "ה", "6": "ו",
        "7": "ז", "8": "ח", "9": "ט", "10": "י", "11": "יא", "12": "יב",
    }
    return grade_map.get(class_code, class_code)


def parse_hour_times(options: dict, student_id: str | None = None) -> dict[int, tuple[tuple[int, int], tuple[int, int]]]:
    """Parse hour times from options or use defaults.

    Args:
        options: Config entry options dict
        student_id: Optional student ID to get per-student configuration

    Returns:
        Dict mapping hour number to ((start_h, start_m), (end_h, end_m))
    """
    from .config_flow import (
        CONF_HOUR_1, CONF_HOUR_2, CONF_HOUR_3,
        CONF_HOUR_4, CONF_HOUR_5, CONF_HOUR_6,
        CONF_HOUR_7, CONF_HOUR_8, CONF_HOUR_9,
        DEFAULT_HOUR_TIMES,
    )

    # Get student-specific options if student_id provided
    if student_id and isinstance(options.get(student_id), dict):
        student_options = options[student_id]
    else:
        # Fall back to global options (for backward compatibility)
        student_options = options

    def parse_time_range(time_str: str) -> tuple[tuple[int, int], tuple[int, int]]:
        """Parse time range string like '8:00-8:50' into tuples."""
        try:
            start_str, end_str = time_str.split("-")
            start_h, start_m = map(int, start_str.split(":"))
            end_h, end_m = map(int, end_str.split(":"))
            return ((start_h, start_m), (end_h, end_m))
        except (ValueError, AttributeError):
            # Return default if parsing fails
            return ((8, 0), (8, 45))

    hour_configs = {
        1: CONF_HOUR_1,
        2: CONF_HOUR_2,
        3: CONF_HOUR_3,
        4: CONF_HOUR_4,
        5: CONF_HOUR_5,
        6: CONF_HOUR_6,
        7: CONF_HOUR_7,
        8: CONF_HOUR_8,
        9: CONF_HOUR_9,
    }

    result = {}
    for hour_num, conf_key in hour_configs.items():
        time_str = student_options.get(conf_key, DEFAULT_HOUR_TIMES[conf_key])
        result[hour_num] = parse_time_range(time_str)

    # Add placeholder times for hours 10+ if needed
    for hour_num in range(10, 11):
        default_times = HOUR_TIMES.get(hour_num, ((17, 0), (17, 45)))
        result[hour_num] = default_times

    return result

