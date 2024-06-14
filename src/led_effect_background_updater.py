# Support for addressable background updated of LED effects based on printer state
# This module requires a special version of klipper-led_effect
#
# Copyright (C) 2024  Julien Kohler <22sunit@gmail.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging
from enum import Enum

######################################################################
# LED Effect handler
######################################################################


class StateComplement(Enum):
    BED_HEATING = "bed_heating"
    BED_HEATSOAK_WAIT = "bed_heatsoak_wait"
    NOZZLE_HEATING = "nozzle_heating"
    CHAMBER_HEATING = "chamber_heating"
    LEVELING = "leveling"
    HOMING = "homing"
    CLEANING = "cleaning"
    PURGING = "purging"
    MESHING = "meshing"
    CANCELLING = "cancelling"
    PAUSING = "pausing"
    RESUMING = "resuming"
    OFF = "off"


class State(Enum):
    READY = "ready"
    BUSY = "busy"
    CANCELLED = "cancelled"
    PAUSED = "paused"
    PRINTING = "printing"
    PRINT_COMPLETE = "print_complete"
    ERROR = "error"

    # Copy of StateComplement, cannot extend Enum
    BED_HEATING = "bed_heating"
    BED_HEATSOAK_WAIT = "bed_heatsoak_wait"
    NOZZLE_HEATING = "nozzle_heating"
    CHAMBER_HEATING = "chamber_heating"
    LEVELING = "leveling"
    HOMING = "homing"
    CLEANING = "cleaning"
    PURGING = "purging"
    MESHING = "meshing"
    CANCELLING = "cancelling"
    PAUSING = "pausing"
    RESUMING = "resuming"
    OFF = "off"


