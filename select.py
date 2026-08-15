"""Favourite selection for the Anthem valve.

One dropdown that both **starts** a stored scene and **shows which one is running**, because
the valve reports the active scene itself (``presetOrExperienceId``) rather than leaving Home
Assistant to remember what it last sent. A scene started from the Konnect app or the
touchscreen therefore shows up here too.

**"Favourite" is the user-facing word; "preset" is the protocol word.** The Konnect app calls
these favourites, so that is what the entity is called. Everything below the entity layer
keeps Kohler's own vocabulary, because that is what the wire format and the documentation
use. Note the Anthem Plus *controller* has its own, unrelated favourites — those belong to
the "Anthem Plus" device, not this one.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, PRESET_HIDDEN_IDS
from .coordinator import KohlerAnthemPlusCoordinator
from .entity import KohlerControllerEntity, KohlerValveEntity

# Shown when no favourite is driving the valve. A `select` must always have its current
# option present in the option list or Home Assistant logs an error on every update, and
# "nothing is running" is a real state that needs a name.
OPTION_OFF = "Off"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the favourite selector when the account has a valve."""
    coordinator: KohlerAnthemPlusCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SelectEntity] = []
    if coordinator.gcs_device is not None:
        entities.append(FavouriteSelect(coordinator))
    if coordinator.hub_device is not None:
        # The controller keeps its own favourites on a different command surface. Both can
        # exist on one account, on their own devices, which is why they are separate
        # entities rather than one merged list.
        entities.append(HubFavouriteSelect(coordinator))
    async_add_entities(entities)


