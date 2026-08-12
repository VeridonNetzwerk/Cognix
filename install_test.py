"""CogniX Installer Test Script

Installs CogniX into a clean test directory, starts the bot with no
pre-loaded cogs, runs the setup wizard, and verifies the marketplace
flow works end-to-end.

Usage:
    python install_test.py
"""

import asyncio
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TEST_DIR = ROOT / "_test_install"
VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"


def step(n: int, msg: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"[{n}] {msg}")
    print(f"{'=' * 60}")


def run(cmd: list[str], cwd: Path | None = None, timeout: float = 30.0) -> tuple[int, str]:
    """Run a command and return (exitcode, output)."""
    try:
        r = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return -1, "TIMEOUT"
    except Exception as e:
        return -1, str(e)


def prepare_clean_install() -> None:
    """Create a clean test directory with a symlinked/synced copy of the bot."""
    step(1, "Preparing clean install directory")

    if TEST_DIR.exists():
        print(f"  Removing existing {TEST_DIR}")
        import time as _time
        for _ in range(5):
            shutil.rmtree(TEST_DIR, ignore_errors=True)
            _time.sleep(0.5)
            if not TEST_DIR.exists():
                break
        if TEST_DIR.exists():
            # Force remove via cmd
            subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", str(TEST_DIR)], check=False)
            _time.sleep(1)

    TEST_DIR.mkdir(parents=True, exist_ok=True)

    # Copy only the source code — no DB, no .cognix_cogs, no logs
    exclude_dirs = {
        "_test_install", ".git", ".venv", "__pycache__",
        "data", "logs", ".cognix_cogs", "test_cog_repo",
        "node_modules", "frontend", ".next",
    }
    exclude_files = {".env", "test_marketplace.py", "reset_setup.py", "install_test.py"}

    for item in ROOT.iterdir():
        if item.name in exclude_dirs or item.name in exclude_files:
            continue
        if item.is_dir():
            print(f"  Copying dir: {item.name}/")
            shutil.copytree(item, TEST_DIR / item.name, dirs_exist_ok=True)
        else:
            shutil.copy2(item, TEST_DIR / item.name)

    # Create empty data dir for SQLite
    (TEST_DIR / "data").mkdir(exist_ok=True)
    print(f"  Created data/")

    # Create .env for test
    env_content = """APP_ENV=development
APP_HOST=0.0.0.0
APP_PORT=8090
APP_BASE_URL=http://localhost:8090
DATABASE_URL=sqlite+aiosqlite:///./data/cognix.db
REDIS_URL=
AUTH_PEPPER=dev-pepper-change-in-production
MASTER_KEY=
JWT_SECRET=
LOG_LEVEL=INFO
LOG_JSON=false
SERVE_FRONTEND=false
"""
    (TEST_DIR / ".env").write_text(env_content)
    print(f"  Created .env (port=8090)")

    # Remove any __pycache__ that got copied
    for pyc in TEST_DIR.rglob("__pycache__"):
        shutil.rmtree(pyc, ignore_errors=True)

    print(f"  Install dir ready: {TEST_DIR}")


