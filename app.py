# app.py
import os
import json
import uuid
import base64
import sqlite3
import asyncio
import datetime as dt
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional

from flask import Flask, request, jsonify, render_template

from groq import Groq


# -----------------------------------------------------------------------------
# Shibuya Tokyo Cyberpunk — DOM-First Browser Agent (Planner → Executor)
# -----------------------------------------------------------------------------
# - Planner (Groq) outputs a JSON plan using ONLY 3 tools:
#     1) go(url)
#     2) click(text)
#     3) type(label, value)
# - Executor runs Playwright inside Docker (sandbox-ish) and returns:
#     - final DOM preview (truncated)
#     - final screenshot file path (artifacts/<run_id>_final.png)
#     - optional vision verification of the final screenshot
#
# Repo layout (top-level):
#   app.py
#   templates/
#   static/
#   artifacts/
#   docker_work/
#   docker/
#   demo.db
# -----------------------------------------------------------------------------

APP_PORT = int(os.getenv("PORT", "8000"))

# Groq
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_TEXT_MODEL = os.getenv("GROQ_TEXT_MODEL", "llama-3.1-8b-instant")
GROQ_VISION_MODEL = os.getenv(
    "GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")

# Docker image for executor (build it from ./docker/Dockerfile)
EXECUTOR_IMAGE = os.getenv(
    "EXECUTOR_IMAGE", "chikar-playwright-executor:latest")

# Storage
DB_PATH = os.getenv("DB_PATH", "demo.db")
ARTIFACTS_DIR = Path(os.getenv("ARTIFACTS_DIR", "artifacts"))
DOCKER_WORK_DIR = Path(os.getenv("DOCKER_WORK_DIR", "docker_work"))
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
DOCKER_WORK_DIR.mkdir(parents=True, exist_ok=True)

# Demo target
DEFAULT_PRODUCT_URL = os.getenv(
    "DEFAULT_PRODUCT_URL",
    "https://chikarahouses.com/products/hardcover-bound-notebook-3",
)

# DOM preview max chars (demo-only)
DOM_PREVIEW_LIMIT = int(os.getenv("DOM_PREVIEW_LIMIT", "1000"))

app = Flask(__name__)
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None


