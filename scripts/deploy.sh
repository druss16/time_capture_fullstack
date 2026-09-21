#!/usr/bin/env bash
#
# Trigger a Render deploy via deploy hooks.
#
# Deploy hooks are deliberately the weakest credential that does this job: a
# hook can start a deploy of one service and nothing else. It cannot read or
# rewrite environment variables, which on this account hold the Neon
# DATABASE_URL, the QuickBooks / Xero / Clio OAuth secrets and SendGrid. An
# account API key could do all of that, so we do not keep one on disk.
#
# The hooks themselves are secrets — anyone holding one can redeploy. They
# live OUTSIDE the repo, in a file only you can read:
#
#   mkdir -p ~/.config/render && chmod 700 ~/.config/render
#   cat > ~/.config/render/hooks.env <<'EOF'
#   RENDER_HOOK_API=https://api.render.com/deploy/srv-xxxxx?key=yyyyy
#   RENDER_HOOK_WEB=https://api.render.com/deploy/srv-zzzzz?key=wwwww
#   EOF
#   chmod 600 ~/.config/render/hooks.env
#
# Each URL comes from: Render dashboard -> the service -> Settings -> Deploy Hook.
#
# Usage:
#   scripts/deploy.sh            # deploy both services
#   scripts/deploy.sh api        # API only
#   scripts/deploy.sh web        # frontend only
#
# Note that Render already auto-deploys on every push to main. This script is
# for the cases that bypasses: redeploying without a commit, or re-running a
# build that failed for a reason outside the code.

set -euo pipefail

HOOKS="${RENDER_HOOKS_FILE:-$HOME/.config/render/hooks.env}"

if [[ ! -f "$HOOKS" ]]; then
  echo "No hooks file at $HOOKS" >&2
  echo "See the comment at the top of this script for how to create it." >&2
  exit 1
fi

# Refuse a world- or group-readable secrets file rather than quietly using it.
perms=$(stat -f '%OLp' "$HOOKS" 2>/dev/null || stat -c '%a' "$HOOKS")
if [[ "$perms" != "600" && "$perms" != "400" ]]; then
  echo "$HOOKS is mode $perms; it holds deploy secrets. Run: chmod 600 $HOOKS" >&2
  exit 1
fi

# shellcheck disable=SC1090
source "$HOOKS"

target="${1:-both}"
case "$target" in
  api|web|both) ;;
  *) echo "usage: $0 [api|web|both]" >&2; exit 2 ;;
esac

fire() {
  local name="$1" url="${2:-}"
  if [[ -z "$url" ]]; then
    echo "  $name: no hook configured, skipping"
    return 0
  fi
  # --fail so a 4xx is an error, and never print the URL: it contains the key.
  local code
  code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$url") || true
  if [[ "$code" == "200" || "$code" == "201" ]]; then
    echo "  $name: deploy triggered (HTTP $code)"
  else
    echo "  $name: FAILED (HTTP $code)" >&2
    return 1
  fi
}

echo "Triggering Render deploy(s) from $(git rev-parse --short HEAD) on $(git rev-parse --abbrev-ref HEAD):"

# Attempt every requested service even if an earlier one fails — a half-deployed
# pair is worth knowing about, and skipping the frontend because the API hook
# 500'd would hide that.
rc=0
[[ "$target" == "api" || "$target" == "both" ]] && { fire "api" "${RENDER_HOOK_API:-}" || rc=1; }
[[ "$target" == "web" || "$target" == "both" ]] && { fire "web" "${RENDER_HOOK_WEB:-}" || rc=1; }

echo
echo "A hook returns 200 as soon as the deploy is QUEUED — it does not report"
echo "whether the build succeeded. Watch it in the Render dashboard, or verify"
echo "the result by probing production once it settles."

exit "$rc"
