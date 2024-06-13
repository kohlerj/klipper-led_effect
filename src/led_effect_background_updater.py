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

class State(Enum):
    READY = 'ready',
    BUSY = 'busy',
    BED_HEATING = 'bed_heating',
    BED_HEATSOAK_WAIT = 'bed_heatsoak_wait',
    NOZZLE_HEATING = 'nozzle_heating',
    CHAMBER_HEATING = 'chamber_heating',
    LEVELING = 'leveling',
    HOMING = 'homing',
    CLEANING = 'cleaning',
    PURGING = 'purging',
    MESHING = 'meshing',
    CANCELLING = 'cancelling',
    CANCELLED = 'cancelled',
    PAUSING = 'pausing',
    PAUSED = 'paused',
    RESUMING = 'resuming',
    PRINTING = 'printing',
    DONE_PRINTING = 'done_printing',
    OFF = 'off',
    ERROR = 'error'



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

        for state in State:
            self._statesToEffectNamesMap[state] = config.getlist(state.value, default=None)

        self.printer.register_event_handler("klippy:connect", self._handle_connect)

    cmd_ACTIVATE_BACKGROUND_LED_UPDATE_help = "Activates the background led update"
    cmd_DEACTIVATE_BACKGROUND_LED_UPDATE_help = "Deactivates the background led update"

    def cmd_ACTIVATE_BACKGROUND_LED_UPDATE(self):
        self._active = True

    def cmd_DEACTIVATE_BACKGROUND_LED_UPDATE(self):
        self._active = False

    def _handle_connect(self):
        self._displayStatus = self.printer.lookup_object("display_status")
        self._printStats = self.printer.lookup_object("print_stats")
        self._idleTimeout = self.printer.lookup_object("idle_timeout")

        effects = {}
        for effect in self.printer.lookup_objects("led_effect"):
            effects[effect.name] = effect

        self._statesToEffectsMap = {}
        for state, effectNames in self._statesToEffectNamesMap.items():
            self._statesToEffectsMap[state] = []
            for effectName in effectNames:
                if effectName not in effects.keys():
                    raise self.printer.config_error(
                        "Effect '%s' for state '%s' is configured but not found as led_effect"
                        % (effectName, state)
                    )

                self._statesToEffectsMap[state].append(effects[effectName])

        self._updateTimer = self.reactor.register_timer(self._update, self.reactor.NOW)

    def _compute_state(self):
        idle_timeout_state = self._idleTimeout.state
        print_stats_state = self._printStats.state
        message_state = self._displayStatus.message

        logging.debug(
            "idle_timeout_state: %s, print_stats_state: %s, message_state: %s",
            idle_timeout_state,
            print_stats_state,
            message_state,
        )

        if idle_timeout_state == "idle":
            state = State.READY
        elif idle_timeout_state == "ready":
            if print_stats_state == "error":
                state = State.ERROR
            elif print_stats_state == "cancelled":
                state = State.CANCELLED
            elif print_stats_state == "paused":
                state = State.PAUSED
            elif print_stats_state == "complete":
                state = State.DONE_PRINTING
            elif print_stats_state == "standby":
                state = State.READY
            else:
                logging.warning(
                    'Unknown print_stats    state: %s in idle_timeout_state "idle"',
                    print_stats_state,
                )
                state = State.READY

        elif idle_timeout_state == "printing":
            if "homing" in message_state:
                state = State.HOMING
            elif "meshing" in message_state:
                state = State.MESHING
            elif "leveling" in message_state:
                state = State.LEVELING
            elif "purging" in message_state:
                state = State.PURGING
            elif "cleaning" in message_state:
                state = State.CLEANING
            elif "heating chamber" in message_state:
                state = State.CHAMBER_HEATING
            elif "heating bed" in message_state:
                state = State.BED_HEATING
            elif "heating nozzle" in message_state:
                state = State.NOZZLE_HEATING
            else:
                if print_stats_state == "printing":
                    state = State.PRINTING
                else:
                    state = State.BUSY
        else:
            logging.warning("Unknown idle_timeout state: %s", idle_timeout_state)
            state = State.READY

        self._lastComputedState = state

        logging.debug("Computed state: %s", state)

        return state

    def _update(self, eventtime):
        if self._active:
            state = self._compute_state()

            for effect in self._statesToEffectsMap[state]:
                effect.set_led_effect(fadetime=self._fadeDuration, replace=True)

        return eventtime + self._updateRate

    def get_status(self, eventtime):
        return {"active": self._active, "last_computed_state": self._lastComputedState.value}


def load_config(config):
    return ledBackgroundHandler(config)
