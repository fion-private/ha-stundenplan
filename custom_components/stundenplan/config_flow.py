"""Config flow for the Stundenplan integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
from homeassistant.util import dt as dt_util

from .api import (
    ParsedPlan,
    Stundenplan24AuthError,
    Stundenplan24Client,
    Stundenplan24ConnectionError,
)
from .const import (
    CONF_CLASS_NAME,
    CONF_HOLIDAY_CALENDAR,
    CONF_IGNORED_COURSES,
    CONF_IGNORED_SUBJECTS,
    CONF_SCHOOL_NUMBER,
    DOMAIN,
    PROBE_DAYS,
)

_LOGGER = logging.getLogger(__name__)


class Stundenplan24ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Setup wizard: credentials -> class -> subjects/courses -> holiday calendar."""

    VERSION = 2

    def __init__(self) -> None:
        self._base_data: dict[str, Any] = {}
        self._probe: ParsedPlan | None = None
        self._reauth_entry: ConfigEntry | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> Any:
        errors: dict[str, str] = {}

        if user_input is not None:
            session = async_get_clientsession(self.hass)
            client = Stundenplan24Client(
                session,
                user_input[CONF_SCHOOL_NUMBER].strip(),
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
            )
            try:
                probe = await client.async_probe(dt_util.now().date(), PROBE_DAYS)
            except Stundenplan24AuthError:
                errors["base"] = "invalid_auth"
            except Stundenplan24ConnectionError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(
                    f"{user_input[CONF_SCHOOL_NUMBER].strip()}_{user_input[CONF_USERNAME]}"
                )
                self._abort_if_unique_id_configured()

                self._base_data = dict(user_input)
                self._base_data[CONF_SCHOOL_NUMBER] = user_input[CONF_SCHOOL_NUMBER].strip()
                self._probe = probe
                if probe is not None and probe.classes:
                    return await self.async_step_class()
                # No plan found within PROBE_DAYS days (e.g. summer holidays) -
                # the class has to be entered manually.
                return await self.async_step_class_manual()

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCHOOL_NUMBER, default=self._base_data.get(CONF_SCHOOL_NUMBER, "")
                ): str,
                vol.Required(
                    CONF_USERNAME, default=self._base_data.get(CONF_USERNAME, "")
                ): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_class(self, user_input: dict[str, Any] | None = None) -> Any:
        assert self._probe is not None
        if user_input is not None:
            self._base_data[CONF_CLASS_NAME] = user_input[CONF_CLASS_NAME]
            return await self.async_step_subjects()

        options = sorted(self._probe.classes.keys())
        schema = vol.Schema(
            {
                vol.Required(CONF_CLASS_NAME): SelectSelector(
                    SelectSelectorConfig(options=options, mode=SelectSelectorMode.DROPDOWN)
                ),
            }
        )
        return self.async_show_form(step_id="class", data_schema=schema)

    async def async_step_class_manual(self, user_input: dict[str, Any] | None = None) -> Any:
        if user_input is not None:
            self._base_data[CONF_CLASS_NAME] = user_input[CONF_CLASS_NAME].strip()
            self._base_data[CONF_IGNORED_SUBJECTS] = []
            self._base_data[CONF_IGNORED_COURSES] = []
            return await self.async_step_calendar()

        schema = vol.Schema({vol.Required(CONF_CLASS_NAME): str})
        return self.async_show_form(
            step_id="class_manual",
            data_schema=schema,
            description_placeholders={"days": str(PROBE_DAYS)},
        )

    async def async_step_subjects(self, user_input: dict[str, Any] | None = None) -> Any:
        assert self._probe is not None
        if user_input is not None:
            self._base_data[CONF_IGNORED_SUBJECTS] = user_input.get(CONF_IGNORED_SUBJECTS, [])
            self._base_data[CONF_IGNORED_COURSES] = user_input.get(CONF_IGNORED_COURSES, [])
            return await self.async_step_calendar()

        class_name = self._base_data[CONF_CLASS_NAME]
        class_data = self._probe.classes[class_name]
        subjects = sorted(class_data.subjects)
        courses = sorted(class_data.courses)
        schema_fields: dict = {
            vol.Optional(CONF_IGNORED_SUBJECTS, default=[]): SelectSelector(
                SelectSelectorConfig(
                    options=subjects, multiple=True, mode=SelectSelectorMode.DROPDOWN
                )
            ),
        }
        if courses:
            schema_fields[vol.Optional(CONF_IGNORED_COURSES, default=[])] = SelectSelector(
                SelectSelectorConfig(
                    options=courses, multiple=True, mode=SelectSelectorMode.DROPDOWN
                )
            )
        return self.async_show_form(step_id="subjects", data_schema=vol.Schema(schema_fields))

    async def async_step_calendar(self, user_input: dict[str, Any] | None = None) -> Any:
        if user_input is not None:
            self._base_data[CONF_HOLIDAY_CALENDAR] = user_input.get(CONF_HOLIDAY_CALENDAR)
            title = f"{self._base_data[CONF_CLASS_NAME]} ({self._base_data[CONF_SCHOOL_NUMBER]})"
            return self.async_create_entry(title=title, data=self._base_data)

        schema = vol.Schema(
            {
                vol.Optional(CONF_HOLIDAY_CALENDAR): EntitySelector(
                    EntitySelectorConfig(domain="calendar")
                ),
            }
        )
        return self.async_show_form(step_id="calendar", data_schema=schema)

    # --- Reauth (e.g. after a password change) --------------------------

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> Any:
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        errors: dict[str, str] = {}
        assert self._reauth_entry is not None

        if user_input is not None:
            session = async_get_clientsession(self.hass)
            client = Stundenplan24Client(
                session,
                self._reauth_entry.data[CONF_SCHOOL_NUMBER],
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
            )
            try:
                await client.async_verify_credentials()
            except Stundenplan24AuthError:
                errors["base"] = "invalid_auth"
            except Stundenplan24ConnectionError:
                errors["base"] = "cannot_connect"
            else:
                new_data = {
                    **self._reauth_entry.data,
                    CONF_USERNAME: user_input[CONF_USERNAME],
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                }
                return self.async_update_reload_and_abort(self._reauth_entry, data=new_data)

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_USERNAME, default=self._reauth_entry.data.get(CONF_USERNAME, "")
                ): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )
        return self.async_show_form(
            step_id="reauth_confirm", data_schema=schema, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> Stundenplan24OptionsFlow:
        return Stundenplan24OptionsFlow()


class Stundenplan24OptionsFlow(OptionsFlow):
    """Change class, subject/course filter, fetch time and holiday calendar later.

    Note: `self.config_entry` is provided automatically by Home Assistant
    and must not be set manually here (removed as of HA 2025.12).
    """

    def __init__(self) -> None:
        self._probe: ParsedPlan | None = None
        self._pending: dict[str, Any] = {}

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> Any:
        current = {**self.config_entry.data, **self.config_entry.options}

        if user_input is not None:
            self._pending = user_input
            return await self.async_step_subjects()

        session = async_get_clientsession(self.hass)
        client = Stundenplan24Client(
            session,
            current[CONF_SCHOOL_NUMBER],
            current[CONF_USERNAME],
            current[CONF_PASSWORD],
        )
        try:
            self._probe = await client.async_probe(dt_util.now().date(), PROBE_DAYS)
        except (Stundenplan24AuthError, Stundenplan24ConnectionError):
            self._probe = None

        if self._probe is not None and self._probe.classes:
            class_selector: Any = SelectSelector(
                SelectSelectorConfig(
                    options=sorted(self._probe.classes.keys()),
                    mode=SelectSelectorMode.DROPDOWN,
                )
            )
        else:
            class_selector = str

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_CLASS_NAME, default=current.get(CONF_CLASS_NAME)
                ): class_selector,
                vol.Optional(
                    CONF_HOLIDAY_CALENDAR, default=current.get(CONF_HOLIDAY_CALENDAR)
                ): EntitySelector(EntitySelectorConfig(domain="calendar")),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)

    async def async_step_subjects(self, user_input: dict[str, Any] | None = None) -> Any:
        current = {**self.config_entry.data, **self.config_entry.options}

        if user_input is not None:
            new_options = {**self._pending, **user_input}
            return self.async_create_entry(title="", data=new_options)

        class_name = self._pending[CONF_CLASS_NAME]
        if self._probe is not None and class_name in self._probe.classes:
            subjects = sorted(self._probe.classes[class_name].subjects)
            courses = sorted(self._probe.classes[class_name].courses)
            custom_value = False
        else:
            subjects = sorted(current.get(CONF_IGNORED_SUBJECTS, []))
            courses = sorted(current.get(CONF_IGNORED_COURSES, []))
            custom_value = True

        selected_subjects = [
            subject for subject in current.get(CONF_IGNORED_SUBJECTS, []) if subject in subjects
        ]
        selected_courses = [
            course for course in current.get(CONF_IGNORED_COURSES, []) if course in courses
        ]

        schema_fields: dict = {
            vol.Optional(
                CONF_IGNORED_SUBJECTS, default=selected_subjects
            ): SelectSelector(
                SelectSelectorConfig(
                    options=subjects,
                    multiple=True,
                    mode=SelectSelectorMode.DROPDOWN,
                    custom_value=custom_value,
                )
            ),
        }
        if courses or custom_value:
            schema_fields[
                vol.Optional(CONF_IGNORED_COURSES, default=selected_courses)
            ] = SelectSelector(
                SelectSelectorConfig(
                    options=courses,
                    multiple=True,
                    mode=SelectSelectorMode.DROPDOWN,
                    custom_value=custom_value,
                )
            )
        return self.async_show_form(step_id="subjects", data_schema=vol.Schema(schema_fields))