# -----------------------------------------------------------------------------
# SQLite (minimal)
# -----------------------------------------------------------------------------
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                user_goal TEXT NOT NULL,
                plan_json TEXT NOT NULL,
                result_json TEXT
            )
           """
        )


init_db()


# -----------------------------------------------------------------------------
# Tool schema (ONLY 3 tools)
# -----------------------------------------------------------------------------
ALLOWED_TOOLS = {"go", "click", "type"}


def validate_plan(plan: List[Dict[str, Any]]) -> Tuple[bool, str]:
    """
    Validate the planner's JSON plan.
    Hard guardrails prevent the LLM from escaping the tool sandbox.
    """
    if not isinstance(plan, list):
        return False, "Plan must be a list."
    if len(plan) == 0:
        return False, "Plan is empty."
    if len(plan) > 10:
        return False, "Plan too long (max 10 steps)."

    for i, step in enumerate(plan):
        if not isinstance(step, dict):
            return False, f"Step {i} must be an object."
        tool = step.get("tool")
        args = step.get("args", {})
        if tool not in ALLOWED_TOOLS:
            return False, f"Step {i}: tool '{tool}' not allowed."
        if not isinstance(args, dict):
            return False, f"Step {i}: args must be an object."

        if tool == "go":
            if set(args.keys()) != {"url"}:
                return False, f"Step {i}: go expects args {{url}} only."
        elif tool == "click":
            if set(args.keys()) != {"text"}:
                return False, f"Step {i}: click expects args {{text}} only."
        elif tool == "type":
            if set(args.keys()) != {"label", "value"}:
                return False, f"Step {i}: type expects args {{label, value}} only."

    return True, "ok"


# -----------------------------------------------------------------------------
# Planner (Groq SDK)
# -----------------------------------------------------------------------------
def deterministic_demo_plan(note_text: str) -> List[Dict[str, Any]]:
    """
    Deterministic plan (used when GROQ_API_KEY is missing or on planner failure).
    Scenario:
      - go to product page
      - add to cart
      - view cart
      - type into 'Order special instructions'
    """
    return [
        {"tool": "go", "args": {"url": DEFAULT_PRODUCT_URL}},
        {"tool": "click", "args": {"text": "Add to cart"}},
        {"tool": "click", "args": {"text": "View cart"}},
        {"tool": "type", "args": {
            "label": "Order special instructions", "value": note_text}},
    ]


async def groq_plan(user_goal: str, note_text: str) -> List[Dict[str, Any]]:
    """
    Planner returns ONLY JSON (no markdown).
    """
    if not groq_client:
        return deterministic_demo_plan(note_text)

    system = (
        "You are a planning agent. Output ONLY valid JSON (no markdown). "
        "Return a list of steps. Each step must be one of:\n"
        '  {"tool":"go","args":{"url":"https://..."}}\n'
        '  {"tool":"click","args":{"text":"Visible button/link text"}}\n'
        '  {"tool":"type","args":{"label":"Field label or placeholder","value":"text"}}\n'
        "Rules:\n"
        "- Use DOM-first actions.\n"
        "- Keep steps <= 6.\n"
        "- Use chikarahouses.com.\n"
        "- Do not proceed to payment submission.\n"
        "- Target this flow:\n"
        "  1) go to product page\n"
        "  2) click 'Add to cart'\n"
        "  3) click 'View cart'\n"
        "  4) type the note into 'Order special instructions'\n"
        "\n"
        f"Product page: {DEFAULT_PRODUCT_URL}\n"
        f"Note text to type: {note_text}\n"
    )

    def _call() -> str:
        completion = groq_client.chat.completions.create(
            model=GROQ_TEXT_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_goal},
            ],
            temperature=0.2,
            max_completion_tokens=600,
        )
        return completion.choices[0].message.content.strip()

    content = await asyncio.to_thread(_call)

    try:
        plan = json.loads(content)
        ok, msg = validate_plan(plan)
        if not ok:
            return deterministic_demo_plan(note_text)
        return plan
    except Exception:
        return deterministic_demo_plan(note_text)


# -----------------------------------------------------------------------------
# Optional: Vision verification (Groq Vision)
# -----------------------------------------------------------------------------
def encode_image_b64(path: Path) -> str:
    """
    Encode an image file to base64 for Groq vision input.
    """
    data = path.read_bytes()
    return base64.b64encode(data).decode("utf-8")


async def groq_vision_verify(image_path: Path) -> Optional[str]:
    """
    Demo-only: Ask the vision model to confirm the cart page and special instructions box.
    Returns a short text verification, or None if no GROQ_API_KEY.
    """
    if not groq_client:
        return None

    b64 = await asyncio.to_thread(encode_image_b64, image_path)

    prompt = (
        "You are verifying a demo run. "
        "Confirm if this screenshot shows:\n"
        "1) A cart page ('Your cart')\n"
        "2) The product 'ZenPath Hardcover Goal Notebook 3'\n"
        "3) A textarea labeled 'Order special instructions' containing some text\n"
        "Reply with a short verification summary."
    )

    def _call() -> str:
        completion = groq_client.chat.completions.create(
            model=GROQ_VISION_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b64}"},
                        },
                    ],
                }
            ],
            temperature=0.2,
            max_completion_tokens=250,
        )
        return completion.choices[0].message.content.strip()

    try:
        return await asyncio.to_thread(_call)
    except Exception:
        return None


# -----------------------------------------------------------------------------
# Executor: run Playwright inside Docker (single container per job)
# -----------------------------------------------------------------------------
PLAYWRIGHT_RUNNER = r"""
import json
import os
import asyncio
from playwright.async_api import async_playwright

REQ_PATH = "/work/request.json"
OUT_PATH = "/work/result.json"
FINAL_SCREENSHOT_PATH = "/work/final.png"

