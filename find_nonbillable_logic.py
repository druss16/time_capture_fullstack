import subprocess, os
base = "/app/tracker" if os.path.isdir("/app/tracker") else "tracker"
def grep(p, ctx=0):
    try:
        a=["grep","-rn"]+(["-A",str(ctx)] if ctx else [])+[p,base+"/services/classification_service.py"]
        return subprocess.run(a,capture_output=True,text=True,timeout=20).stdout.strip()
    except Exception as e: return f"(err {e})"

print("="*74)
print("Where non-billable / Personal gets decided in classification_service.py:")
print("="*74)
for pat in ("non.billable","is_billable","Personal","NON_BILLABLE","mark_non","overhead","Inbox","inbox"):
    h = grep(pat)
    if h:
        print(f"\n[{pat}]\n{h[:1200]}")
print("="*74)
# Is there an existing 'always non-billable apps/titles' list anywhere?
print("Existing overhead/non-billable signature lists in the codebase:")
def grep_all(p):
    try: return subprocess.run(["grep","-rln",p,base],capture_output=True,text=True,timeout=20).stdout.strip()
    except Exception as e: return f"(err {e})"
for pat in ("NON_BILLABLE","OVERHEAD","PERSONAL_APPS","always_non","ALWAYS_NON"):
    h=grep_all(pat)
    if h: print(f"  [{pat}] {h}")
print("="*74)