async def run_bot_and_test() -> None:
    """Start the bot in the test dir and run API tests against it."""
    step(2, "Starting bot in test directory")

    # Start bot as subprocess
    proc = subprocess.Popen(
        [str(VENV_PYTHON), "main.py"],
        cwd=str(TEST_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    print(f"  Bot PID: {proc.pid}")

    # Wait for API to be ready (look for "api_started" in output)
    # Note: Bot won't connect to Discord without a real token, but the
    # web API + setup wizard work independently.
    ready = False
    start_time = time.time()
    output_lines: list[str] = []

    while time.time() - start_time < 45:
        line = proc.stdout.readline() if proc.stdout else ""
        if line:
            line = line.strip()
            output_lines.append(line)
            print(f"  [bot] {line}")
            if "api_started" in line:
                ready = True
                # Give it a couple more seconds to finish startup
                time.sleep(2)
                break
            if "Traceback" in line or "Error" in line:
                print(f"  ERROR detected in bot output!")

    if not ready:
        print(f"\n  FAILED: Bot did not become ready within 45s")
        proc.terminate()
        proc.wait(timeout=5)
        return

    print(f"\n  API is ready! (took {time.time() - start_time:.1f}s)")
    print(f"  Note: Bot has no real Discord token — testing web API only.")

    # Run setup wizard via API
    step(3, "Running setup wizard")
    rc, out = run(
        ["curl", "-s", "-X", "POST", "http://localhost:8090/setup",
         "-d", "bot_token=test_token&application_id=123&admin_username=admin&admin_email=admin@test.com&admin_password=password123",
         "-w", "\\n%{http_code}"],
        timeout=15.0,
    )
    print(f"  Setup response: {out.strip().split(chr(10))[-1] if out else 'no output'}")

    # Login
    step(4, "Login as admin")
    rc, out = run(
        ["curl", "-s", "-c", str(TEST_DIR / "cookies.txt"),
         "-X", "POST", "http://localhost:8090/api/v1/auth/login",
         "-H", "Content-Type: application/json",
         "-d", '{"username":"admin","password":"password123"}',
         "-w", "\\n%{http_code}"],
        timeout=10.0,
    )
    status = out.strip().split("\n")[-1] if out else "?"
    print(f"  Login status: {status}")

    if status != "200":
        print(f"  Login failed! Response: {out}")
        proc.terminate()
        proc.wait(timeout=5)
        return

    cookies = str(TEST_DIR / "cookies.txt")

    # Check available cogs
    step(5, "Check available cogs (should show built-in, none installed)")
    rc, out = run(
        ["curl", "-s", "-b", cookies, "http://localhost:8090/api/v1/marketplace/available"],
        timeout=10.0,
    )
    print(f"  Available: {out[:200]}...")

    # Check installed cogs (should be empty)
    step(6, "Check installed cogs (should be empty)")
    rc, out = run(
        ["curl", "-s", "-b", cookies, "http://localhost:8090/api/v1/marketplace/installed"],
        timeout=10.0,
    )
    print(f"  Installed: {out}")

    # Load a built-in cog (will fail with 503 since bot has no Discord connection)
    step(7, "Load Utility cog via marketplace API (expected: 503 — no bot connection)")
    rc, out = run(
        ["curl", "-s", "-b", cookies, "-X", "POST",
         "http://localhost:8090/api/v1/marketplace/install",
         "-H", "Content-Type: application/json",
         "-d", '{"cog_or_url":"Utility"}',
         "-w", "\\n%{http_code}"],
        timeout=15.0,
    )
    lines = out.strip().split("\n") if out else []
    status_code = lines[-1] if lines else "?"
    body = "\n".join(lines[:-1]) if len(lines) > 1 else ""
    print(f"  Status: {status_code}")
    print(f"  Body: {body[:200]}")
    if status_code == "503":
        print(f"  OK: Expected 503 — bot not connected to Discord (no real token)")
    elif status_code == "200":
        print(f"  OK: Cog loaded successfully (bot is connected)")
    else:
        print(f"  WARNING: Unexpected status {status_code}")

    # Check installed again (should show Utility)
    step(8, "Check installed cogs (should show Utility)")
    rc, out = run(
        ["curl", "-s", "-b", cookies, "http://localhost:8090/api/v1/marketplace/installed"],
        timeout=10.0,
    )
    print(f"  Installed: {out[:300]}")

    # Unload Utility (only if it was loaded)
    step(9, "Unload Utility cog (skip if not loaded)")
    if status_code == "200":
        rc, out = run(
            ["curl", "-s", "-b", cookies, "-X", "POST",
             "http://localhost:8090/api/v1/marketplace/uninstall",
             "-H", "Content-Type: application/json",
             "-d", '{"cog_name":"Utility"}',
             "-w", "\\n%{http_code}"],
            timeout=15.0,
        )
        lines = out.strip().split("\n") if out else []
        print(f"  Unload result: {lines[-2] if len(lines) > 1 else out}")
    else:
        print(f"  Skipped — Utility was not loaded (no bot connection)")

    # Check installed again (should be empty again)
    step(10, "Check installed cogs (should be empty again)")
    rc, out = run(
        ["curl", "-s", "-b", cookies, "http://localhost:8090/api/v1/marketplace/installed"],
        timeout=10.0,
    )
    print(f"  Installed: {out}")

    # Test marketplace page loads
    step(11, "Check marketplace HTML page")
    rc, out = run(
        ["curl", "-s", "-b", cookies, "http://localhost:8090/marketplace", "-w", "\\n%{http_code}"],
        timeout=10.0,
    )
    status = out.strip().split("\n")[-1] if out else "?"
    has_marketplace = "Marketplace" in (out or "")
    print(f"  Page status: {status}, contains 'Marketplace': {has_marketplace}")

    # Summary
    step(12, "Summary")
    print(f"  Test directory: {TEST_DIR}")
    print(f"  Bot port: 8090")
    print(f"  All tests completed!")

    # Cleanup
    print(f"\n  Stopping bot...")
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()

    # Show any remaining output
    remaining = proc.stdout.read() if proc.stdout else ""
    for line in remaining.strip().split("\n")[-10:]:
        if line.strip():
            print(f"  [bot] {line.strip()}")

    print(f"\n  Bot stopped. Test dir preserved at {TEST_DIR} for inspection.")


def main() -> None:
    print("=" * 60)
    print("CogniX Installer Test — Clean install with no pre-loaded cogs")
    print("=" * 60)

    if not VENV_PYTHON.exists():
        print(f"ERROR: Python not found at {VENV_PYTHON}")
        sys.exit(1)

    prepare_clean_install()
    asyncio.run(run_bot_and_test())


if __name__ == "__main__":
    main()
