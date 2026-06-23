import subprocess, os
base = "/app/tracker" if os.path.isdir("/app/tracker") else "tracker"
def grep(p):
    try: return subprocess.run(["grep","-rln",p,base],capture_output=True,text=True,timeout=20).stdout.strip()
    except Exception as e: return f"(err {e})"

print("="*70)
print("Files with client alias / name matching logic:")
print("="*70)
for pat in ("alias","fuzzy","_match_client","match_client_name","client_name_match","aliases"):
    hits = grep(pat)
    if hits:
        print(f"\n[{pat}]\n{hits}")
print("="*70)
# Client model fields — does it have aliases?
from tracker.models import Client
fields = [f.name for f in Client._meta.get_fields()]
print("Client model fields:", [f for f in fields if not f.startswith('_')][:40])
print("="*70)
# sample a few org-21 clients with aliases
cs = Client.objects.filter(org_id=21)[:5]
for c in cs:
    al = getattr(c, 'aliases', None)
    print(f"  client {c.id}: {c.name!r}  aliases={al}")
print("="*70)
