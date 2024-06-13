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

        self._active = False

        self._fadeDuration = config.getfloat(
            "fade_duration", default=0.5, minval=0.0, maxval=5
        )

        updateFrequency = config.getfloat(
            "update_frequency", default=1, minval=0.1, maxval=5
        )
        self._updateRate = 1.0 / updateFrequency

        self._lastComputedState = State.READY

        self._statesToEffectNamesMap = {}

        self._stateComplement = ""

        for state in State:
            self._statesToEffectNamesMap[state] = config.getlist(
                state.value, default=None
            )

        self.printer.register_event_handler("klippy:connect", self._handle_connect)

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

        self._stateComplement = stateComplement
        logging.info("Set led effect state to %s", self._stateComplement)

    def cmd_RESET_BACKGROUND_LED_UPDATE_COMPLEMENT(self, gcmd):
        self._stateComplement = ""

    def cmd_ACTIVATE_BACKGROUND_LED_UPDATE(self, gcmd):
        self._active = True

    def cmd_DEACTIVATE_BACKGROUND_LED_UPDATE(self, gcmd):
        self._active = False

    def _handle_connect(self):
        self._printStats = self.printer.lookup_object("print_stats")
        self._idleTimeout = self.printer.lookup_object("idle_timeout")
        self.reactor = self.printer.get_reactor()

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

    def _compute_state(self):
        idle_timeout_state = self._idleTimeout.state.lower()
        print_stats_state = self._printStats.state.lower()
        state_complement = self._stateComplement

        logging.info(
            "idle_timeout_state: %s, print_stats_state: %s, state_complement: %s",
            idle_timeout_state,
            print_stats_state,
            state_complement,
        )

        if idle_timeout_state == "idle":
            state = State.OFF

        elif idle_timeout_state == "ready":
            if print_stats_state == "standby":
                state = State.READY

            elif print_stats_state == "printing":
                raise "printing print_stats state in idle_timeout state 'ready' should not be possible"  # This should never happen

            elif print_stats_state == "complete":
                state = State.DONE_PRINTING

            elif print_stats_state == "paused":
                state = State.PAUSED

            elif print_stats_state == "cancelled":
                state = State.CANCELLED

            elif print_stats_state == "error":
                state = State.ERROR

            else:
                logging.error(
                    'Unknown print_stats    state: %s in idle_timeout_state "idle"',
                    print_stats_state,
                )
                state = State.READY

        elif idle_timeout_state == "printing":
            if print_stats_state == "standby":
                if state_complement:
                    state = State(state_complement)
                else:
                    state = State.BUSY

            elif print_stats_state == "printing":
                if state_complement:
                    state = State(state_complement)
                else:
                    state = State.PRINTING

            elif print_stats_state == "complete":
                state = State.PRINT_COMPLETE

            elif print_stats_state == "paused":
                if state_complement == State.CANCELLING.value:
                    state = State.CANCELLING
                elif state_complement == State.RESUMING.value:
                    state = State.RESUMING
                else:
                    state = State.PAUSED

            elif print_stats_state == "cancelled":
                state = State.CANCELLED

            elif print_stats_state == "error":
                state = State.ERROR

            else:
                logging.error(
                    'Unknown print_stats    state: %s in idle_timeout_state "idle"',
                    print_stats_state,
                )
                state = State.BUSY
        else:
            logging.error("Unknown idle_timeout state: %s", idle_timeout_state)
            state = State.READY

        self._lastComputedState = state

        logging.info("Computed state: %s", state)

        return state

    def _update(self, eventtime):
        if self._active:
            state = self._compute_state()

            for effect in self._statesToEffectsMap[state]:
                effect.set_led_effect(fadetime=self._fadeDuration, replace=True)

        return eventtime + self._updateRate

    def get_status(self, eventtime):
        return {
            "active": self._active,
            "last_computed_state": self._lastComputedState.value,
        }


def load_config(config):
    return ledBackgroundHandler(config)
