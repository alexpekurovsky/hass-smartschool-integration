"""SmartSchool API client with username/password authentication."""
from __future__ import annotations

import base64
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
import json
import logging
from typing import Any
import uuid

import aiohttp

from .const import API_BASE_URL

_LOGGER = logging.getLogger(__name__)


class SmartSchoolAuthError(Exception):
    """Exception raised for authentication failures."""


class SmartSchoolError(Exception):
    """Generic SmartSchool API error."""


class SmartSchoolClient:
    """Client for SmartSchool API using direct username/password login."""

    # Encryption constants discovered through JavaScript reverse engineering
    # These are hardcoded in the SmartSchool web application
    _SMART_KEY = "01234567890000000150778345678901"  # AES encryption key
    _IV = "6543210987654321"  # Initialization vector

    def __init__(
        self,
        username: str,
        password: str,
        session: aiohttp.ClientSession,
    ) -> None:
        """
        Initialize the client.

        Args:
            username: SmartSchool username
            password: SmartSchool password
            session: aiohttp ClientSession
        """
        self._username = username
        self._password = password
        self._session = session
        self._base_url = API_BASE_URL
        self._login_url = f"{self._base_url}/server/api/user/LoginByUserNameAndPassword"
        self._authenticated = False
        self._user_data: dict[str, Any] | None = None
        self._token: str | None = None
        self._unique_id = str(uuid.uuid4().hex)
        self._login_counter = 0  # Track login attempts for Data generation

    def _generate_data_parameter(self) -> str:
        """
        Generate the Data parameter using AES-CBC encryption.

        This matches the JavaScript implementation:
        encryptStringToServer(username + loginCounter)

        Returns:
            Base64 encoded encrypted string
        """
        # Create the input string: username + loginCounter
        input_string = f"{self._username}{self._login_counter}"

        # JSON stringify the input (matching JavaScript)
        json_input = json.dumps(input_string)

        # Convert key and IV to bytes
        key = self._SMART_KEY.encode('utf-8')
        iv = self._IV.encode('utf-8')

        # Create AES cipher in CBC mode
        cipher = AES.new(key, AES.MODE_CBC, iv)

        # Pad and encrypt
        padded_data = pad(json_input.encode('utf-8'), AES.block_size)
        encrypted = cipher.encrypt(padded_data)

        # Return base64 encoded result
        return base64.b64encode(encrypted).decode('utf-8')

    async def async_login(self) -> dict[str, Any]:
        """
        Authenticate with username and password.
        Returns user data including student information.
        """
        _LOGGER.info("Attempting login for user: %s", self._username)

        # Generate the Data parameter dynamically
        data_param = self._generate_data_parameter()

        # Prepare login payload matching browser structure
        payload = {
            "UserName": self._username,
            "Password": self._password,
            "Data": data_param,
            "RememberMe": True,
            "BiometricLogin": "",
            "UniqueId": self._unique_id,
            "deviceDataJson": json.dumps({
                "isMobile": False,
                "isTablet": False,
                "isDesktop": True,
                "getDeviceType": "Desktop",
                "os": "Linux",
                "osVersion": "Home Assistant",
                "browser": "HomeAssistant",
                "browserVersion": "1.0.0",
                "browserMajorVersion": 1,
                "screen_resolution": "1920 x 1080",
                "cookies": True,
                "userAgent": "HomeAssistant/SmartSchool Integration"
            })
        }

        try:
            async with self._session.post(self._login_url, json=payload) as response:
                response.raise_for_status()
                data = await response.json()

                _LOGGER.debug("Login response status: %s", data.get("status"))

                if data.get("status"):
                    self._user_data = data.get("data", {})
                    self._token = self._user_data.get("token")
                    self._authenticated = True

                    # Reset login counter on successful authentication
                    self._login_counter = 0

                    # Set the webToken cookie for subsequent requests
                    if self._token:
                        self._session.cookie_jar.update_cookies(
                            {"webToken": self._token},
                            aiohttp.client.URL(self._base_url)
                        )

                    _LOGGER.info(
                        "Login successful for user: %s (%s)",
                        self._user_data.get("fullName"),
                        self._user_data.get("schoolName")
                    )

                    return self._user_data
                else:
                    error_msg = data.get("errorDescription") or data.get("message") or "Unknown error"
                    _LOGGER.error("Login failed: %s", error_msg)

                    # Increment login counter for retry
                    self._login_counter += 1

                    raise SmartSchoolAuthError(f"Login failed: {error_msg}")

        except aiohttp.ClientResponseError as exc:
            _LOGGER.error("HTTP error during login: %s", exc)
            self._login_counter += 1
            raise SmartSchoolAuthError(f"Login failed: {exc}") from exc
        except Exception as exc:
            _LOGGER.error("Unexpected error during login: %s", exc)
            self._login_counter += 1
            raise SmartSchoolAuthError(f"Login failed: {exc}") from exc

    async def async_get_students(self) -> list[dict[str, Any]]:
        """
        Get list of students (children) for the authenticated user.
        Uses InitDashboard endpoint to get children list.
        """
        if not self._authenticated:
            await self.async_login()

        _LOGGER.debug("Fetching students list from InitDashboard")

        endpoint = f"{self._base_url}/server/api/dashboard/InitDashboard"

        try:
            response = await self._make_request("POST", endpoint, json={})

            if isinstance(response, dict) and response.get("status"):
                data = response.get("data", {})
                children = data.get("childrens", [])

                _LOGGER.debug("InitDashboard raw children data: %s", children)
                _LOGGER.info("Found %d children", len(children))

                # Convert to standard format
                students = []
                for child in children:
                    student = {
                        "id": child.get("id"),
                        "firstName": child.get("firstName"),
                        "lastName": child.get("lastName"),
                        "fullName": f"{child.get('firstName', '')} {child.get('lastName', '')}".strip(),
                        "classCode": child.get("classCode"),
                        "classNum": child.get("classNum"),
                        "cellphone": child.get("cellphone"),
                    }
                    _LOGGER.debug("Processed student: %s", student)
                    students.append(student)

                return students
            else:
                error_msg = response.get("errorDescription") or response.get("message")
                raise SmartSchoolError(f"Failed to fetch students: {error_msg}")

        except Exception as exc:
            _LOGGER.error("Failed to fetch students: %s", exc)
            raise SmartSchoolError(f"Failed to fetch students: {exc}") from exc

    async def async_get_settings_list(self, year: int) -> dict[str, Any]:
        """
        Get settings list including modules, periods, and study year info.

        Args:
            year: The study year (e.g., 2026)

        Returns:
            Dict with:
            - study_year: Current study year
            - module_id: ID of lessonSubjectHomework module
            - period_id: ID of current period
            - period_name: Name of current period
        """
        if not self._authenticated:
            await self.async_login()

        _LOGGER.debug("Fetching settings list for year: %s", year)

        endpoint = f"{self._base_url}/server/api/PupilCard/GetSettingsList"

        payload = {"id": year}

        try:
            response = await self._make_request("POST", endpoint, json=payload)

            if isinstance(response, dict) and response.get("status"):
                data = response.get("data", {})

                # Extract current study year
                study_year = data.get("currentStudyYear", year)

                # Find lessonSubjectHomework module
                module_id = None
                for module in data.get("modulesList", []):
                    if module.get("universalTitle") == "lessonSubjectHomework":
                        module_id = module.get("id")
                        break

                # Find current period (isCurrent == 1)
                period_id = None
                period_name = None
                for division in data.get("divisionsList", []):
                    if division.get("isCurrent") == 1:
                        period_id = division.get("division_id")
                        period_name = division.get("division_name")
                        break

                _LOGGER.info(
                    "Settings list - study_year: %s, module_id: %s, period_id: %s, period_name: %s",
                    study_year, module_id, period_id, period_name
                )

                return {
                    "study_year": study_year,
                    "module_id": module_id,
                    "period_id": period_id,
                    "period_name": period_name,
                }
            else:
                error_msg = response.get("errorDescription") or response.get("message")
                raise SmartSchoolError(f"Failed to fetch settings list: {error_msg}")

        except Exception as exc:
            _LOGGER.error("Failed to fetch settings list: %s", exc)
            raise SmartSchoolError(f"Failed to fetch settings list: {exc}") from exc

    async def async_get_homework(
        self,
        student_id: str,
        class_code: int,
        class_number: int,
    ) -> dict[str, Any]:
        """
        Get today's homework for a student.

        Args:
            student_id: The encrypted student ID
            class_code: Class code (e.g., 3)
            class_number: Class number (e.g., 1)
        """
        if not self._authenticated:
            await self.async_login()

        _LOGGER.debug("Fetching homework for student: %s", student_id)

        endpoint = f"{self._base_url}/server/api/dashboard/GetHomeWork"

        payload = {
            "id": student_id,
            "ClassCode": class_code,
            "ClassNumber": class_number,
        }

        try:
            response = await self._make_request("POST", endpoint, json=payload)

            if isinstance(response, dict) and response.get("status"):
                data = response.get("data", {})
                return {
                    "allowToViewThis": data.get("allowToViewThis", False),
                    "homework": data.get("dataTable", []),
                }
            else:
                error_msg = response.get("errorDescription") or response.get("message")
                raise SmartSchoolError(f"Failed to fetch homework: {error_msg}")

        except Exception as exc:
            _LOGGER.error("Failed to fetch homework: %s", exc)
            raise SmartSchoolError(f"Failed to fetch homework: {exc}") from exc

    async def async_get_grades(
        self,
        student_id: str,
        class_code: int,
    ) -> list[dict[str, Any]]:
        """
        Get grades/results for a student.

        Args:
            student_id: The encrypted student ID
            class_code: Class code (e.g., 3)
        """
        if not self._authenticated:
            await self.async_login()

        _LOGGER.debug("Fetching grades for student: %s", student_id)

        endpoint = f"{self._base_url}/server/api/dashboard/GetGrades"

        payload = {
            "id": student_id,
            "ClassCode": class_code,
        }

        try:
            response = await self._make_request("POST", endpoint, json=payload)

            if isinstance(response, dict) and response.get("status"):
                data = response.get("data", {})
                return data.get("dataTable", [])
            else:
                error_msg = response.get("errorDescription") or response.get("message")
                raise SmartSchoolError(f"Failed to fetch grades: {error_msg}")

        except Exception as exc:
            _LOGGER.error("Failed to fetch grades: %s", exc)
            raise SmartSchoolError(f"Failed to fetch grades: {exc}") from exc

    async def async_get_behavior_events(
        self,
        student_id: str,
        class_code: int,
    ) -> list[dict[str, Any]]:
        """
        Get behavior/discipline events for a student.

        Args:
            student_id: The encrypted student ID
            class_code: Class code (e.g., 3)
        """
        if not self._authenticated:
            await self.async_login()

        _LOGGER.debug("Fetching behavior events for student: %s", student_id)

        endpoint = f"{self._base_url}/server/api/dashboard/GetPupilDiciplineEvents"

        payload = {
            "id": student_id,
            "ClassCode": class_code,
        }

        try:
            response = await self._make_request("POST", endpoint, json=payload)

            if isinstance(response, dict) and response.get("status"):
                data = response.get("data", {})
                data_table = data.get("dataTable", {})
                return data_table.get("diciplineEvents", [])
            else:
                error_msg = response.get("errorDescription") or response.get("message")
                raise SmartSchoolError(f"Failed to fetch behavior events: {error_msg}")

        except Exception as exc:
            _LOGGER.error("Failed to fetch behavior events: %s", exc)
            raise SmartSchoolError(f"Failed to fetch behavior events: {exc}") from exc

    async def async_get_schedule(
        self,
        student_id: str,
        student_name: str,
        class_code: int,
        week_index: int = 0,
        study_year: int | None = None,
        period_id: int | None = None,
        period_name: str | None = None,
        module_id: int | None = None,
    ) -> dict[str, Any]:
        """
        Get weekly schedule and homework for a student.

        Args:
            student_id: The encrypted student ID
            student_name: Student's full name
            class_code: Class code (e.g., 3)
            week_index: Week offset (0=current, 1=next week, -1=last week)
            study_year: Study year (e.g., 2026)
            period_id: Period ID
            period_name: Period name (Hebrew)
            module_id: Module ID
        """
        if not self._authenticated:
            await self.async_login()

        _LOGGER.debug("Fetching schedule for student: %s, week: %s", student_id, week_index)

        endpoint = f"{self._base_url}/server/api/PupilCard/GetPupilLessonsAndHomework"

        payload = {
            "weekIndex": week_index,
            "viewType": 0,
            "studyYear": study_year,
            "studyYearName": study_year,
            "studentID": student_id,
            "studentName": student_name,
            "classCode": class_code,
            "periodID": period_id,
            "periodName": period_name,
            "moduleID": module_id,
        }

        try:
            response = await self._make_request("POST", endpoint, json=payload)

            if isinstance(response, dict) and response.get("status"):
                data = response.get("data", [])
                return {
                    "week_index": week_index,
                    "days": data,
                }
            else:
                error_msg = response.get("errorDescription") or response.get("message")
                raise SmartSchoolError(f"Failed to fetch schedule: {error_msg}")

        except Exception as exc:
            _LOGGER.error("Failed to fetch schedule: %s", exc)
            raise SmartSchoolError(f"Failed to fetch schedule: {exc}") from exc

    async def _make_request(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """Make an authenticated API request using the token cookie."""
        _LOGGER.debug("Making %s request to %s", method, url)

        # Ensure we're authenticated
        if not self._authenticated:
            await self.async_login()

        try:
            async with self._session.request(method, url, **kwargs) as response:
                # Check for auth errors
                if response.status == 401:
                    _LOGGER.warning("Authentication expired, re-logging in")
                    self._authenticated = False
                    await self.async_login()
                    # Retry the request
                    return await self._make_request(method, url, **kwargs)

                response.raise_for_status()

                # Parse JSON response
                try:
                    data = await response.json()
                    return data
                except Exception as parse_exc:
                    text = await response.text()
                    _LOGGER.error("Failed to parse response as JSON: %s", text[:200])
                    raise SmartSchoolError(f"Invalid response format: {parse_exc}") from parse_exc

        except aiohttp.ClientResponseError as exc:
            if exc.status == 401:
                raise SmartSchoolAuthError("Authentication failed") from exc
            _LOGGER.error("API request failed: %s", exc)
            raise SmartSchoolError(f"API request failed: {exc}") from exc
        except SmartSchoolAuthError:
            raise
        except Exception as exc:
            _LOGGER.error("Request failed: %s", exc)
            raise SmartSchoolError(f"Request failed: {exc}") from exc