DOM_PREVIEW_LIMIT = int(os.getenv("DOM_PREVIEW_LIMIT", "1000"))

def dom_preview(html: str) -> str:
    html = html.replace("\n", " ").replace("\t", " ")
    return html[:DOM_PREVIEW_LIMIT]

async def click_by_text(page, text: str):
    # Prefer accessible roles
    loc = page.get_by_role("button", name=text)
    if await loc.count() == 0:
        loc = page.get_by_role("link", name=text)
    if await loc.count() == 0:
        # Last resort: raw text locator
        loc = page.locator(f"text={text}")
    await loc.first.click(timeout=15000)

async def type_by_label(page, label: str, value: str):
    loc = page.get_by_label(label)
    if await loc.count() == 0:
        loc = page.get_by_placeholder(label)
    if await loc.count() == 0:
        # Last resort: try text=label then nearest textarea/input
        loc = page.locator(f"text={label}").locator("..").locator("textarea, input")
    await loc.first.fill(value, timeout=15000)

async def main():
    with open(REQ_PATH, "r", encoding="utf-8") as f:
        req = json.load(f)

    plan = req["plan"]
    headless = bool(req.get("headless", True))

    out = {
        "ok": True,
        "steps": [],
        "final_url": None,
        "final_title": None,
        "final_dom_preview": None,
        "final_screenshot": "artifacts/final.png",
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(viewport={"width": 1200, "height": 900})
        page = await context.new_page()

        for idx, step in enumerate(plan):
            tool = step["tool"]
            args = step["args"]
            step_out = {"idx": idx, "tool": tool, "args": args, "ok": True, "error": None, "url": None, "title": None}

            try:
                if tool == "go":
                    await page.goto(args["url"], wait_until="domcontentloaded", timeout=45000)

                elif tool == "click":
                    await click_by_text(page, args["text"])

                elif tool == "type":
                    await type_by_label(page, args["label"], args["value"])

                else:
                    raise ValueError(f"Unknown tool: {tool}")

                step_out["url"] = page.url
                step_out["title"] = await page.title()

            except Exception as e:
                step_out["ok"] = False
                step_out["error"] = str(e)
                out["ok"] = False

            out["steps"].append(step_out)
            if not step_out["ok"]:
                break

        out["final_url"] = page.url
        out["final_title"] = await page.title()

        # Final evidence screenshot (always)
        await page.screenshot(path=FINAL_SCREENSHOT_PATH, full_page=False)

        # Minimal DOM preview (demo)
        html = await page.content()
        out["final_dom_preview"] = dom_preview(html)

        await context.close()
        await browser.close()

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    asyncio.run(main())
""".strip()


async def run_in_docker(run_id: str, plan: List[Dict[str, Any]], headless: bool = True) -> Dict[str, Any]:
    """
    Run the executor in Docker:
      - Write request.json + runner.py into ./docker_work/
      - Mount ./docker_work -> /work
      - Copy /work/final.png + /work/result.json into ./artifacts
    """
    work_run_dir = DOCKER_WORK_DIR / run_id
    work_run_dir.mkdir(parents=True, exist_ok=True)

    request_path = work_run_dir / "request.json"
    runner_path = work_run_dir / "runner.py"
    result_path = work_run_dir / "result.json"
    final_path = work_run_dir / "final.png"

    request_path.write_text(
        json.dumps({"plan": plan, "headless": headless},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    runner_path.write_text(PLAYWRIGHT_RUNNER, encoding="utf-8")

    # Run container
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{work_run_dir.resolve()}:/work",
        "-e", f"DOM_PREVIEW_LIMIT={DOM_PREVIEW_LIMIT}",
        EXECUTOR_IMAGE,
        "python", "/work/runner.py",
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout_b, stderr_b = await proc.communicate()
    stdout = stdout_b.decode("utf-8", errors="replace")
    stderr = stderr_b.decode("utf-8", errors="replace")

    if proc.returncode != 0:
        return {
            "ok": False,
            "docker_returncode": proc.returncode,
            "stdout": stdout[-3000:],
            "stderr": stderr[-3000:],
        }

    if not result_path.exists() or not final_path.exists():
        return {
            "ok": False,
            "docker_returncode": proc.returncode,
            "stdout": stdout[-2000:],
            "stderr": (stderr + "\nMissing result.json or final.png")[-3000:],
        }

    # Copy artifacts to top-level ./artifacts for easy demo navigation
    final_out = ARTIFACTS_DIR / f"{run_id}_final.png"
    json_out = ARTIFACTS_DIR / f"{run_id}_output.json"
    final_out.write_bytes(final_path.read_bytes())
    json_out.write_text(result_path.read_text(
        encoding="utf-8"), encoding="utf-8")

    result = json.loads(json_out.read_text(encoding="utf-8"))
    return {
        "ok": True,
        "run_id": run_id,
        "result": result,
        "final_screenshot": str(final_out),
        "final_output_json": str(json_out),
        "logs": {"stdout": stdout[-2000:], "stderr": stderr[-2000:]},
    }


# -----------------------------------------------------------------------------
# Flask routes
# -----------------------------------------------------------------------------
@app.get("/")
def home():
    return render_template(
        "index.html",
        groq_text_model=GROQ_TEXT_MODEL,
        groq_vision_model=GROQ_VISION_MODEL,
        executor_image=EXECUTOR_IMAGE,
        default_product_url=DEFAULT_PRODUCT_URL,
    )


@app.post("/api/plan")
async def api_plan():
    data = request.get_json(force=True) or {}
    goal = (data.get("goal") or "").strip()
    note_text = (data.get("note_text") or "").strip(
    ) or "Shibuya Tokyo Cyberpunk demo note."

    plan = await groq_plan(goal, note_text)
    ok, msg = validate_plan(plan)

    return jsonify({"ok": ok, "plan": plan, "note": msg})


@app.post("/api/run")
async def api_run():
    data = request.get_json(force=True) or {}

    goal = (data.get("goal") or "").strip()
    note_text = (data.get("note_text") or "").strip(
    ) or "Shibuya Tokyo Cyberpunk demo note."
    plan = data.get("plan")

    if not goal:
        goal = "Demo: add product to cart, open cart, and type special instructions."

    if not isinstance(plan, list):
        # If UI didn't provide a plan, generate one.
        plan = await groq_plan(goal, note_text)

    ok, msg = validate_plan(plan)
    if not ok:
        plan = deterministic_demo_plan(note_text)

    run_id = uuid.uuid4().hex[:10]
    created_at = dt.datetime.utcnow().isoformat()

    with db() as conn:
        conn.execute(
            "INSERT INTO runs (id, created_at, user_goal, plan_json) VALUES (?, ?, ?, ?)",
            (run_id, created_at, goal, json.dumps(plan, ensure_ascii=False)),
        )

    exec_out = await run_in_docker(run_id, plan, headless=True)

    if not exec_out.get("ok"):
        with db() as conn:
            conn.execute(
                "UPDATE runs SET result_json=? WHERE id=?",
                (json.dumps(exec_out, ensure_ascii=False), run_id),
            )
        return jsonify(exec_out), 500

    # Optional: vision verification from final screenshot
    final_ss = Path(exec_out["final_screenshot"])
    vision_summary = await groq_vision_verify(final_ss)

    payload = {
        "ok": True,
        "run_id": run_id,
        "plan": plan,
        "final_screenshot": exec_out["final_screenshot"],
        "final_output_json": exec_out["final_output_json"],
        "result": exec_out["result"],
        "vision_summary": vision_summary,
        "logs": exec_out["logs"],
    }

    with db() as conn:
        conn.execute(
            "UPDATE runs SET result_json=? WHERE id=?",
            (json.dumps(payload, ensure_ascii=False), run_id),
        )

    return jsonify(payload)


# app.py (optional: add favicon route to avoid 404 noise)
from flask import send_from_directory

@app.get("/favicon.ico")
def favicon():
    # no file shipped; return 204 (no content) to keep logs clean
    return ("", 204)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=APP_PORT, debug=True)
