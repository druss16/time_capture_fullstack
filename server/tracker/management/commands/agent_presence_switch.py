"""
Remote off switch for the desktop agent's agent-presence MEASUREMENT.
Never affects time tracking. Agents pick a change up within ~40 seconds
(30s server cache + 10s check-in), and an agent that is switched off stays off
across restarts until switched back on.

    python manage.py agent_presence_switch status
    python manage.py agent_presence_switch off --all   --note "Windows CPU report"
    python manage.py agent_presence_switch off --org 21
    python manage.py agent_presence_switch off --device DESKTOP-ABC123   (pk, device_id or hostname)
    python manage.py agent_presence_switch on  --all
    python manage.py agent_presence_switch clear --org 21   (remove the row; inherit again)

Most specific wins: device, then firm, then everyone. So `on --all` does NOT
override a firm or device that was switched off — clear those rows instead.

Emergency path with no database: set AGENT_PRESENCE_DISABLED=1 on the Render
service. It beats every row.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from tracker.models import AgentDevice, AgentPresenceSwitch, Organization
from tracker.services.agent_presence_switch import (
    clear_switch, env_disabled_value, set_switch,
)


class Command(BaseCommand):
    help = "Switch the agent-presence measurement on/off for everyone, a firm or a device."

    def add_arguments(self, parser):
        parser.add_argument('action', choices=['status', 'on', 'off', 'clear'])
        scope = parser.add_mutually_exclusive_group()
        scope.add_argument('--all', action='store_true', help='everyone')
        scope.add_argument('--org', type=int, help='organization id')
        scope.add_argument('--device', help='device pk, device_id or hostname')
        parser.add_argument('--note', default='')

    def _device(self, ref):
        q = Q(device_id=ref) | Q(hostname__iexact=ref)
        if ref.isdigit():
            q |= Q(pk=int(ref))
        matches = list(AgentDevice.objects.filter(q).order_by('-last_seen_at')[:5])
        if not matches:
            raise CommandError(f"No device matches {ref!r}.")
        if len({d.pk for d in matches}) > 1:
            listing = ", ".join(f"pk={d.pk} {d.hostname} (seen {d.last_seen_at})" for d in matches)
            raise CommandError(f"{ref!r} matches several devices — pass a pk: {listing}")
        return matches[0]

    def handle(self, *args, action, all, org, device, note, **opts):
        if action == 'status':
            return self._status()
        if not (all or org or device):
            raise CommandError("Say who: --all, --org ID or --device REF.")

        scope = {'org_id': None, 'device_pk': None}
        label = 'everyone'
        if org:
            o = Organization.objects.filter(pk=org).first()
            if not o:
                raise CommandError(f"No organization {org}.")
            scope['org_id'], label = org, f"firm {org} ({o.name})"
        elif device:
            d = self._device(device)
            scope['device_pk'], label = d.pk, f"device pk={d.pk} ({d.hostname})"

        if action == 'clear':
            n = clear_switch(**scope)
            self.stdout.write(f"Cleared {n} row(s) for {label}; it now inherits.")
        else:
            set_switch(action == 'on', note=note, **scope)
            self.stdout.write(self.style.SUCCESS(
                f"Agent presence measurement {action.upper()} for {label}. "
                f"Agents pick this up within ~40s."))
        self._status()

    def _status(self):
        env = env_disabled_value()
        if env:
            self.stdout.write(self.style.WARNING(
                f"AGENT_PRESENCE_DISABLED={env!r} is set — OFF for everyone regardless of rows."))
        rows = list(AgentPresenceSwitch.objects.order_by('device_pk', 'org_id'))
        if not rows:
            self.stdout.write("No switch rows: ON for everyone (default).")
        for r in rows:
            self.stdout.write(f"  {r}  (updated {r.updated_at:%Y-%m-%d %H:%M}){'  — ' + r.note if r.note else ''}")
