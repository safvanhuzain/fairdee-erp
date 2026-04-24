"""
Local dev server: Flow UI + trigger Playwright desk smoke.

From repository root:
  pip install -r tools/vibe_server/requirements.txt
  playwright install chromium
  python tools/vibe_server/server.py

Django must be running separately (e.g. python manage.py runserver).

Optional: FAIRDEE_FLOW_PREVIEW_URL — default iframe / preview URL if 127.0.0.1 is not
reachable from your browser (e.g. http://host.docker.internal:8000/app/).
Optional: FAIRDEE_FLOW_SERVER_ORIGIN — base URL for handoff links (default http://127.0.0.1:8765).
Optional: FLOW_ENABLE_GITHUB_BUTTON=1 — enables “Create changes on GitHub” (git stash, branch from
origin/main or origin/master, commit changed paths, push, open GitHub compare).
Optional: FLOW_GITHUB_BASE_BRANCH — preferred base name (default: try main, then master).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from starlette.routing import Route

REPO_ROOT = Path(__file__).resolve().parents[2]
SMOKE_SCRIPT = Path(__file__).resolve().parent / "flow_playwright_smoke.py"


class FlowGitError(Exception):
    pass


def _git_run(
    args: list[str],
    cwd: Path,
    *,
    timeout: float = 180.0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _changed_paths(repo: Path) -> list[str]:
    paths: set[str] = set()
    r = _git_run(["diff", "--name-only", "HEAD"], repo, timeout=60.0)
    for line in (r.stdout or "").splitlines():
        t = line.strip()
        if t:
            paths.add(t)
    r = _git_run(["ls-files", "--others", "--exclude-standard"], repo, timeout=60.0)
    for line in (r.stdout or "").splitlines():
        t = line.strip()
        if t:
            paths.add(t)
    return sorted(paths)


def _github_compare_url(remote_url: str, base: str, head_branch: str) -> str | None:
    remote_url = remote_url.strip()
    m = re.search(
        r"(?:git@|https?://)github\.com[:/]([^/]+)/([^/\s]+?)(?:\.git)?\s*$",
        remote_url,
        re.I,
    )
    if not m:
        return None
    owner, repo = m.group(1), m.group(2)
    return f"https://github.com/{owner}/{repo}/compare/{base}...{head_branch}?expand=1"


def _safe_commit_message(raw: str) -> str:
    s = (raw or "").strip().replace("\x00", "")
    if not s:
        return "Flow: changes"
    line = s.split("\n", 1)[0].strip()
    return (line[:240] if line else "Flow: changes") or "Flow: changes"


def _resolve_origin_base(repo: Path) -> str:
    pref = (os.environ.get("FLOW_GITHUB_BASE_BRANCH") or "").strip()
    candidates = [b for b in (pref, "main", "master") if b]
    seen: list[str] = []
    for b in candidates:
        if b in seen:
            continue
        seen.append(b)
        r = _git_run(["rev-parse", f"origin/{b}"], repo, timeout=30.0)
        if r.returncode == 0:
            return b
    raise FlowGitError("Could not resolve origin base (need origin/main or origin/master; run git fetch origin)")


def _github_publish_sync(commit_message: str) -> dict[str, str | bool]:
    """Stash current changes to listed paths, branch from origin/<base>, pop, commit, push."""
    repo = REPO_ROOT
    r = _git_run(["rev-parse", "--is-inside-work-tree"], repo, timeout=10.0)
    if r.returncode != 0 or (r.stdout or "").strip() != "true":
        raise FlowGitError("Not a git checkout (expected a clone with origin)")

    fr = _git_run(["fetch", "origin"], repo, timeout=180.0)
    if fr.returncode != 0:
        raise FlowGitError((fr.stderr or fr.stdout or "git fetch origin failed").strip()[:800])

    base = _resolve_origin_base(repo)
    remote_r = _git_run(["remote", "get-url", "origin"], repo)
    if remote_r.returncode != 0:
        raise FlowGitError("No git remote named origin")
    remote_url = (remote_r.stdout or "").strip()

    paths = _changed_paths(repo)
    if not paths:
        raise FlowGitError("No modified or untracked files to include")

    branch = f"flow/ui-{time.strftime('%Y%m%d')}-{secrets.token_hex(3)}"
    st = _git_run(
        ["stash", "push", "-u", "-m", "flow-github-publish", "--", *paths],
        repo,
        timeout=120.0,
    )
    if st.returncode != 0:
        raise FlowGitError((st.stderr or st.stdout or "git stash failed").strip()[:800])

    co = _git_run(["checkout", "-B", branch, f"origin/{base}"], repo, timeout=60.0)
    if co.returncode != 0:
        pop0 = _git_run(["stash", "pop"], repo, timeout=60.0)
        msg = (co.stderr or co.stdout or "checkout failed").strip()[:800]
        if pop0.returncode != 0:
            msg += " | stash pop also failed — check git status"
        raise FlowGitError(msg)

    pop = _git_run(["stash", "pop"], repo, timeout=120.0)
    if pop.returncode != 0:
        raise FlowGitError(
            (pop.stderr or pop.stdout or "stash pop failed (merge conflicts?)").strip()[:800]
            + " — run git stash list if you need to recover the stash entry.",
        )

    ad = _git_run(["add", "--"] + paths, repo, timeout=60.0)
    if ad.returncode != 0:
        raise FlowGitError((ad.stderr or ad.stdout or "git add failed").strip()[:800])

    dq = _git_run(["diff", "--cached", "--quiet"], repo, timeout=30.0)
    if dq.returncode == 0:
        raise FlowGitError("Nothing to commit (no diff vs index after applying changes)")

    cm = _git_run(["commit", "-m", commit_message], repo, timeout=60.0)
    if cm.returncode != 0:
        raise FlowGitError((cm.stderr or cm.stdout or "git commit failed").strip()[:800])

    pu = _git_run(["push", "-u", "origin", branch], repo, timeout=180.0)
    if pu.returncode != 0:
        raise FlowGitError((pu.stderr or pu.stdout or "git push failed").strip()[:800])

    open_url = _github_compare_url(remote_url, base, branch)
    return {
        "ok": True,
        "branch": branch,
        "base": base,
        "open_url": open_url or "",
        "remote": remote_url,
    }


# __FLOW_CONFIG_JSON__ replaced at runtime (repo path for handoff markdown).
_FLOW_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Fairdee · Flow</title>
  <style>
    :root { font-family: system-ui, sans-serif; background: #0f1419; color: #e6edf3; }
    * { box-sizing: border-box; }
    body { margin: 0; min-height: 100vh; }
    .flow-shell { display: flex; flex-direction: row; min-height: 100vh; }
    .left {
      flex: 0 0 min(28rem, 42vw);
      max-width: 32rem;
      padding: 1rem 1.1rem 1.5rem;
      overflow: auto;
      border-right: 1px solid #334155;
      background: #0f1419;
    }
    .right {
      flex: 1 1 auto;
      min-width: 0;
      display: flex;
      flex-direction: column;
      background: #111827;
    }
    .preview-toolbar {
      display: flex;
      align-items: center;
      gap: 0.5rem;
      padding: 0.45rem 0.65rem;
      border-bottom: 1px solid #334155;
      font-size: 0.8rem;
      color: #94a3b8;
    }
    .preview-toolbar input[type="url"] {
      flex: 1;
      min-width: 0;
      padding: 0.35rem 0.5rem;
      border-radius: 6px;
      border: 1px solid #334155;
      background: #0b1220;
      color: #e2e8f0;
    }
    .preview-toolbar button {
      margin: 0;
      padding: 0.35rem 0.65rem;
      font-size: 0.8rem;
    }
    .preview-toolbar a.preview-open-tab {
      color: #93c5fd;
      font-size: 0.8rem;
      white-space: nowrap;
    }
    .flow-after-smoke { margin-top: 0.5rem; }
    a.flow-return-btn {
      display: inline-block;
      margin-top: 0.35rem;
      padding: 0.5rem 0.95rem;
      border-radius: 8px;
      background: #059669;
      color: #fff !important;
      font-weight: 600;
      text-decoration: none;
    }
    a.flow-return-btn:hover { background: #047857; }
    iframe#preview {
      flex: 1;
      width: 100%;
      border: 0;
      background: #fff;
    }
    h1 { font-weight: 600; font-size: 1.2rem; margin: 0 0 0.35rem; }
    p, li { line-height: 1.45; color: #9fb0c3; font-size: 0.88rem; margin: 0.35rem 0; }
    code { background: #1b222c; padding: 0.1rem 0.3rem; border-radius: 4px; font-size: 0.85em; }
    button {
      margin-top: 0.65rem;
      padding: 0.5rem 0.9rem;
      border-radius: 8px;
      border: 0;
      background: #3b82f6;
      color: #fff;
      font-weight: 600;
      cursor: pointer;
    }
    button:disabled { opacity: 0.5; cursor: not-allowed; }
    #out { margin-top: 0.65rem; white-space: pre-wrap; font-size: 0.78rem; max-height: 12rem; overflow: auto; }
    .ok { color: #4ade80; }
    .err { color: #f87171; }
    .prompt-box {
      border: 1px solid #334155;
      border-radius: 8px;
      padding: 0.65rem 0.75rem;
      margin: 0.65rem 0;
      background: #111827;
    }
    .prompt-box h2 { font-size: 0.88rem; margin: 0 0 0.35rem; color: #e2e8f0; }
    .prompt-box p { margin: 0; font-size: 0.82rem; color: #94a3b8; }
    textarea#flow_prompt {
      width: 100%;
      min-height: 6rem;
      margin-top: 0.35rem;
      padding: 0.45rem;
      border-radius: 6px;
      border: 1px solid #334155;
      background: #0b1220;
      color: #e2e8f0;
      font-family: inherit;
      font-size: 0.88rem;
    }
    form.flow-fields { display: flex; flex-direction: column; gap: 0.4rem; margin-top: 0.45rem; }
    .hint { font-size: 0.75rem; color: #64748b; margin-top: 0.35rem; }
    .sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0; }
    .handoff-row { display: flex; flex-wrap: wrap; gap: 0.45rem; margin-top: 0.5rem; }
    .btn-handoff { margin-top: 0; font-size: 0.82rem; padding: 0.45rem 0.75rem; }
    button.btn-secondary { background: #334155; }
    button.btn-secondary:hover { background: #475569; }
    hr.sep { border: 0; border-top: 1px solid #334155; margin: 1rem 0; }
    h2.subhead { font-size: 0.95rem; margin: 0 0 0.35rem; color: #e2e8f0; }
    .handoff-box a { color: #93c5fd; }
    button.btn-github {
      margin-top: 0.5rem;
      background: #24292f;
      font-size: 0.85rem;
    }
    button.btn-github:hover:not(:disabled) { background: #1a1e24; }
  </style>
</head>
<body>
  <div class="flow-shell">
    <div class="left">
      <h1>Fairdee · Flow</h1>
      <p>Preview the desk, write <strong>Plain text</strong> for Cursor, then <strong>Handoff</strong>. Optional Playwright smoke below.</p>
      <section class="prompt-box" aria-labelledby="plain-text-h">
        <h2 id="plain-text-h">Plain text</h2>
        <p>Your change request only. Sent to smoke as <code>FAIRDEE_FLOW_PROMPT</code> when you run smoke.</p>
        <label for="flow_prompt" class="sr-only">Plain text change request</label>
        <textarea id="flow_prompt" name="flow_prompt" rows="7" placeholder="Describe the change you want in fairdee-erp…"></textarea>
      </section>
      <section class="prompt-box handoff-box" aria-labelledby="handoff-h">
        <h2 id="handoff-h">Handoff · Cursor / Engineering</h2>
        <p>Builds markdown (repo root + agent steps) and opens <a href="https://cursor.com" target="_blank" rel="noopener noreferrer">Cursor</a>’s prompt link. <strong>Engineering</strong> adds an extra checklist. GitHub branch/PR uses the button below when enabled.</p>
        <div class="handoff-row">
          <button type="button" class="btn-handoff" id="handoff_cursor">Handoff → Cursor</button>
          <button type="button" class="btn-handoff btn-secondary" id="handoff_engineering">Handoff → Engineering</button>
          <button type="button" class="btn-handoff btn-secondary" id="handoff_copy">Copy handoff markdown</button>
        </div>
        <p id="handoff_status" class="hint" style="min-height:1.15em;margin-top:0.45rem" role="status"></p>
      </section>
      <hr class="sep" aria-hidden="true" />
      <h2 class="subhead">GitHub</h2>
      <p class="hint">Branch from <code>origin</code> default branch, commit every file that differs from <code>HEAD</code> (including new untracked files under those paths), push, then open GitHub’s compare page. Enable with <code>FLOW_ENABLE_GITHUB_BUTTON=1</code> and restart Flow.</p>
      <button type="button" class="btn-github" id="github_publish" disabled>Create changes on GitHub</button>
      <p id="github_publish_status" class="hint" style="min-height:1em;margin-top:0.35rem" role="status"></p>
      <hr class="sep" aria-hidden="true" />
      <h2 class="subhead">Desk smoke (Playwright)</h2>
      <p class="hint">Workspace heading must read <strong>Hello User</strong>. Run Django on <code>http://127.0.0.1:8000</code> or set base URL below.</p>
      <ul style="padding-left:1.1rem;margin:0.5rem 0">
        <li><code>python manage.py runserver</code></li>
        <li><code>FAIRDEE_SMOKE_EMAIL</code> / <code>FAIRDEE_SMOKE_PASSWORD</code> or form</li>
      </ul>
      <p class="hint">Credentials are sent only to this localhost server as JSON.</p>
      <form class="flow-fields" id="flow-form" autocomplete="on">
        <input type="email" id="email" name="email" placeholder="Email" autocomplete="username" style="padding:0.4rem;border-radius:6px;border:1px solid #334155;background:#111827;color:#e2e8f0">
        <input type="password" id="password" name="password" placeholder="Password" autocomplete="current-password" style="padding:0.4rem;border-radius:6px;border:1px solid #334155;background:#111827;color:#e2e8f0">
        <input type="url" id="base" name="base" placeholder="Base URL (optional)" autocomplete="url" style="padding:0.4rem;border-radius:6px;border:1px solid #334155;background:#111827;color:#e2e8f0">
      </form>
      <button type="button" id="run">Run smoke</button>
      <div id="out"></div>
      <div id="after_smoke" class="flow-after-smoke" aria-live="polite"></div>
    </div>
    <div class="right">
      <div class="preview-toolbar">
        <span>Preview</span>
        <input type="url" id="preview_url" value="http://127.0.0.1:8000/app/" title="Django app URL">
        <button type="button" id="preview_reload" title="Reload iframe">Reload</button>
        <a class="preview-open-tab" id="open_preview_tab" href="http://127.0.0.1:8000/app/" target="_blank" rel="noopener noreferrer">Open in tab</a>
      </div>
      <iframe id="preview" title="Django app preview" src="about:blank"></iframe>
    </div>
  </div>
  <script type="application/json" id="flow-config">__FLOW_CONFIG_JSON__</script>
  <script>
    const FLOW_CFG = JSON.parse(document.getElementById("flow-config").textContent);
    const out = document.getElementById("out");
    const btn = document.getElementById("run");
    const preview = document.getElementById("preview");
    const previewUrl = document.getElementById("preview_url");
    const openPreviewTab = document.getElementById("open_preview_tab");
    const handoffStatus = document.getElementById("handoff_status");
    const githubBtn = document.getElementById("github_publish");
    const githubStatus = document.getElementById("github_publish_status");
    if (FLOW_CFG.githubButtonEnabled) {
      githubBtn.disabled = false;
      githubStatus.textContent = "";
    } else {
      githubBtn.disabled = true;
      githubStatus.textContent = "Set FLOW_ENABLE_GITHUB_BUTTON=1 and restart Flow to enable.";
    }
    const defaultPreview = (FLOW_CFG.defaultPreviewUrl || "").trim() || "http://127.0.0.1:8000/app/";
    previewUrl.value = defaultPreview;
    preview.src = defaultPreview;
    function previewTargetHref() {
      const u = (previewUrl.value || "").trim();
      return u || "http://127.0.0.1:8000/app/";
    }
    function syncOpenTabHref() {
      openPreviewTab.href = previewTargetHref();
    }
    previewUrl.addEventListener("input", syncOpenTabHref);
    syncOpenTabHref();
    function buildHandoffMarkdown(engineering) {
      const prompt = (document.getElementById("flow_prompt").value || "").trim();
      const repo = FLOW_CFG.repoRoot || "";
      const lines = [
        "# Change request (paste into Cursor chat)",
        "",
        "**Repository root:** `" + repo + "`",
        "",
        "## Plain-language request",
        prompt || "(add your plain text above)",
        "",
        "## Instructions for the agent",
        "1. Implement the request in this repo; prefer minimal, focused diffs.",
        "2. Run checks locally (e.g. `python manage.py check`, relevant tests).",
        "3. Run the desk Playwright smoke from the repo root (Django must be up; set FAIRDEE_SMOKE_EMAIL / FAIRDEE_SMOKE_PASSWORD if needed): `python tools/vibe_server/flow_playwright_smoke.py`",
        "4. Do **not** push branches, open PRs, or use GitHub automation from Cursor unless the user explicitly asks (they may use Flow’s **Create changes on GitHub** button themselves).",
      ];
      if (engineering) {
        lines.push(
          "",
          "## Engineering checklist",
          "- [ ] Migrations reviewed (if any)",
          "- [ ] No secrets or local-only files in diff",
          "- [ ] Desk smoke passing",
        );
      }
      return lines.join(String.fromCharCode(10));
    }
    function openCursorHandoff(engineering) {
      const md = buildHandoffMarkdown(engineering);
      const url = "https://cursor.com/link/prompt?text=" + encodeURIComponent(md);
      window.open(url, "_blank", "noopener,noreferrer");
      handoffStatus.textContent = engineering ? "Opened Engineering handoff in a new tab." : "Opened Cursor handoff in a new tab.";
    }
    document.getElementById("handoff_cursor").addEventListener("click", () => openCursorHandoff(false));
    document.getElementById("handoff_engineering").addEventListener("click", () => openCursorHandoff(true));
    document.getElementById("handoff_copy").addEventListener("click", async () => {
      const md = buildHandoffMarkdown(false);
      try {
        await navigator.clipboard.writeText(md);
        handoffStatus.textContent = "Copied Cursor handoff markdown to clipboard.";
      } catch (e) {
        handoffStatus.textContent = "Copy failed — select Plain text and copy manually.";
      }
    });
    githubBtn.addEventListener("click", async () => {
      if (!FLOW_CFG.githubButtonEnabled) return;
      githubStatus.textContent = "Working…";
      githubBtn.disabled = true;
      out.textContent = "";
      try {
        const msg = (document.getElementById("flow_prompt").value || "").split("\\n")[0].trim() || "Flow: changes";
        const r = await fetch("/flow/github-publish", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: msg }),
        });
        const data = await readResponse(r);
        if (data.ok && data.open_url) {
          window.location.href = data.open_url;
          return;
        }
        out.className = "err";
        out.textContent = JSON.stringify(data, null, 2);
        githubStatus.textContent = data.error || "Failed";
      } catch (e) {
        out.className = "err";
        out.textContent = String(e);
        githubStatus.textContent = "Request failed";
      } finally {
        if (FLOW_CFG.githubButtonEnabled) githubBtn.disabled = false;
      }
    });
    document.getElementById("preview_reload").addEventListener("click", () => {
      const u = previewTargetHref();
      preview.src = u;
      syncOpenTabHref();
    });
    async function readResponse(r) {
      const ct = r.headers.get("content-type") || "";
      if (ct.includes("application/json")) {
        return await r.json();
      }
      return { ok: r.ok, raw: await r.text() };
    }
    btn.addEventListener("click", async () => {
      out.textContent = "";
      document.getElementById("after_smoke").innerHTML = "";
      btn.disabled = true;
      try {
        const email = document.getElementById("email").value.trim();
        const password = document.getElementById("password").value;
        const base_url = document.getElementById("base").value.trim();
        const prompt = document.getElementById("flow_prompt").value.trim();
        const payload = {};
        if (email) payload.email = email;
        if (password) payload.password = password;
        if (base_url) payload.base_url = base_url;
        if (prompt) payload.prompt = prompt;
        const r = await fetch("/flow/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await readResponse(r);
        out.className = r.ok ? "ok" : "err";
        out.textContent = JSON.stringify(data, null, 2);
        const after = document.getElementById("after_smoke");
        after.innerHTML = "";
        if (r.ok && data && data.ok === true) {
          const flowUrl = FLOW_CFG.flowPageUrl || (window.location.origin + "/flow");
          const wrap = document.createElement("div");
          const a = document.createElement("a");
          a.href = flowUrl;
          a.className = "flow-return-btn";
          a.textContent = "Back to Flow";
          wrap.appendChild(a);
          const hint = document.createElement("p");
          hint.className = "hint";
          hint.style.marginTop = "0.45rem";
          hint.textContent = "Opens this Flow page again so you can refresh the desk preview or run smoke once more.";
          wrap.appendChild(hint);
          after.appendChild(wrap);
        }
      } catch (e) {
        out.className = "err";
        out.textContent = String(e);
        const after = document.getElementById("after_smoke");
        if (after) after.innerHTML = "";
      } finally {
        btn.disabled = false;
      }
    });
  </script>
</body>
</html>"""


