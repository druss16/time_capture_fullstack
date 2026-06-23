"""READ-ONLY. Our FIX-6 sets recommended_state='committed' (~line 4292) but the
final decision is 'proposed'. Find what runs AFTER 4292 and overrides it."""
import subprocess, os
base = "/app/tracker" if os.path.isdir("/app/tracker") else "tracker"
f = base+"/services/classification_service.py"
def sed(a,b):
    try: return subprocess.run(["sed","-n",f"{a},{b}p",f],capture_output=True,text=True,timeout=20).stdout
    except Exception as e: return f"(err {e})"

# All recommended_state assignments with line numbers
print("All 'recommended_state =' assignments (line numbers):")
out = subprocess.run(["grep","-n","recommended_state =",f],capture_output=True,text=True).stdout
print(out)
print("="*72)
# The classify() method spans where? find its end so we know what runs after 4292
print("Where does classify() end / what's the next def after 4292?")
out2 = subprocess.run(["grep","-n","    def ",f],capture_output=True,text=True).stdout
for line in out2.splitlines():
    ln = int(line.split(":")[0])
    if 4290 < ln < 4520:
        print("  next def after our edit:", line)
        break
print("="*72)
# Show lines 4300-4360 — what runs right after our FIX-6 edit inside classify()
print("Lines 4300–4360 (what runs right AFTER our committed-setting edit):")
print(sed(4300,4360))
print("="*72)
