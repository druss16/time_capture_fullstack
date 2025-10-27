# tracker/views.py (near your compactor helpers)
def _merge_ctx(cur: dict, e: RawEvent):
    ctx = getattr(e, "ctx", None) or {}
    if not ctx:
        return

    # Ensure nested dict exists
    cur.setdefault("hints", {})

    # Browser
    if "browser" in ctx:
        b = ctx["browser"]
        cur["hints"]["browser_origin"] = b.get("origin")
        cur["hints"]["browser_pathname"] = b.get("pathname")
        if b.get("jira_key"):
            cur["hints"]["jira_key"] = b["jira_key"]
        if b.get("github_repo"):
            cur["hints"]["github_repo"] = b["github_repo"]
        if b.get("github_pr"):
            cur["hints"]["github_pr"] = b["github_pr"]

    # VS Code
    if "vscode" in ctx:
        v = ctx["vscode"]
        cur["hints"]["repo_root"]   = v.get("repo_root")
        cur["hints"]["workspace"]   = v.get("workspace")
        cur["hints"]["rel_file"]    = v.get("rel_file")
        cur["hints"]["branch"]      = v.get("branch")
        cur["hints"]["remote"]      = v.get("remote")

    # Shell
    if "shell" in ctx:
        s = ctx["shell"]
        cur["hints"]["pwd"] = s.get("pwd")
        if s.get("branch"):
            cur["hints"]["branch"] = s["branch"]
