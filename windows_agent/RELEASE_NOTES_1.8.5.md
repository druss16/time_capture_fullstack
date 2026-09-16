# TimeTracker Agent 1.8.5

## The agent no longer bills its own sleep

When the tracking loop stops iterating — the machine sleeps, a thread freezes, a
syscall blocks — nothing is observed and the open dwell is simply left open. Idle
detection is polled *inside* that same loop, so it cannot fire either. When the
loop comes back it closes the dwell over the entire gap and records all of it as
active time.

On one machine this recorded **8h50m of overnight QuickBooks as billable client
time**, because QuickBooks happened to be the foreground window when the user
went home. Across 30 days it produced 20 hours of phantom billable time on two
clients.

`_emit_current_dwell` now credits at most one idle-grace window of any stretch
the loop did not observe — exactly what idle detection would have credited had it
been able to run — and drops the rest. `last_emit_ts` still advances to the true
end, so the dropped span is never re-emitted by the following heartbeat.

## What this does not change

- **Short freezes cost nothing.** Anything inside the grace window (10 minutes by
  default) is credited in full. Measured over 30 days of real fleet data, 10 of
  16 observed stalls were under the grace and lost zero minutes. A 9-minute
  freeze mid-work still keeps every second.
- **IDLE dwells are untouched.** The agent chunks idle spans the same way, but
  recording them is the point — they keep their full span.
- **Normal capture is byte-identical.** Heartbeats, window changes, and short
  dwells behave exactly as in 1.8.4.

The change can only ever *under*-count. It cannot invent time.

## Safety

The grace window is floored at one heartbeat. `mouse_idle_pause_seconds` is an
org setting with no server-side validators, and a zero would otherwise have
collapsed the write loop to zero iterations and silently stopped all recording.
Verified across idle-pause values of `None / 0 / -5 / 1 / 60 / 600 / 3600 /
999999`: every case writes at least one event and advances the dwell correctly.

## Visibility

A stall now reports `unobserved_gap` to the backend on the resume path, carrying
the gap length, what was credited, and the foreground window. Previously every
error call site was an exception handler or a watchdog that required the loop to
be running — and a frozen loop raises nothing, which is why this went unnoticed
for a month. The server marks the same events at ingest independently, so the
signal exists whether or not an agent has taken this build.

## Server side

Shipped separately in the API (no agent dependency): the same rule runs at
ingest, and `repair_unobserved_time` retires historical phantom time. Agents
still on 1.8.4 or earlier are protected by the server rule.
