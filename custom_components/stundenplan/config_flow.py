"""Config Flow für Stundenplan24 / Indiware."""
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
    TimeSelector,
)
from homeassistant.util import dt as dt_util

from .api import (
    ParsedPlan,
    Stundenplan24AuthError,
    Stundenplan24Client,
    Stundenplan24ConnectionError,
)
from .const import (
    CONF_ABRUFZEIT,
    CONF_FERIEN_KALENDER,
    CONF_IGNORIERTE_FAECHER,
    CONF_IGNORIERTE_KURSE,
    CONF_KLASSE,
    CONF_SCHULNUMMER,
    DEFAULT_ABRUFZEIT,
    DOMAIN,
    PROBE_DAYS,
)

_LOGGER = logging.getLogger(__name__)


class Stundenplan24ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Einrichtungsdialog: Zugangsdaten -> Klasse -> Fächer -> Ferienkalender."""

    VERSION = 1

    def __init__(self) -> None:
        self._grunddaten: dict[str, Any] = {}
        self._probe: ParsedPlan | None = None
        self._reauth_entry: ConfigEntry | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        errors: dict[str, str] = {}

        if user_input is not None:
            session = async_get_clientsession(self.hass)
            client = Stundenplan24Client(
                session,
                user_input[CONF_SCHULNUMMER].strip(),
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
                    f"{user_input[CONF_SCHULNUMMER].strip()}_{user_input[CONF_USERNAME]}"
                )
                self._abort_if_unique_id_configured()

                self._grunddaten = dict(user_input)
                self._grunddaten[CONF_SCHULNUMMER] = user_input[CONF_SCHULNUMMER].strip()
                self._probe = probe
                if probe is not None and probe.klassen:
                    return await self.async_step_klasse()
                # In den nächsten PROBE_DAYS Tagen wurde kein Plan gefunden
                # (z.B. Sommerferien) - Klasse muss manuell eingegeben werden.
                return await self.async_step_klasse_manuell()

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCHULNUMMER, default=self._grunddaten.get(CONF_SCHULNUMMER, "")
                ): str,
                vol.Required(
                    CONF_USERNAME, default=self._grunddaten.get(CONF_USERNAME, "")
                ): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Required(
                    CONF_ABRUFZEIT,
                    default=self._grunddaten.get(CONF_ABRUFZEIT, DEFAULT_ABRUFZEIT),
                ): TimeSelector(),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_klasse(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        assert self._probe is not None
        if user_input is not None:
            self._grunddaten[CONF_KLASSE] = user_input[CONF_KLASSE]
            return await self.async_step_faecher()

        optionen = sorted(self._probe.klassen.keys())
        schema = vol.Schema(
            {
                vol.Required(CONF_KLASSE): SelectSelector(
                    SelectSelectorConfig(options=optionen, mode=SelectSelectorMode.DROPDOWN)
                ),
            }
        )
        return self.async_show_form(step_id="klasse", data_schema=schema)

    async def async_step_klasse_manuell(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        if user_input is not None:
            self._grunddaten[CONF_KLASSE] = user_input[CONF_KLASSE].strip()
            self._grunddaten[CONF_IGNORIERTE_FAECHER] = []
            self._grunddaten[CONF_IGNORIERTE_KURSE] = []
            return await self.async_step_kalender()

        schema = vol.Schema({vol.Required(CONF_KLASSE): str})
        return self.async_show_form(
            step_id="klasse_manuell",
            data_schema=schema,
            description_placeholders={"tage": str(PROBE_DAYS)},
        )

    async def async_step_faecher(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        assert self._probe is not None
        if user_input is not None:
            self._grunddaten[CONF_IGNORIERTE_FAECHER] = user_input.get(
                CONF_IGNORIERTE_FAECHER, []
            )
            self._grunddaten[CONF_IGNORIERTE_KURSE] = user_input.get(
                CONF_IGNORIERTE_KURSE, []
            )
            return await self.async_step_kalender()

        klasse = self._grunddaten[CONF_KLASSE]
        klasse_daten = self._probe.klassen[klasse]
        faecher = sorted(klasse_daten.faecher)
        kurse = sorted(klasse_daten.kurse)
        schema_felder: dict = {
            vol.Optional(CONF_IGNORIERTE_FAECHER, default=[]): SelectSelector(
                SelectSelectorConfig(
                    options=faecher, multiple=True, mode=SelectSelectorMode.DROPDOWN
                )
            ),
        }
        if kurse:
            schema_felder[vol.Optional(CONF_IGNORIERTE_KURSE, default=[])] = SelectSelector(
                SelectSelectorConfig(
                    options=kurse, multiple=True, mode=SelectSelectorMode.DROPDOWN
                )
            )
        return self.async_show_form(step_id="faecher", data_schema=vol.Schema(schema_felder))

    async def async_step_kalender(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        if user_input is not None:
            self._grunddaten[CONF_FERIEN_KALENDER] = user_input.get(CONF_FERIEN_KALENDER)
            titel = f"{self._grunddaten[CONF_KLASSE]} ({self._grunddaten[CONF_SCHULNUMMER]})"
            return self.async_create_entry(title=titel, data=self._grunddaten)

        schema = vol.Schema(
            {
                vol.Optional(CONF_FERIEN_KALENDER): EntitySelector(
                    EntitySelectorConfig(domain="calendar")
                ),
            }
        )
        return self.async_show_form(step_id="kalender", data_schema=schema)

    # --- Reauth (z.B. nach Passwortänderung) ---------------------------------

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
                self._reauth_entry.data[CONF_SCHULNUMMER],
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
                neue_daten = {
                    **self._reauth_entry.data,
                    CONF_USERNAME: user_input[CONF_USERNAME],
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                }
                return self.async_update_reload_and_abort(
                    self._reauth_entry, data=neue_daten
                )

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
    def async_get_options_flow(config_entry: ConfigEntry) -> "Stundenplan24OptionsFlow":
        return Stundenplan24OptionsFlow()


class Stundenplan24OptionsFlow(OptionsFlow):
    """Nachträgliches Ändern von Klasse, Fächerfilter, Abrufzeit und Ferienkalender.

    Hinweis: `self.config_entry` wird von Home Assistant automatisch bereitgestellt
    und darf hier nicht mehr manuell gesetzt werden (seit HA 2025.12 entfernt).
    """

    def __init__(self) -> None:
        self._probe: ParsedPlan | None = None
        self._temp: dict[str, Any] = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        aktuelle = {**self.config_entry.data, **self.config_entry.options}

        if user_input is not None:
            self._temp = user_input
            return await self.async_step_faecher()

        session = async_get_clientsession(self.hass)
        client = Stundenplan24Client(
            session,
            aktuelle[CONF_SCHULNUMMER],
            aktuelle[CONF_USERNAME],
            aktuelle[CONF_PASSWORD],
        )
        try:
            self._probe = await client.async_probe(dt_util.now().date(), PROBE_DAYS)
        except (Stundenplan24AuthError, Stundenplan24ConnectionError):
            self._probe = None

        if self._probe is not None and self._probe.klassen:
            klasse_selector: Any = SelectSelector(
                SelectSelectorConfig(
                    options=sorted(self._probe.klassen.keys()),
                    mode=SelectSelectorMode.DROPDOWN,
                )
            )
        else:
            klasse_selector = str

        schema = vol.Schema(
            {
                vol.Required(CONF_KLASSE, default=aktuelle.get(CONF_KLASSE)): klasse_selector,
                vol.Required(
                    CONF_ABRUFZEIT, default=aktuelle.get(CONF_ABRUFZEIT, DEFAULT_ABRUFZEIT)
                ): TimeSelector(),
                vol.Optional(
                    CONF_FERIEN_KALENDER, default=aktuelle.get(CONF_FERIEN_KALENDER)
                ): EntitySelector(EntitySelectorConfig(domain="calendar")),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)

    async def async_step_faecher(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        aktuelle = {**self.config_entry.data, **self.config_entry.options}

        if user_input is not None:
            neue_optionen = {**self._temp, **user_input}
            return self.async_create_entry(title="", data=neue_optionen)

        klasse = self._temp[CONF_KLASSE]
        if self._probe is not None and klasse in self._probe.klassen:
            faecher = sorted(self._probe.klassen[klasse].faecher)
            kurse = sorted(self._probe.klassen[klasse].kurse)
            custom_value = False
        else:
            faecher = sorted(aktuelle.get(CONF_IGNORIERTE_FAECHER, []))
            kurse = sorted(aktuelle.get(CONF_IGNORIERTE_KURSE, []))
            custom_value = True

        bisher_ignorierte_faecher = [
            f for f in aktuelle.get(CONF_IGNORIERTE_FAECHER, []) if f in faecher
        ]
        bisher_ignorierte_kurse = [
            k for k in aktuelle.get(CONF_IGNORIERTE_KURSE, []) if k in kurse
        ]

        schema_felder: dict = {
            vol.Optional(
                CONF_IGNORIERTE_FAECHER, default=bisher_ignorierte_faecher
            ): SelectSelector(
                SelectSelectorConfig(
                    options=faecher,
                    multiple=True,
                    mode=SelectSelectorMode.DROPDOWN,
                    custom_value=custom_value,
                )
            ),
        }
        if kurse or custom_value:
            schema_felder[
                vol.Optional(CONF_IGNORIERTE_KURSE, default=bisher_ignorierte_kurse)
            ] = SelectSelector(
                SelectSelectorConfig(
                    options=kurse,
                    multiple=True,
                    mode=SelectSelectorMode.DROPDOWN,
                    custom_value=custom_value,
                )
            )
        return self.async_show_form(step_id="faecher", data_schema=vol.Schema(schema_felder))