def _flow_page_html() -> str:
    default_preview = (os.environ.get("FAIRDEE_FLOW_PREVIEW_URL") or "http://127.0.0.1:8000/app/").strip()
    if not default_preview:
        default_preview = "http://127.0.0.1:8000/app/"
    flow_origin = (os.environ.get("FAIRDEE_FLOW_SERVER_ORIGIN") or "http://127.0.0.1:8765").strip().rstrip("/")
    flow_page_url = f"{flow_origin}/flow"
    cfg = json.dumps(
        {
            "repoRoot": str(REPO_ROOT),
            "defaultPreviewUrl": default_preview,
            "flowPageUrl": flow_page_url,
            "githubButtonEnabled": os.environ.get("FLOW_ENABLE_GITHUB_BUTTON", "").lower()
            in ("1", "true", "yes"),
        },
    ).replace("<", "\\u003c")
    return _FLOW_HTML_TEMPLATE.replace("__FLOW_CONFIG_JSON__", cfg)


async def flow_page(_: Request) -> HTMLResponse:
    return HTMLResponse(
        _flow_page_html(),
        headers={"Cache-Control": "no-store, max-age=0"},
    )


async def flow_github_publish(request: Request) -> JSONResponse:
    if os.environ.get("FLOW_ENABLE_GITHUB_BUTTON", "").lower() not in ("1", "true", "yes"):
        return JSONResponse(
            {
                "ok": False,
                "error": "disabled",
                "hint": "Set environment variable FLOW_ENABLE_GITHUB_BUTTON=1 and restart the Flow server.",
            },
            status_code=403,
        )
    body: dict = {}
    ct = request.headers.get("content-type", "")
    if "application/json" in ct.lower():
        try:
            body = await request.json()
            if not isinstance(body, dict):
                body = {}
        except Exception:
            body = {}
    message = _safe_commit_message(str(body.get("message") or ""))

    def _run() -> dict[str, str | bool]:
        try:
            return _github_publish_sync(message)
        except FlowGitError as e:
            return {"ok": False, "error": str(e)}

    result = await asyncio.to_thread(_run)
    if not result.get("ok"):
        return JSONResponse(result, status_code=400)
    return JSONResponse(result)


