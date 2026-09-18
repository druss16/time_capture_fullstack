"""Is the agent able to see a camera or microphone in use right now?

    cd windows_agent   (or mac_agent)
    python check_capture.py

Answers in one second what otherwise takes an install and a ten-minute wait:
whether media_capture — the module that decides whether to keep counting time
while someone sits still on a call — can see the devices on THIS machine.

It imports the shipped module rather than reimplementing it, so it cannot
drift from what the agent actually does. A copy that drifts is worse than no
check at all: it reports success while the real code returns nothing.

Run it twice — once with nothing using the camera, once during a call. The
second run should name the device. If it does not, the agent will let idle
win mid-call on this machine, whatever it does elsewhere.
"""
import sys
import time

try:
    from media_capture import IS_MAC, IS_WINDOWS, capture_in_use
except ImportError:
    sys.exit("Run this from inside mac_agent/ or windows_agent/, "
             "where media_capture.py lives.")


def main():
    platform = 'macOS' if IS_MAC else 'Windows' if IS_WINDOWS else sys.platform
    started = time.time()
    state = capture_in_use(force=True)
    took_ms = (time.time() - started) * 1000

    print()
    print(f"platform : {platform}")
    print(f"probe    : {took_ms:.1f}ms")

    if state.error:
        print(f"ERROR    : {state.error}")
        if 'CoreMediaIO' in state.error:
            # Almost always this script run under a system Python rather than
            # a problem with the agent, which bundles the framework.
            print("\n-> The camera probe needs pyobjc, which the packaged "
                  "agent bundles but a system Python does not. Either "
                  "'pip install pyobjc-framework-CoreMediaIO' and re-run, or "
                  "check the agent's own log for [CAPTURE] lines instead.")
        else:
            print("\n-> The probe could not run. The agent will fall back to "
                  "keyboard/mouse idle only, so calls will be cut short on "
                  "this machine.")
        return 2

    if state.active:
        print(f"in use   : {', '.join(state.devices)}")
        print("\n-> The agent will hold idle off while this is true.")
        return 0

    print("in use   : nothing")
    print("\n-> Correct if no call is running. Start one (or open the Camera "
          "app / Photo Booth) and run again — it should name the device.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