class ledBackgroundHandler:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object("gcode")

        self.gcode.register_command(
            "ACTIVATE_BACKGROUND_LED_UPDATE",
            self.cmd_ACTIVATE_BACKGROUND_LED_UPDATE,
            desc=self.cmd_ACTIVATE_BACKGROUND_LED_UPDATE_help,
        )

        self.gcode.register_command(
            "DEACTIVATE_BACKGROUND_LED_UPDATE",
            self.cmd_DEACTIVATE_BACKGROUND_LED_UPDATE,
            desc=self.cmd_DEACTIVATE_BACKGROUND_LED_UPDATE_help,
        )

        self.gcode.register_command(
            "SET_BACKGROUND_LED_UPDATE_COMPLEMENT",
            self.cmd_SET_BACKGROUND_LED_UPDATE_COMPLEMENT,
            desc=self.cmd_SET_BACKGROUND_LED_UPDATE_COMPLEMENT_help,
        )

        self.gcode.register_command(
            "RESET_BACKGROUND_LED_UPDATE_COMPLEMENT",
            self.cmd_RESET_BACKGROUND_LED_UPDATE_COMPLEMENT,
            desc=self.cmd_RESET_BACKGROUND_LED_UPDATE_COMPLEMENT_help,
        )

        self.short_name = 'bckgnd_led_updater'

        self._active = False

        self._fadeDuration = config.getfloat(
            "fade_duration", default=0.5, minval=0.0, maxval=5
        )

        updateFrequency = config.getfloat(
            "update_frequency", default=1, minval=0.1, maxval=5
        )
        self._updateRate = 1.0 / updateFrequency

        self._statesToEffectNamesMap = {}

        self._stateComplement = []

        self._lastState = []

        for state in State:
            self._statesToEffectNamesMap[state] = config.getlist(
                state.value, default=None
            )

        self.printer.register_event_handler("klippy:connect", self._handle_connect)
        self.printer.register_event_handler("klippy:ready", self._handle_ready)

    cmd_ACTIVATE_BACKGROUND_LED_UPDATE_help = "Activates the background led update"
    cmd_DEACTIVATE_BACKGROUND_LED_UPDATE_help = "Deactivates the background led update"
    cmd_SET_BACKGROUND_LED_UPDATE_COMPLEMENT_help = (
        "Set the led effect state complement"
    )
    cmd_RESET_BACKGROUND_LED_UPDATE_COMPLEMENT_help = (
        "Reset the led effect state complement"
    )

    def cmd_SET_BACKGROUND_LED_UPDATE_COMPLEMENT(self, gcmd):
        stateComplement = gcmd.get("VALUE")
        if stateComplement not in [state.value for state in State]:
            raise gcmd.error(
                "VALUE parameter must be a lowercase string from the list %s"
                % [state.value for state in StateComplement]
            )

        self.toolhead.wait_moves()
        self._stateComplement.append(stateComplement)
        logging.info("Add led effect state to list of stateComplement %s", self._stateComplement)

    def cmd_RESET_BACKGROUND_LED_UPDATE_COMPLEMENT(self, gcmd):
        self.toolhead.wait_moves()
        self._stateComplement.pop()

    def cmd_ACTIVATE_BACKGROUND_LED_UPDATE(self, gcmd):
        self._active = True

    def cmd_DEACTIVATE_BACKGROUND_LED_UPDATE(self, gcmd):
        self._active = False

    def _handle_connect(self):
        self._printStats = self.printer.lookup_object("print_stats")
        self._idleTimeout = self.printer.lookup_object("idle_timeout")
        self.reactor = self.printer.get_reactor()

        self._lastStateChange = self.reactor.NOW

        effects = {}

        filtered_effects = [
            effect[1]
            for effect in self.printer.lookup_objects("led_effect")
            if hasattr(effect[1], "name")
        ]

        for effect in filtered_effects:
            effects[effect.name] = effect

        self._statesToEffectsMap = {}
        for state, effectNames in self._statesToEffectNamesMap.items():
            self._statesToEffectsMap[state] = []
            for effectName in effectNames:
                if effectName not in effects.keys():
                    raise self.printer.config_error(
                        "Effect '%s' for state '%s' is configured but not found as led_effect"
                        % (effectName, state.value)
                    )

                self._statesToEffectsMap[state].append(effects[effectName])

        self._updateTimer = self.reactor.register_timer(self._update, self.reactor.NOW)

    def _handle_ready(self):

        self.toolhead = self.printer.lookup_object('toolhead')
        

    def _compute_state(self):
        idleTimeoutState = self._idleTimeout.state.lower()
        printStatsState = self._printStats.state.lower()
        stateComplement = self._stateComplement[-1] if len(self._stateComplement) > 0 else ""

        if idleTimeoutState == "idle":
            state = State.OFF

            # we can no longer be in a nested state so we clear the state complement
            if len(self._stateComplement) > 0:
                self._stateComplement = []

        elif idleTimeoutState == "ready":

            # we can no longer be in a nested state so we clear the state complement
            if len(self._stateComplement) > 0:
                self._stateComplement = []

            if printStatsState == "standby":
                state = State.READY

            elif printStatsState == "printing":
                raise "printing print_stats state in idle_timeout state 'ready' should not be possible"  # This should never happen

            elif printStatsState == "complete":
                state = State.DONE_PRINTING

            elif printStatsState == "paused":
                state = State.PAUSED

            elif printStatsState == "cancelled":
                state = State.CANCELLED

            elif printStatsState == "error":
                state = State.ERROR

            else:
                logging.error(
                    'Unknown print_stats    state: %s in idle_timeout_state "idle"',
                    printStatsState,
                )
                state = State.READY

        elif idleTimeoutState == "printing":
            if printStatsState == "standby":
                if stateComplement:
                    state = State(stateComplement)
                else:
                    state = State.BUSY

            elif printStatsState == "printing":
                if stateComplement:
                    state = State(stateComplement)
                else:
                    state = State.PRINTING

            elif printStatsState == "complete":
                state = State.PRINT_COMPLETE

            elif printStatsState == "paused":
                if stateComplement == State.CANCELLING.value:
                    state = State.CANCELLING
                elif stateComplement == State.RESUMING.value:
                    state = State.RESUMING
                else:
                    state = State.PAUSED

            elif printStatsState == "cancelled":
                state = State.CANCELLED

            elif printStatsState == "error":
                state = State.ERROR

            else:
                logging.error(
                    'Unknown print_stats    state: %s in idle_timeout_state "idle"',
                    printStatsState,
                )
                state = State.BUSY
        else:
            logging.error("Unknown idle_timeout state: %s", idleTimeoutState)
            state = State.READY

        logging.debug("Computed state: %s from idle_timeout_state: %s, print_stats_state: %s, state_complement: %s", state, idleTimeoutState, printStatsState, self._stateComplement)

        return state

    def _update(self, eventtime):

        state = self._compute_state()

        if state != self._lastState:
            self._lastStateChange = eventtime
            self._lastState = state

            if self._active:
                for effect in self._statesToEffectsMap[state]:
                    effect.set_led_effect(fadetime=self._fadeDuration, replace=True)

        return eventtime + self._updateRate

    def get_status(self, eventtime):
        return {
            "active": self._active,
        }

    def stats(self, eventtime):
        is_active = eventtime - self._lastStateChange < 30.
        return is_active, '%s: last_state=%s its=%s pss=%s sc=%s' % (
            self.short_name, self._lastState.value, self._idleTimeout.state.lower(), self._printStats.state.lower(), self._stateComplement)


def load_config(config):
    return ledBackgroundHandler(config)
