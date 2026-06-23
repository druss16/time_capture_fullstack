"""READ-ONLY. Find the method that reclassifies a single block through the
classification service, so the cleanup calls the real code path."""
import subprocess, os
base = "/app/tracker" if os.path.isdir("/app/tracker") else "tracker"
def grep(p, f="services/classification_service.py"):
    try: return subprocess.run(["grep","-n",p,base+"/"+f],
                               capture_output=True,text=True,timeout=20).stdout.strip()
    except Exception as e: return f"(err {e})"

print("Public entrypoints on ClassificationService (def classify / reclassify / run):")
for pat in ("def classify","def reclassify","def run","def process_block","def apply","def finalize","def classify_block"):
    h=grep(pat)
    if h: print(f"  {h}")
print("="*70)
# How does the existing reclassify command call it?
print("How management/commands/reclassify_captured.py invokes it:")
try:
    print(subprocess.run(["grep","-n","ClassificationService\\|\\.classify\\|reclassif\\|recommit\\|apply\\|for block",
                          base+"/management/commands/reclassify_captured.py"],
                         capture_output=True,text=True,timeout=20).stdout.strip()[:1500])
except Exception as e: print(e)
print("="*70)
# Signature of the main classify entry + how it persists
print("Class def + __init__ signature:")
print(grep("class ClassificationService"))
print(grep("def __init__"))
print("="*70)
