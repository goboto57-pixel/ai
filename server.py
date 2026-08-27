#!/usr/bin/env python3
"""Misrtal Pro — full agentic coding backend (Claude Code style)."""

import os, json, re, subprocess, uuid, mimetypes
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import httpx

load_dotenv()

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "").strip()
MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "codestral-latest")
MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"
WORKSPACE = Path(__file__).parent / "workspace"
WORKSPACE.mkdir(exist_ok=True)
MAX_ROUNDS = 14

# Cloudinary
CN = os.getenv("CLOUDINARY_CLOUD_NAME", "").strip()
CK = os.getenv("CLOUDINARY_API_KEY", "").strip()
CS = os.getenv("CLOUDINARY_API_SECRET", "").strip()
CLOUD_ON = bool(CN and CK and CS)
if CLOUD_ON:
    import cloudinary, cloudinary.uploader
    cloudinary.config(cloud_name=CN, api_key=CK, api_secret=CS, secure=True)

app = FastAPI(title="Misrtal Pro")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ---------- FS tools ----------
def safe_path(rel: str) -> Path:
    p = (WORKSPACE / rel.lstrip("/\\")).resolve()
    if not str(p).startswith(str(WORKSPACE.resolve())):
        raise ValueError("path escape")
    return p

def tool_list_dir(path: str = ".") -> str:
    p = safe_path(path)
    if not p.exists():
        return f"not found: {path}"
    lines = []
    for item in sorted(p.iterdir()):
        if item.name.startswith(".") and item.name not in (".env.example",):
            continue
        kind = "dir " if item.is_dir() else "file"
        sz = item.stat().st_size if item.is_file() else 0
        lines.append(f"{kind} {sz:>8}  {item.name}")
    return "\n".join(lines) or "(empty)"

def tool_read_file(path: str) -> str:
    p = safe_path(path)
    if not p.exists():
        return f"not found: {path}"
    if p.is_dir():
        return f"{path} is directory"
    data = p.read_bytes()
    # binary?
    if b"\x00" in data[:1024]:
        return f"[binary file {len(data)} bytes — cannot display as text]"
    text = data.decode("utf-8", errors="replace")
    if len(text) > 120_000:
        return text[:120_000] + "\n\n...[truncated]"
    return text

def cloud_upload(rel: str) -> str:
    if not CLOUD_ON:
        return ""
    try:
        p = safe_path(rel)
        if not p.is_file():
            return ""
        pid = "misrtal/" + re.sub(r"[^a-zA-Z0-9_\-./]", "_", rel.replace("\\", "/"))
        res = cloudinary.uploader.upload(str(p), resource_type="raw", public_id=pid, overwrite=True, invalidate=True)
        return res.get("secure_url") or res.get("url") or ""
    except Exception:
        return ""

def tool_write_file(path: str, content: str) -> str:
    p = safe_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    before = p.read_text("utf-8", errors="replace") if p.exists() else ""
    p.write_text(content, encoding="utf-8")
    url = cloud_upload(path.replace("\\", "/"))
    return json.dumps({
        "ok": True, "path": path,
        "lines_before": before.count("\n") + (1 if before else 0),
        "lines_after": content.count("\n") + 1,
        "bytes": len(content.encode()),
        "cloud_url": url,
        "preview": content[:2000],
    })

def tool_edit_file(path: str, old_str: str, new_str: str) -> str:
    p = safe_path(path)
    if not p.exists():
        return f"not found: {path}"
    text = p.read_text("utf-8", errors="replace")
    if old_str not in text:
        return f"old_str not found in {path}"
    new_text = text.replace(old_str, new_str, 1)
    p.write_text(new_text, encoding="utf-8")
    url = cloud_upload(path.replace("\\", "/"))
    # simple diff stats
    return json.dumps({
        "ok": True, "path": path, "replacements": 1,
        "cloud_url": url,
        "preview": new_text[:2000],
        "lines_after": new_text.count("\n") + 1,
    })