async def flow_run(request: Request) -> JSONResponse:
    child_env = os.environ.copy()
    ct = request.headers.get("content-type", "")
    if "application/json" in ct.lower():
        try:
            body = await request.json()
            if isinstance(body, dict):
                if body.get("email"):
                    child_env["FAIRDEE_SMOKE_EMAIL"] = str(body["email"]).strip()
                # Only override password when a non-empty string is sent (avoid wiping env).
                pw = body.get("password")
                if isinstance(pw, str) and pw != "":
                    child_env["FAIRDEE_SMOKE_PASSWORD"] = pw
                if body.get("base_url"):
                    child_env["FAIRDEE_BASE_URL"] = str(body["base_url"]).strip().rstrip("/")
                pr = body.get("prompt")
                if isinstance(pr, str) and pr.strip():
                    child_env["FAIRDEE_FLOW_PROMPT"] = pr.strip()
        except Exception:
            pass

    email_ok = bool((child_env.get("FAIRDEE_SMOKE_EMAIL") or "").strip())
    password_ok = bool(child_env.get("FAIRDEE_SMOKE_PASSWORD"))
    if not email_ok or not password_ok:
        return JSONResponse(
            {
                "ok": False,
                "error": "missing_credentials",
                "hint": "Set FAIRDEE_SMOKE_EMAIL and FAIRDEE_SMOKE_PASSWORD on the server, or send email and password in the JSON body.",
            },
            status_code=400,
        )

    def _run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SMOKE_SCRIPT)],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=120,
            env=child_env,
        )

    try:
        proc = await asyncio.to_thread(_run)
    except subprocess.TimeoutExpired:
        return JSONResponse(
            {"ok": False, "error": "timeout", "stdout": "", "stderr": ""},
            status_code=500,
        )
    payload = {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": proc.stdout or "",
        "stderr": proc.stderr or "",
    }
    status = 200 if proc.returncode == 0 else 500
    return JSONResponse(payload, status_code=status)


async def health(_: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")


async def root(_: Request) -> RedirectResponse:
    return RedirectResponse(url="/flow", status_code=302)


routes = [
    Route("/", endpoint=root, methods=["GET"]),
    Route("/flow", endpoint=flow_page, methods=["GET"]),
    Route("/flow/github-publish", endpoint=flow_github_publish, methods=["POST"]),
    Route("/flow/run", endpoint=flow_run, methods=["POST"]),
    Route("/health", endpoint=health, methods=["GET"]),
]

app = Starlette(routes=routes)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info")
