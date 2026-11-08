from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_ENTITY_ID
from homeassistant.helpers import selector

from .const import CONF_SOURCE_ENTITY, DOMAIN, NAME


class YandexMusicChaosConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            source = user_input[CONF_SOURCE_ENTITY]
            await self.async_set_unique_id(source)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=NAME, data={CONF_SOURCE_ENTITY: source})

        schema = vol.Schema(
            {
                vol.Required(CONF_SOURCE_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="media_player", multiple=False)
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    @staticmethod
    def async_get_options_flow(config_entry):
        return YandexMusicChaosOptionsFlow(config_entry)


class YandexMusicChaosOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self.config_entry.options or {}
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SOURCE_ENTITY,
                    default=current.get(
                        CONF_SOURCE_ENTITY,
                        self.config_entry.data.get(CONF_SOURCE_ENTITY, ""),
                    ),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="media_player", multiple=False)
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
