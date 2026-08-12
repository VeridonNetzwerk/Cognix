#!/usr/bin/env python3
"""CogniX installer — sets up the bot from scratch.

Usage:
    python install.py

What it does:
  1. Checks Python version (>= 3.12)
  2. Creates a virtual environment (.venv/)
  3. Installs all dependencies from requirements.txt
  4. Copies .env.example → .env (if not already present)
  5. Generates MASTER_KEY, JWT_SECRET, AUTH_PEPPER automatically
  6. Runs Alembic database migrations
  7. Optionally creates an admin account
  8. Prints next-step instructions

"""

from __future__ import annotations

import base64
import os
import secrets
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"

# ANSI colors
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"


def info(msg: str) -> None:
    print(f"{GREEN}[✓]{RESET} {msg}")


def warn(msg: str) -> None:
    print(f"{YELLOW}[!]{RESET} {msg}")


def error(msg: str) -> None:
    print(f"{RED}[✗]{RESET} {msg}")


def header(msg: str) -> None:
    print(f"\n{BOLD}{'=' * 50}{RESET}")
    print(f"{BOLD}  {msg}{RESET}")
    print(f"{BOLD}{'=' * 50}{RESET}\n")


def run(cmd: list[str], **kwargs) -> int:
    return subprocess.run(cmd, check=kwargs.pop("check", True), cwd=ROOT, **kwargs).returncode


def check_python_version() -> None:
    header("Checking Python version")
    if sys.version_info < (3, 12):
        error(f"Python 3.12+ required, got {sys.version_info[0]}.{sys.version_info[1]}")
        sys.exit(1)
    info(f"Python {sys.version_info[0]}.{sys.version_info[1]}.{sys.version_info[2]} OK")


def create_venv() -> str:
    header("Creating virtual environment")
    if VENV_DIR.exists():
        info(".venv/ already exists — skipping creation")
    else:
        venv.create(str(VENV_DIR), with_pip=True)
        info("Virtual environment created at .venv/")

    if sys.platform == "win32":
        pip = str(VENV_DIR / "Scripts" / "pip.exe")
        python = str(VENV_DIR / "Scripts" / "python.exe")
    else:
        pip = str(VENV_DIR / "bin" / "pip")
        python = str(VENV_DIR / "bin" / "python")

    return python


def install_deps(python: str) -> None:
    header("Installing dependencies")
    run([python, "-m", "pip", "install", "--upgrade", "pip"])
    run([python, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")])
    info("All dependencies installed")


def setup_env() -> None:
    header("Setting up .env file")

    if ENV_FILE.exists():
        warn(".env already exists — skipping (edit manually if needed)")
        return

    if not ENV_EXAMPLE.exists():
        error(".env.example not found!")
        sys.exit(1)

    content = ENV_EXAMPLE.read_text()

    # Generate secrets
    master_key = base64.b64encode(secrets.token_bytes(32)).decode()
    jwt_secret = secrets.token_urlsafe(64)
    auth_pepper = secrets.token_urlsafe(32)

    content = content.replace("MASTER_KEY=", f"MASTER_KEY={master_key}")
    content = content.replace("JWT_SECRET=", f"JWT_SECRET={jwt_secret}")
    content = content.replace("AUTH_PEPPER=", f"AUTH_PEPPER={auth_pepper}")

    ENV_FILE.write_text(content)
    info(".env created with generated secrets")
    info(f"  MASTER_KEY: {master_key[:12]}...")
    info(f"  JWT_SECRET: {jwt_secret[:12]}...")
    info(f"  AUTH_PEPPER: {auth_pepper[:12]}...")


def run_migrations(python: str) -> None:
    header("Running database migrations")
    # Ensure data/ dir exists for SQLite
    data_dir = ROOT / "data"
    data_dir.mkdir(exist_ok=True)
    run([python, "-m", "alembic", "upgrade", "head"])
    info("Database migrations complete")


def create_admin(python: str) -> None:
    header("Admin account setup")
    answer = input("Create an admin account now? [Y/n] ").strip().lower()
    if answer and answer != "y":
        warn("Skipping admin creation — you can do this later with:")
        warn(f"  {python} -m tests.scripts.create_admin <username> <email> <password>")
        return

    username = input("Admin username: ").strip()
    if not username:
        error("Username cannot be empty")
        return
    email = input("Admin email (optional, press Enter to skip): ").strip()
    password = input("Admin password (min 10 chars): ").strip()
    if len(password) < 10:
        error("Password must be at least 10 characters")
        return

    cmd = [python, "-m", "tests.scripts.create_admin", username]
    if email:
        cmd.append(email)
    cmd.append(password)
    run(cmd)
    info(f"Admin account '{username}' created")


def print_next_steps(python: str) -> None:
    header("Installation complete!")
    print(f"""
  {BOLD}Next steps:{RESET}

  1. Edit {YELLOW}.env{RESET} and set your Discord bot token:
     DISCORD_BOT_TOKEN=your_token_here

  2. Or skip that and use the web setup wizard — just start the bot:

     {GREEN}{python} main.py{RESET}

  3. Open {YELLOW}http://localhost:8080{RESET} in your browser
     The first-run setup wizard will guide you through the rest.

  4. Install cogs from the dashboard Marketplace tab.

  {BOLD}Useful commands:{RESET}
     Start bot:     {python} main.py
     Create admin:  {python} -m tests.scripts.create_admin <username> <email> <password>
     Health check:  {python} -m tests.scripts.healthcheck

  {BOLD}Documentation:{RESET} see docs/ folder
""")


def main() -> int:
    print(f"\n{BOLD}  CogniX Installer{RESET}")
    print(f"  Modular Discord bot platform\n")

    try:
        check_python_version()
        python = create_venv()
        install_deps(python)
        setup_env()
        run_migrations(python)
        create_admin(python)
        print_next_steps(python)
    except KeyboardInterrupt:
        error("\nInstallation cancelled by user")
        return 1
    except subprocess.CalledProcessError as exc:
        error(f"Command failed: {' '.join(exc.cmd or [])}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