def tool_run_bash(command: str) -> str:
    banned = ["rm -rf /", "curl ", "wget ", "ssh ", "sudo ", "mkfs", "> /etc", "dd if="]
    low = command.lower()
    for b in banned:
        if b in low:
            return f"blocked: {b}"
    before = {str(f.relative_to(WORKSPACE)): f.stat().st_mtime
              for f in WORKSPACE.rglob("*") if f.is_file()}
    try:
        r = subprocess.run(command, shell=True, cwd=str(WORKSPACE),
                           capture_output=True, text=True, timeout=30,
                           env={**os.environ, "HOME": str(WORKSPACE)})
        out = (r.stdout or "") + (r.stderr or "")
        # upload changed
        urls = []
        for f in WORKSPACE.rglob("*"):
            if not f.is_file():
                continue
            rel = str(f.relative_to(WORKSPACE)).replace("\\", "/")
            mt = f.stat().st_mtime
            if rel not in before or mt > before.get(rel, 0):
                u = cloud_upload(rel)
                if u:
                    urls.append(f"{rel} → {u}")
        extra = ("\n[cloud]\n" + "\n".join(urls)) if urls else ""
        return f"exit={r.returncode}\n{out[:22000]}{extra}"
    except subprocess.TimeoutExpired:
        return "timeout 30s"
    except Exception as e:
        return f"error: {e}"

