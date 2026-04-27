#!/usr/bin/env bash
# scripts/security-scan-local.sh
#
# Run the full security scan suite locally before pushing.
# Usage:  ./scripts/security-scan-local.sh [path-to-repo-root]
#
# Designed for the TimeTracker stack: Django backend, React frontend,
# React Native mobile, Windows + Mac Python agents.

set -u  # error on undefined vars (don't set -e; we want all scans to run)

REPO_ROOT="${1:-$(pwd)}"
cd "$REPO_ROOT" || exit 1

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

REPORT_DIR="./security-reports/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$REPORT_DIR"

PASS=0
FAIL=0

step() { echo -e "\n${BLUE}==> $1${NC}"; }
ok()   { echo -e "${GREEN}    PASS${NC}"; PASS=$((PASS+1)); }
bad()  { echo -e "${RED}    FAIL — see $1${NC}"; FAIL=$((FAIL+1)); }
warn() { echo -e "${YELLOW}    WARN — see $1${NC}"; }

# ---------------------------------------------------------------------------
# 0. Tool installation check
# ---------------------------------------------------------------------------
step "Checking required tools"
MISSING=()
for tool in python3 pip node npm git; do
  command -v "$tool" >/dev/null 2>&1 || MISSING+=("$tool")
done
if [ ${#MISSING[@]} -gt 0 ]; then
  echo -e "${RED}Missing core tools: ${MISSING[*]}${NC}"
  exit 1
fi

# Install scanners if missing (idempotent)
pip install --quiet --upgrade bandit[toml] pip-audit semgrep gitleaks 2>/dev/null || true
# gitleaks via pip is the python wrapper; the binary is preferred:
if ! command -v gitleaks >/dev/null 2>&1; then
  echo -e "${YELLOW}gitleaks binary not found. Install via: brew install gitleaks${NC}"
  echo -e "${YELLOW}                              or:    https://github.com/gitleaks/gitleaks/releases${NC}"
fi

# ---------------------------------------------------------------------------
# 1. Secret scan - HIGHEST PRIORITY for you (Stripe, QuickBooks, DeviceKey, MAVOPS_ADMIN_SECRET)
# ---------------------------------------------------------------------------
step "1/6  Scanning git history for leaked secrets (gitleaks)"
if command -v gitleaks >/dev/null 2>&1; then
  gitleaks detect --source . --report-path "$REPORT_DIR/gitleaks.json" --report-format json --no-banner \
    && ok || bad "$REPORT_DIR/gitleaks.json"
else
  warn "gitleaks not installed - SKIPPED"
fi

# ---------------------------------------------------------------------------
# 2. Python SAST - Django backend + agent code
# ---------------------------------------------------------------------------
step "2/6  Python static analysis (bandit) — Django + agents"
bandit -r . \
  -x ./venv,./.venv,./node_modules,./tests,./test,./migrations,./build,./dist,./security-reports \
  -ll \
  -f json \
  -o "$REPORT_DIR/bandit.json" 2>/dev/null
BANDIT_ISSUES=$(python3 -c "import json; d=json.load(open('$REPORT_DIR/bandit.json')); print(len(d.get('results',[])))" 2>/dev/null || echo "?")
echo "    Found: $BANDIT_ISSUES medium+ severity issues"
[ "$BANDIT_ISSUES" = "0" ] && ok || warn "$REPORT_DIR/bandit.json"

# ---------------------------------------------------------------------------
# 3. Python dependency CVEs
# ---------------------------------------------------------------------------
step "3/6  Python dependency CVEs (pip-audit)"
PIP_FAIL=0
for req in requirements.txt requirements-prod.txt requirements-dev.txt agent/requirements.txt; do
  if [ -f "$req" ]; then
    echo "    Auditing $req"
    pip-audit -r "$req" --format json --output "$REPORT_DIR/pip-audit-$(basename $req .txt).json" 2>/dev/null || PIP_FAIL=1
  fi
done
[ $PIP_FAIL -eq 0 ] && ok || bad "$REPORT_DIR/pip-audit-*.json"

# ---------------------------------------------------------------------------
# 4. JS/TS dependency CVEs
# ---------------------------------------------------------------------------
step "4/6  JS/TS dependency CVEs (npm audit)"
NPM_FAIL=0
# Auto-detect every directory that contains a package.json (excluding node_modules)
while IFS= read -r pkg; do
  dir=$(dirname "$pkg")
  echo "    Auditing $dir"
  (cd "$dir" && npm audit --audit-level=high --json > "$REPO_ROOT/$REPORT_DIR/npm-audit-$(echo $dir | tr '/' '_').json" 2>/dev/null) || NPM_FAIL=1
done < <(find . -name package.json -not -path '*/node_modules/*' -not -path './security-reports/*')
[ $NPM_FAIL -eq 0 ] && ok || warn "$REPORT_DIR/npm-audit-*.json"

# ---------------------------------------------------------------------------
# 5. Semgrep multi-language SAST
# ---------------------------------------------------------------------------
step "5/6  Semgrep SAST (Django + React + OWASP Top 10 + Secrets)"
semgrep scan \
  --config=p/django \
  --config=p/react \
  --config=p/owasp-top-ten \
  --config=p/secrets \
  --severity=ERROR --severity=WARNING \
  --json -o "$REPORT_DIR/semgrep.json" \
  --quiet 2>/dev/null
SEMGREP_ISSUES=$(python3 -c "import json; d=json.load(open('$REPORT_DIR/semgrep.json')); print(len(d.get('results',[])))" 2>/dev/null || echo "?")
echo "    Found: $SEMGREP_ISSUES issues"
[ "$SEMGREP_ISSUES" = "0" ] && ok || warn "$REPORT_DIR/semgrep.json"

# ---------------------------------------------------------------------------
# 6. Multi-tenant isolation audit (TimeTracker-specific)
# Custom grep for org_id leaks - the failure mode that would end the company
# ---------------------------------------------------------------------------
step "6/6  Multi-tenant isolation audit (TimeTracker-specific)"
ISO_FILE="$REPORT_DIR/multitenancy-audit.txt"
{
  echo "=== Queries that may not filter by org_id ==="
  echo "Look for .objects.filter() / .objects.get() WITHOUT an org/organization filter:"
  echo
  grep -rn --include='*.py' \
    -E '\.objects\.(filter|get|all)\(' . \
    --exclude-dir=venv --exclude-dir=.venv --exclude-dir=node_modules \
    --exclude-dir=migrations --exclude-dir=security-reports \
    | grep -v -E '(org|organization|Org|Organization|tenant)' \
    | head -100
  echo
  echo "=== Direct usage of MAVOPS_ADMIN_SECRET ==="
  grep -rn 'MAVOPS_ADMIN_SECRET' . \
    --exclude-dir=venv --exclude-dir=.venv --exclude-dir=node_modules \
    --exclude-dir=security-reports
  echo
  echo "=== ?org_id= impersonation parameter handling ==="
  grep -rn 'org_id' . --include='*.py' \
    --exclude-dir=venv --exclude-dir=.venv --exclude-dir=migrations \
    --exclude-dir=security-reports \
    | grep -iE '(request\.(GET|POST|query_params)|impersonat)' | head -50
  echo
  echo "=== Hardcoded org_ids (should be parameterized in production code) ==="
  grep -rn -E 'org_id\s*=\s*(17|21)\b' . --include='*.py' \
    --exclude-dir=venv --exclude-dir=tests --exclude-dir=security-reports
} > "$ISO_FILE"
echo "    Written to $ISO_FILE — review manually"
warn "$ISO_FILE"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo
echo "==============================================="
echo "  Scan complete"
echo "  Reports: $REPORT_DIR"
echo "  Passed: $PASS    Failed: $FAIL"
echo "==============================================="
[ $FAIL -gt 0 ] && exit 1 || exit 0
