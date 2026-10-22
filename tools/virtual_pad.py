#!/usr/bin/env python3
"""Virtual gamepad (uinput) to test Big Screen without a physical controller.

Usage: virtual_pad.py guide wait:1.5 down down right a wait:2 b guide
Buttons: a b x y lb rb lt rt select start guide up down left right
         stick-up/down/left/right (left stick, 0.4 s)  hold:<button>:<seconds>
         shot:<file.png> (screenshot with grim)  wait:<seconds>
"""

import subprocess
import sys
import time

from evdev import AbsInfo, UInput, ecodes as e

BUTTONS = {
    "a": e.BTN_SOUTH, "b": e.BTN_EAST, "x": e.BTN_X, "y": e.BTN_Y, "lb": e.BTN_TL, "rb": e.BTN_TR,
    "lt": e.BTN_TL2, "rt": e.BTN_TR2, "select": e.BTN_SELECT, "start": e.BTN_START, "guide": e.BTN_MODE,
}
HAT = {"up": (e.ABS_HAT0Y, -1), "down": (e.ABS_HAT0Y, 1), "left": (e.ABS_HAT0X, -1), "right": (e.ABS_HAT0X, 1)}
STICK = {"stick-up": (e.ABS_Y, -32767), "stick-down": (e.ABS_Y, 32767),
         "stick-left": (e.ABS_X, -32767), "stick-right": (e.ABS_X, 32767)}

stick = AbsInfo(value=0, min=-32768, max=32767, fuzz=16, flat=128, resolution=0)
hat = AbsInfo(value=0, min=-1, max=1, fuzz=0, flat=0, resolution=0)
caps = {
    e.EV_KEY: list(BUTTONS.values()) + [e.BTN_THUMBL, e.BTN_THUMBR],
    e.EV_ABS: [(e.ABS_X, stick), (e.ABS_Y, stick), (e.ABS_RX, stick), (e.ABS_RY, stick),
               (e.ABS_HAT0X, hat), (e.ABS_HAT0Y, hat)],
}


def press(ui, code, hold=0.08):
    ui.write(e.EV_KEY, code, 1)
    ui.syn()
    time.sleep(hold)
    ui.write(e.EV_KEY, code, 0)
    ui.syn()


def axis(ui, code, value, hold):
    ui.write(e.EV_ABS, code, value)
    ui.syn()
    time.sleep(hold)
    ui.write(e.EV_ABS, code, 0)
    ui.syn()


def main(args):
    with UInput(caps, name="Big Screen Test Pad", vendor=0x045E, product=0x028E, version=0x110,
                phys="bigscreen-test/input0") as ui:
        time.sleep(1.2)  # let udev apply the ACL and Big Screen pick the device up
        for arg in args:
            if arg.startswith("shot:"):
                subprocess.run(["grim", arg[5:]], check=False)
                continue
            if arg.startswith("wait:"):
                time.sleep(float(arg[5:]))
            elif arg.startswith("hold:"):
                _, name, seconds = arg.split(":")
                if name in HAT:
                    axis(ui, *HAT[name], float(seconds))
                else:
                    press(ui, BUTTONS[name], float(seconds))
            elif arg in BUTTONS:
                press(ui, BUTTONS[arg])
            elif arg in HAT:
                axis(ui, *HAT[arg], 0.08)
            elif arg in STICK:
                axis(ui, *STICK[arg], 0.4)
            else:
                sys.exit(f"unknown command: {arg}")
            time.sleep(0.25)
        time.sleep(0.3)


if __name__ == "__main__":
    main(sys.argv[1:])