TOOLS = [
    {"type": "function", "function": {"name": "list_dir", "description": "List directory", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "read_file", "description": "Read file contents", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "write_file", "description": "Create/overwrite file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
    {"type": "function", "function": {"name": "edit_file", "description": "Replace exact string once in file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "old_str": {"type": "string"}, "new_str": {"type": "string"}}, "required": ["path", "old_str", "new_str"]}}},
    {"type": "function", "function": {"name": "run_bash", "description": "Shell in workspace (no network)", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
]
IMPL = {
    "list_dir": lambda a: tool_list_dir(a.get("path", ".")),
    "read_file": lambda a: tool_read_file(a["path"]),
    "write_file": lambda a: tool_write_file(a["path"], a["content"]),
    "edit_file": lambda a: tool_edit_file(a["path"], a["old_str"], a["new_str"]),
    "run_bash": lambda a: tool_run_bash(a["command"]),
}

SYSTEM = """You are Misrtal — an agentic coding assistant like Claude Code / Cursor agent, powered by Codestral.
Workspace is a sandbox. Tools: list_dir, read_file, write_file, edit_file, run_bash.

CRITICAL RULES:
1. FIRST message must be ONLY valid JSON: {"plan":["step1","step2",...],"summary":"one line"}
2. After user says PLAN_ACCEPTED — execute with tools. Think step by step.
3. Prefer edit_file for small changes, write_file for new/full files.
4. After each meaningful change, briefly say what you did.
5. When done: say DONE and list created/changed files.
6. Match user language (Russian/English).
7. Never invent tool results. Write working code.
"""

sessions: Dict[str, dict] = {}

class StartReq(BaseModel):
    message: str
    session_id: Optional[str] = None

class RunReq(BaseModel):
    session_id: str

async def mistral(messages, tools=None, tool_choice="auto"):
    if not MISTRAL_API_KEY:
        raise HTTPException(400, "MISTRAL_API_KEY missing")
    body = {"model": MISTRAL_MODEL, "messages": messages, "temperature": 0.15, "max_tokens": 8192}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = tool_choice
    headers = {"Authorization": f"Bearer {MISTRAL_API_KEY}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=100.0) as c:
        r = await c.post(MISTRAL_URL, json=body, headers=headers)
        if r.status_code != 200:
            raise HTTPException(r.status_code, r.text[:500])
        return r.json()

def sse(ev: str, data: Any) -> str:
    payload = json.dumps(data, ensure_ascii=False) if not isinstance(data, str) else data
    return f"event: {ev}\ndata: {payload}\n\n"

@app.get("/api/status")
def status():
    return {
        "has_key": bool(MISTRAL_API_KEY),
        "model": MISTRAL_MODEL,
        "cloud": CLOUD_ON,
        "workspace": str(WORKSPACE),
    }

@app.post("/api/start")
async def start(req: StartReq):
    sid = req.session_id or str(uuid.uuid4())
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": req.message}]
    try:
        resp = await mistral(messages)
        content = resp["choices"][0]["message"]["content"] or ""
    except HTTPException as e:
        if "missing" in str(e.detail).lower() or e.status_code == 400:
            plan = ["Разобрать задачу", "Создать файлы", "Написать код", "Проверить"]
            sessions[sid] = {"messages": messages, "plan": plan, "status": "plan_ready", "demo": True}
            return {"session_id": sid, "plan": plan, "summary": "demo", "demo": True}
        raise
    plan, summary = [], ""
    try:
        s, e = content.find("{"), content.rfind("}") + 1
        if s >= 0:
            obj = json.loads(content[s:e])
            plan = obj.get("plan", [])
            summary = obj.get("summary", "")
    except Exception:
        plan = [l.strip("-• ").strip() for l in content.splitlines() if l.strip()][:10]
    if not plan:
        plan = ["Выполнить задачу"]
    sessions[sid] = {
        "messages": messages + [{"role": "assistant", "content": content}],
        "plan": plan, "status": "plan_ready", "demo": False, "summary": summary,
    }
    return {"session_id": sid, "plan": plan, "summary": summary, "demo": False}

@app.post("/api/run")
async def run(req: RunReq):
    sid = req.session_id
    if sid not in sessions:
        raise HTTPException(404, "session not found")
    sess = sessions[sid]
    if sess["status"] != "plan_ready":
        raise HTTPException(400, "not plan_ready")
    if sess.get("demo"):
        async def demo_stream():
            yield sse("thinking", {"text": "Демо-режим: нет API ключа"})
            yield sse("done", {"text": "Поставь MISTRAL_API_KEY в Secrets"})
        return StreamingResponse(demo_stream(), media_type="text/event-stream")

    sess["status"] = "running"
    messages = sess["messages"]
    messages.append({"role": "user", "content": "PLAN_ACCEPTED. Execute now with tools."})

    async def stream():
        yield sse("status", {"status": "running"})
        yield sse("thinking", {"text": "План принят. Начинаю работу…"})
        try:
            for rnd in range(MAX_ROUNDS):
                yield sse("thinking", {"text": f"Раунд {rnd+1}: думаю / инструменты…"})
                resp = await mistral(messages, tools=TOOLS)
                msg = resp["choices"][0]["message"]
                messages.append(msg)
                if msg.get("content"):
                    yield sse("message", {"text": msg["content"]})
                    yield sse("thinking", {"text": msg["content"][:400]})
                tcs = msg.get("tool_calls") or []
                if not tcs:
                    yield sse("done", {"text": msg.get("content") or "DONE"})
                    sess["status"] = "done"
                    break
                for tc in tcs:
                    fn = tc["function"]
                    name = fn["name"]
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except Exception:
                        args = {}
                    yield sse("tool_call", {"name": name, "args": args})
                    try:
                        result = IMPL[name](args)
                    except Exception as e:
                        result = f"tool error: {e}"
                    yield sse("tool_result", {"name": name, "result": result[:5000]})
                    if name in ("write_file", "edit_file"):
                        try:
                            meta = json.loads(result)
                            yield sse("file_change", {
                                "path": meta.get("path") or args.get("path"),
                                "action": name,
                                "lines": meta.get("lines_after"),
                                "preview": meta.get("preview", "")[:2500],
                                "cloud_url": meta.get("cloud_url", ""),
                                "add": meta.get("lines_after", 0),
                                "del": meta.get("lines_before", 0),
                            })
                        except Exception:
                            pass
                    messages.append({"role": "tool", "name": name, "content": result, "tool_call_id": tc["id"]})
            else:
                yield sse("done", {"text": "Лимит раундов"})
                sess["status"] = "done"
        except Exception as e:
            yield sse("error", {"text": str(e)})
            sess["status"] = "error"
        sess["messages"] = messages

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.get("/api/files")
def files():
    out = []
    for p in sorted(WORKSPACE.rglob("*")):
        if p.is_file() and "__pycache__" not in str(p):
            rel = str(p.relative_to(WORKSPACE)).replace("\\", "/")
            out.append({"path": rel, "size": p.stat().st_size,
                        "mtime": datetime.fromtimestamp(p.stat().st_mtime).isoformat()})
    return {"files": out}

@app.get("/api/file")
def get_file(path: str):
    try:
        return {"path": path, "content": tool_read_file(path)}
    except Exception as e:
        raise HTTPException(400, str(e))

@app.post("/api/upload")
async def upload(files: List[UploadFile] = File(...)):
    saved = []
    for f in files:
        dest = WORKSPACE / f.filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(await f.read())
        cloud_upload(f.filename)
        saved.append(f.filename)
    return {"saved": saved}

ROOT = Path(__file__).parent

@app.get("/")
def index():
    return FileResponse(ROOT / "index.html")

@app.get("/styles.css")
def css():
    return FileResponse(ROOT / "styles.css", media_type="text/css")

@app.get("/app.js")
def js():
    return FileResponse(ROOT / "app.js", media_type="application/javascript")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "7860"))
    print(f"Misrtal Pro | key={bool(MISTRAL_API_KEY)} cloud={CLOUD_ON} port={port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