class FavouriteSelect(KohlerValveEntity, SelectEntity):
    """Start a stored favourite, and show which one is running."""

    _attr_icon = "mdi:playlist-play"
    _attr_name = "Favourite"

    def __init__(self, coordinator: KohlerAnthemPlusCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._device_id}_favourite"
        # Holds the requested option until the valve reports back, matching the outlet
        # switches. Activation takes 1-2 s on real hardware.
        self._optimistic: str | None = None

    @property
    def _presets(self):
        state = self._state
        if state is None:
            return []
        return state.selectable_presets(hidden=PRESET_HIDDEN_IDS)

    @property
    def options(self) -> list[str]:
        """``Off`` plus every selectable favourite, lowest slot first.

        Rebuilt from current state on every read, so a favourite added, renamed, or deleted
        in the Konnect app appears here without a reload — the valve pushes those changes
        over MQTT.
        """
        return [OPTION_OFF] + [preset.name for preset in self._presets]

    @property
    def current_option(self) -> str | None:
        """The running favourite, or ``Off``.

        ``presetOrExperienceId`` is cleared by **both** pause and stop, so a paused session
        reads as ``Off`` here while the outlet switches still show their assignment. It is
        also never set by a direct outlet command, so opening an outlet by hand leaves this
        at ``Off`` with water running — this reports *what started the session*, not whether
        water is on.
        """
        if self._optimistic is not None:
            return self._optimistic
        state = self._state
        if state is None:
            return None
        active = state.active_preset_id
        if active is None:
            return OPTION_OFF
        preset = state.presets.get(active)
        # An id we cannot name — a hidden favourite (preset 1, driven by the shower switch),
        # an experience, or one that arrived before the list did. Reporting an option that
        # is not in `options` makes Home Assistant log an error on every update, so fall
        # back rather than inventing an entry.
        if preset is None or not preset.is_selectable:
            return OPTION_OFF
        if preset.preset_id in PRESET_HIDDEN_IDS:
            return OPTION_OFF
        return preset.name

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        state = self._state
        if state is None:
            return {}
        return {
            # The raw id behind the current option, including the ids this entity hides —
            # useful when the dropdown reads Off but something is clearly running.
            "active_preset_id": state.active_preset_id,
            "favourite_count": len(self._presets),
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Real state has arrived, so the optimistic guess is no longer needed."""
        self._optimistic = None
        super()._handle_coordinator_update()

    async def async_select_option(self, option: str) -> None:
        """Start the named favourite, or stop the shower.

        Resolved **by name at call time**, never by a remembered id: preset ids are slots
        that get reused, so a stale id stays valid while pointing at a different scene.
        """
        if option == OPTION_OFF:
            await self._async_command(OPTION_OFF, self.coordinator.async_stop_shower())
            return

        state = self._state
        preset = (
            None if state is None else state.preset_by_name(option, PRESET_HIDDEN_IDS)
        )
        if preset is None:
            raise HomeAssistantError(
                f"No Anthem favourite called {option!r}. It may have been renamed or "
                "deleted in the Konnect app."
            )
        await self._async_command(
            option, self.coordinator.async_activate_preset(preset.preset_id)
        )

    async def _async_command(self, option: str, action) -> None:
        self._optimistic = option
        self.async_write_ha_state()
        try:
            await action
        except Exception:
            # The command failed, so stop showing a state the valve never reached.
            self._optimistic = None
            self.async_write_ha_state()
            raise


class HubFavouriteSelect(KohlerControllerEntity, SelectEntity):
    """Start a stored controller favourite, and show which one is running.

    The controller's equivalent of the valve's preset picker, and its **only** unit of
    control: there is no "set temperature and outlets now" command on this device — you
    create a favourite holding that configuration and activate it.

    Two differences from the valve side worth knowing:

    * **Favourite ids are genuinely reassigned.** Deleting one shifts the others, confirmed
      by an `AllOff-omit` moving from id 6 to id 5 between two reads. GCS presets are fixed
      slots; these are a list. So resolving by name at call time is not a nicety here, it is
      the only correct approach.
    * **Editing is blocked while the system runs** (HTTP 400, `statusCode 902`), though
      *activating* is allowed at any time. That is why the practical pattern is one
      favourite per state, switched by activation.

    Options come from the favourites list, which is seeded over REST and then kept current
    by ``FAVORITES_SNAPSHOT`` — the controller pushes a full list after every create, edit,
    and delete, so the dropdown follows the app without a reload.
    """

    _attr_icon = "mdi:playlist-star"
    _attr_name = "Favourite"

    def __init__(self, coordinator: KohlerAnthemPlusCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._device_id}_favourite"
        self._optimistic: str | None = None

    @staticmethod
    def _name_of(favorite: dict) -> str:
        """The favourite's name, from whichever key this source happens to use.

        **The two sources disagree, and the list is fed by both.** REST ``hub-favorites``
        returns ``title`` with no ``name``; MQTT ``FAVORITES_SNAPSHOT`` returns ``name`` with
        no ``title`` — same ids, same favourites, different key. Since the REST seed is later
        replaced wholesale by snapshots, reading only one key works until the first snapshot
        arrives and then silently empties the dropdown.
        """
        return str(favorite.get("name") or favorite.get("title") or "").strip()

    @property
    def _favourites(self) -> list[dict]:
        """Named favourites only, excluding experiences.

        ``isExperience`` appears in the REST list and marks a firmware program rather than a
        user scene. It is absent from the MQTT snapshot, so this filters what it can see and
        treats a missing flag as "not an experience" — the same direction of error as the
        name fallback above, preferring to show a favourite over hiding one.
        """
        return [
            f
            for f in self.coordinator.favorites
            if self._name_of(f)
            and str(f.get("isExperience", "")).strip().lower() != "true"
        ]

    @property
    def options(self) -> list[str]:
        return [OPTION_OFF] + [self._name_of(f) for f in self._favourites]

    @property
    def current_option(self) -> str | None:
        """The running favourite, or ``Off``.

        ``FAVORITE_STS`` reports the active id, with ``"0"`` meaning nothing is driving the
        system. An id we cannot name falls back to ``Off`` rather than inventing an option,
        since Home Assistant logs an error whenever the current option is not in the list.
        """
        if self._optimistic is not None:
            return self._optimistic
        state = self._state
        if state is None:
            return None
        active = state.active_favorite_id
        if active is None:
            return OPTION_OFF
        for favorite in self._favourites:
            if str(favorite.get("id")) == str(active):
                return self._name_of(favorite)
        return OPTION_OFF

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        state = self._state
        return {
            "active_favorite_id": None if state is None else state.active_favorite_id,
            "favourite_count": len(self._favourites),
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        self._optimistic = None
        super()._handle_coordinator_update()

    async def async_select_option(self, option: str) -> None:
        """Activate the named favourite, or stop everything.

        Resolved by name at call time. Ids shift when a favourite is deleted, so a
        remembered one would eventually start the wrong scene.
        """
        if option == OPTION_OFF:
            # `valvecontrol OFF`, not `stopall`: this dropdown selects a *water* scene, so
            # its Off should stop water and leave music, steam, and lighting alone. The
            # whole-system stop lives on the System switch.
            await self._async_command(
                OPTION_OFF, self.coordinator.async_set_hub_shower(False)
            )
            return
        wanted = option.strip().lower()
        favorite = next(
            (f for f in self._favourites if self._name_of(f).lower() == wanted), None
        )
        if favorite is None:
            raise HomeAssistantError(
                f"No Anthem Plus favourite called {option!r}. It may have been renamed or "
                "deleted in the Konnect app."
            )
        await self._async_command(
            option,
            self.coordinator.async_activate_favorite(
                favorite.get("id"), self._name_of(favorite)
            ),
        )

    async def _async_command(self, option: str, action) -> None:
        self._optimistic = option
        self.async_write_ha_state()
        try:
            await action
        except Exception:
            self._optimistic = None
            self.async_write_ha_state()
            raise
