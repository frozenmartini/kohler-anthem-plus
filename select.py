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
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later

from .anthem_plus import WARMUP_MODES_CURRENT
from .const import DOMAIN, PRESET_HIDDEN_IDS, WARMUP_LABELS
from .coordinator import KohlerAnthemPlusCoordinator
from .entity import KohlerControllerEntity, KohlerValveEntity

# Shown when no favourite is driving the valve. A `select` must always have its current
# option present in the option list or Home Assistant logs an error on every update, and
# "nothing is running" is a real state that needs a name.
OPTION_OFF = "Off"

# How long a just-chosen option is shown before the device's own answer takes over, if the
# device never agrees. Sized off the two confirmations measured live on 2026-08-21: a warmup
# write confirmed 2.2 s later with its MQTT echo 0.8 s after that, and a controller
# favourite's `FAVORITE_STS` arrived 1.5 s after activation. `async_set_warmup` already
# awaits its own readback chain (`WARMUP_READBACK_DELAYS`, up to ~6 s) before this even
# starts, so this is the margin on top, not the whole budget.
#
# It is a backstop, not the normal path: agreement clears it sooner, every time.
OPTIMISTIC_GRACE_SECONDS = 12.0


class OptimisticOptionMixin:
    """Hold a just-chosen option until the device confirms it, or the grace runs out.

    ⚠️ **Clearing on any coordinator update is not good enough**, and that is what all three
    selects here did until 2026-08-21. This coordinator pushes an update for *every* message
    the system sends, so the optimistic value was routinely dropped within milliseconds —
    while the device still reported the old value — and the dropdown visibly snapped back to
    the old option before jumping forward again when the real confirmation landed. The owner
    reported it as "flip flop", and the logs show exactly why:

    * **Warmup.** Selected at 00:21:53, confirmed by the REST readback at 00:21:55.586, MQTT
      echo at 00:21:56.399. Three coordinator updates inside that window, each one a
      snap-back.
    * **Controller favourite.** `FAVORITE_STS` for "Play Music" landed at 07:23:51.575, with
      `STEAM_STS` at 07:23:50.804 and `MUSIC_STS` at 07:23:51.054 arriving first — two clears
      before the one message that actually carried the answer.

    So the value is cleared on exactly two things: **the device agreeing**, or **the grace
    expiring**. A subclass supplies `_device_option`; this supplies `current_option`.

    The grace timer matters more than it looks. Without it a write the device silently
    ignored would leave the dropdown asserting something untrue until the next coordinator
    update happened to arrive — and this system has gone quiet for hours at a stretch. One of
    these dropdowns can start water, so it must not hold a claim it cannot support.
    """

    _optimistic: str | None = None
    _optimistic_cancel = None

    @property
    def _device_option(self) -> str | None:
        """What the device itself says, ignoring anything chosen but not yet confirmed."""
        raise NotImplementedError

    @property
    def current_option(self) -> str | None:
        if self._optimistic is not None:
            return self._optimistic
        return self._device_option

    def _set_optimistic(self, option: str) -> None:
        self._cancel_optimistic_timer()
        self._optimistic = option
        self.async_write_ha_state()

    def _clear_optimistic(self) -> None:
        self._cancel_optimistic_timer()
        if self._optimistic is None:
            return
        self._optimistic = None
        self.async_write_ha_state()

    def _cancel_optimistic_timer(self) -> None:
        if self._optimistic_cancel is not None:
            self._optimistic_cancel()
            self._optimistic_cancel = None

    def _arm_optimistic_expiry(self) -> None:
        """Give up on the guess after the grace, whatever the device has or has not said."""
        self._cancel_optimistic_timer()

        @callback
        def _expire(_now) -> None:
            self._optimistic_cancel = None
            self._clear_optimistic()

        self._optimistic_cancel = async_call_later(
            self.hass, OPTIMISTIC_GRACE_SECONDS, _expire
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        # The one clear that is always right: the device now reports what was asked for, so
        # the guess has been overtaken by fact and there is nothing left to hold.
        if self._optimistic is not None and self._device_option == self._optimistic:
            self._cancel_optimistic_timer()
            self._optimistic = None
        super()._handle_coordinator_update()

    async def async_will_remove_from_hass(self) -> None:
        self._cancel_optimistic_timer()
        await super().async_will_remove_from_hass()


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
        entities.append(ValveWarmupSelect(coordinator))
    if coordinator.hub_device is not None:
        # The controller keeps its own favourites on a different command surface. Both can
        # exist on one account, on their own devices, which is why they are separate
        # entities rather than one merged list.
        entities.append(HubFavouriteSelect(coordinator))
    async_add_entities(entities)


class FavouriteSelect(OptimisticOptionMixin, KohlerValveEntity, SelectEntity):
    """Start a stored favourite, and show which one is running."""

    _attr_icon = "mdi:playlist-play"
    _attr_name = "Favourite"

    def __init__(self, coordinator: KohlerAnthemPlusCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._device_id}_favourite"
        # Holds the requested option until the valve reports back, matching the outlet
        # switches. Activation takes 1-2 s on real hardware.

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
    def _device_option(self) -> str | None:
        """The running favourite, or ``Off``.

        ``presetOrExperienceId`` is cleared by **both** pause and stop, so a paused session
        reads as ``Off`` here while the outlet switches still show their assignment. It is
        also never set by a direct outlet command, so opening an outlet by hand leaves this
        at ``Off`` with water running — this reports *what started the session*, not whether
        water is on.
        """
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
        self._set_optimistic(option)
        try:
            await action
        except Exception:
            # The command failed, so stop showing a state the valve never reached.
            self._clear_optimistic()
            raise
        # The command was accepted. The device's own confirmation is still in flight — 1.5 s
        # for a controller favourite, measured — so hold the guess until it lands rather than
        # dropping it on the next unrelated message.
        self._arm_optimistic_expiry()


class ValveWarmupSelect(OptimisticOptionMixin, KohlerValveEntity, SelectEntity):
    """The valve's warmup mode — the dropdown, and the state, are the mode itself.

    Warmup runs water up to temperature before the session proper. This entity is the
    **mode**: which warmup the valve will do, with ``Off`` as one of the choices. It is not
    whether a warm-up is happening at this instant — those are two independent axes in the
    device's own state (``warmUpState.warmUp`` vs ``warmUpState.state``), and a control bound
    to the second reads "off" almost always, because a warm-up is over in seconds. "Warming
    Up" is reported by the valve Status sensor; both axes appear in the attributes here.

    **Three options** — ``Off``, ``All Outlets``, ``Started Outlets``, all with no start
    delay. These are the three modes the current Konnect app can write, but the labels are
    this integration's own since 2026-08-21 and no longer echo the app's wording; see
    ``WARMUP_LABELS`` in ``const.py``. Which outlets ``Started Outlets`` refers to is not
    exposed by any cloud API: it is per-zone `warmupOutlets` on the controller's local API,
    so this dropdown chooses the *mode* and the selection itself is configured on the device.

    ⚠️ **A valve can hold a mode this list does not offer.** Two legacy delayed-start values
    still parse in firmware. If the valve reports one, it is appended to the options for as
    long as it is in force, so the entity reports the truth rather than an error — but it is
    never on the menu otherwise, because nothing establishes what their delay does.

    ⚠️ **Something outside Home Assistant keeps setting this back to Off.** Four times
    between 2026-08-13 and 08-18 the mode reverted with no command visible on the MQTT
    channel and nothing from this integration. It is not the reboots: the mode survives
    those. The writer is unidentified; the leading candidate is the Anthem Plus controller
    over the RJ wired link, which cannot be observed. **If this dropdown moves to Off on its
    own, that is the device.** See `docs/gcs/api.md` §3e.

    The value here is the REST field, `warmUpState.warmUp` — read at setup, on every MQTT
    reconnect, and again after every write, because a 200 from the cloud is not evidence the
    valve applied anything. The device's `GCS_WARM_STS` push corrects it too; measured
    2026-08-20, that echo lands **3.42 s** after the write and the REST field catches up on
    about the same schedule, which is why the confirmation is retried rather than read once.
    """

    _attr_icon = "mdi:thermometer-water"
    _attr_name = "Warmup"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: KohlerAnthemPlusCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._device_id}_warmup"

    @property
    def _mode(self) -> str | None:
        state = self._state
        return None if state is None else state.warmup_mode

    @property
    def options(self) -> list[str]:
        """The three current modes, plus whatever the valve is holding if it is not one.

        Home Assistant logs an error on every update when `current_option` is absent from
        this list, so a mode we would never write still has to appear while it is in force.
        """
        labels = [WARMUP_LABELS[mode] for mode in WARMUP_MODES_CURRENT]
        held = self._mode
        if held is not None and held not in WARMUP_MODES_CURRENT:
            labels.append(WARMUP_LABELS.get(held, held))
        return labels

    @property
    def _device_option(self) -> str | None:
        mode = self._mode
        if mode is None:
            # Never announced. `Off` would be a guess, and the wrong one to show for a
            # setting somebody may be trying to confirm is on.
            return None
        return WARMUP_LABELS.get(mode, mode)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The raw mode string, and the axis this entity deliberately does not show."""
        state = self._state
        if state is None:
            return {}
        return {
            "warmup_mode": state.warmup_mode,
            "warmup_in_progress": state.warmup_in_progress,
        }

    async def async_select_option(self, option: str) -> None:
        """Write the mode behind the chosen label.

        Optimistic like the favourite selector: the valve echoes the new mode back as a
        `GCS_WARM_STS` message, and that echo is the only real confirmation there is — a 200
        from the cloud means the command was accepted, never that the valve applied it.
        """
        mode = next(
            (value for value, label in WARMUP_LABELS.items() if label == option), None
        )
        if mode is None:
            raise HomeAssistantError(f"{option!r} is not a warmup mode")
        if mode not in WARMUP_MODES_CURRENT and mode != self._mode:
            raise HomeAssistantError(
                f"{option!r} is a legacy mode this integration does not write. It is listed "
                "only because the valve is currently holding it."
            )
        self._set_optimistic(option)
        try:
            await self.coordinator.async_set_warmup(mode)
        except Exception:
            self._clear_optimistic()
            raise
        # `async_set_warmup` has already read the mode back and applied it, so in the normal
        # case the device agrees by now and the next coordinator update clears this. The
        # timer only matters for the case that call warns about: the cloud accepting a
        # command the valve then ignores.
        self._arm_optimistic_expiry()


class HubFavouriteSelect(OptimisticOptionMixin, KohlerControllerEntity, SelectEntity):
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
        names = [self._name_of(f) for f in self._favourites]
        # `FAVORITE_STS` can name a favourite the list has not caught up with — one created
        # moments ago, or a cold start before the first snapshot lands. Home Assistant logs
        # an error on every update when `current_option` is missing from `options`, so carry
        # it while it is in force, the same way `ValveWarmupSelect` carries a legacy mode.
        state = self._state
        running = None if state is None else state.active_favorite_name
        if running and running not in names:
            names.append(running)
        return [OPTION_OFF] + names

    @property
    def _device_option(self) -> str | None:
        """The running favourite, or ``Off``.

        ``FAVORITE_STS`` reports the active favourite's **name** alongside its id, and the
        name is preferred: it is right even before the favourites list has been seeded, and
        it cannot be thrown off by ids being reassigned when a favourite is deleted. The id
        lookup stays as a fallback for a message that somehow carried no name.

        ``active_favorite_id`` of ``None`` means nothing is driving the system — either a
        ``status: "OFF"`` message or an id of ``"0"``. An id that resolves to no name falls
        back to ``Off`` rather than inventing an option.
        """
        state = self._state
        if state is None:
            return None
        active = state.active_favorite_id
        if active is None:
            return OPTION_OFF
        # Safe to return directly: `options` carries this name whether or not the favourites
        # list knows it yet.
        if state.active_favorite_name:
            return state.active_favorite_name
        for favorite in self._favourites:
            if str(favorite.get("id")) == str(active):
                return self._name_of(favorite)
        return OPTION_OFF

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        state = self._state
        return {
            "active_favorite_id": None if state is None else state.active_favorite_id,
            "active_favorite_name": (
                None if state is None else state.active_favorite_name
            ),
            "favourite_count": len(self._favourites),
        }

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
        self._set_optimistic(option)
        try:
            await action
        except Exception:
            self._clear_optimistic()
            raise
        # The command was accepted. The device's own confirmation is still in flight — 1.5 s
        # for a controller favourite, measured — so hold the guess until it lands rather than
        # dropping it on the next unrelated message.
        self._arm_optimistic_expiry()
