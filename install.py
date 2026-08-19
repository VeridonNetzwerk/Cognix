#!/usr/bin/env python3
"""CogniX installer — clones the repo and sets up the bot from scratch.

Usage:
    python install.py [target_dir] [options]

What it does:
   1. Checks Python version (>= 3.12)
   2. Cleans the target directory (removes everything except install.py and .env)
   3. Clones the CogniX repository using a *sparse* checkout so only the
      strictly necessary paths are downloaded. By default this excludes the
      optional `cogs_store/` (cog marketplace), `docs/` and `tests/` to keep
      the install footprint minimal.
   4. Creates a virtual environment (.venv/)
   5. Installs only the CORE dependencies from requirements-core.txt (or the
      full bundle with --profile full)
   6. Copies .env.example -> .env (if not already present)
   7. Generates MASTER_KEY, JWT_SECRET, AUTH_PEPPER automatically
   8. Runs Alembic database migrations
   9. Prints next-step instructions

Admin account is created during the web setup wizard (first launch).

Modularity / filtering:
   --profile core   (default) sparse clone without cogs_store/docs/tests,
                              installs requirements-core.txt
   --profile full   sparse clone WITH cogs_store, installs requirements.txt
   --with-cogs-store / --with-docs / --with-tests  opt individual components in
   --requirements FILE                            override the dependency file
"""

from __future__ import annotations

import argparse
import base64
import os
import secrets
import shutil
import subprocess
import sys
import venv
from pathlib import Path

REPO_URL = "https://github.com/VeridonNetzwerk/CogniX.git"

# Resolved after clone — defaults to script directory
ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"

# Top-level paths that are strictly necessary for core functionality.
# Root-level files are always included by git's cone-mode sparse checkout.
CORE_SPARSE_PATHS = ["bot", "web", "cogs"]

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


def clean_directory(target: Path) -> None:
    """Remove everything inside *target* except install.py and .env."""
    header(f"Cleaning {target}")
    script = target / "install.py"
    script_data = script.read_bytes() if script.exists() else None

    for item in target.iterdir():
        # Preserve .env so users don't lose their config on reinstall
        if item.name == ".env":
            continue
        try:
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink()
        except Exception:
            pass

    if script_data is not None:
        script.write_bytes(script_data)
    info(f"Cleaned {target}")


def clone_repo(target: Path, *, with_cogs_store: bool, with_docs: bool, with_tests: bool) -> None:
    """Clone the repo with a sparse checkout to avoid downloading optional
    components (cogs_store, docs, tests) unless explicitly requested.

    Falls back to a full clone if sparse-checkout is unsupported or fails.
    """
    header("Cloning CogniX repository (sparse)")

    cone = list(CORE_SPARSE_PATHS)
    if with_cogs_store:
        cone.append("cogs_store")
    if with_docs:
        cone.append("docs")
    if with_tests:
        cone += ["tests", "bot/tests"]

    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="cognix_clone_"))

    try:
        # Partial clone: trees + commits, but no file blobs yet.
        run(["git", "clone", "--filter=blob:none", "--no-checkout", REPO_URL, str(tmp)])
        try:
            # Cone-mode sparse checkout keeps root files automatically and
            # downloads blobs only for the selected directories.
            run(["git", "-C", str(tmp), "sparse-checkout", "init", "--cone"])
            run(["git", "-C", str(tmp), "sparse-checkout", "set", *cone])
            run(["git", "-C", str(tmp), "checkout"])
        except subprocess.CalledProcessError:
            warn("sparse-checkout unsupported — falling back to full checkout")
            run(["git", "-C", str(tmp), "checkout"])
    except subprocess.CalledProcessError:
        warn("partial clone failed — falling back to full clone")
        shutil.rmtree(tmp, ignore_errors=True)
        tmp = Path(tempfile.mkdtemp(prefix="cognix_clone_"))
        run(["git", "clone", REPO_URL, str(tmp)])

    try:
        # Copy all files (except .git) into target
        for item in tmp.iterdir():
            if item.name == ".git":
                continue
            dest = target / item.name
            try:
                if dest.exists():
                    if dest.is_dir():
                        shutil.rmtree(dest, ignore_errors=True)
                    else:
                        dest.unlink()
            except OSError:
                pass
            if item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest)

        # Copy .git into target so it's a proper repo (non-fatal on NAS permission issues)
        git_dest = target / ".git"
        if git_dest.exists():
            shutil.rmtree(git_dest, ignore_errors=True)
        try:
            shutil.copytree(tmp / ".git", git_dest, dirs_exist_ok=True)
        except (OSError, shutil.Error):
            warn("Could not copy .git to target (NAS permission issue) — git operations may be limited")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    skipped = [p for p, on in (("cogs_store", not with_cogs_store), ("docs", not with_docs), ("tests", not with_tests)) if on]
    if skipped:
        info(f"Repository cloned (excluded optional: {', '.join(skipped)})")
    else:
        info("Repository cloned (full)")


def create_venv() -> str:
    header("Creating virtual environment")

    if sys.platform == "win32":
        python_exe = VENV_DIR / "Scripts" / "python.exe"
    else:
        python_exe = VENV_DIR / "bin" / "python"

    if VENV_DIR.exists() and python_exe.exists():
        info(".venv/ already exists — skipping creation")
    else:
        if VENV_DIR.exists():
            shutil.rmtree(VENV_DIR, ignore_errors=True)
        venv.create(str(VENV_DIR), with_pip=True)
        info("Virtual environment created at .venv/")

    if sys.platform == "win32":
        pip = str(VENV_DIR / "Scripts" / "pip.exe")
        python = str(VENV_DIR / "Scripts" / "python.exe")
    else:
        pip = str(VENV_DIR / "bin" / "pip")
        python = str(VENV_DIR / "bin" / "python")

    return python


def install_deps(python: str, requirements_file: Path) -> None:
    header(f"Installing dependencies ({requirements_file.name})")
    run([python, "-m", "pip", "install", "--upgrade", "pip"])
    run([python, "-m", "pip", "install", "-r", str(requirements_file)])
    info("Dependencies installed")


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


def setup_cogs_dir() -> None:
    header("Setting up cogs directory")
    cogs_dir = ROOT / "cogs"
    if cogs_dir.exists():
        info("cogs/ directory already exists — skipping")
    else:
        cogs_dir.mkdir(exist_ok=True)
        (cogs_dir / "__init__.py").touch()
        info("Created empty cogs/ directory — install cogs from the web panel")


def run_migrations(python: str) -> None:
    header("Running database migrations")
    # Ensure data/ dir exists for SQLite
    data_dir = ROOT / "data"
    data_dir.mkdir(exist_ok=True)
    run([python, "-m", "alembic", "upgrade", "head"])
    info("Database migrations complete")


def print_next_steps(python: str, profile: str, with_cogs_store: bool) -> None:
    header("Installation complete!")
    cog_note = (
        "Cogs are NOT bundled (minimal install). Install them from the web panel\n"
        "once a cog store is available, or re-run install.py with --with-cogs-store."
        if not with_cogs_store
        else "Cogs are available from the built-in store — install them from the web panel."
    )
    print(f"""
  {BOLD}Next steps:{RESET}

  1. Start the bot:

     {GREEN}{python} main.py{RESET}

  2. Open {YELLOW}http://localhost:8080{RESET} in your browser
     The first-run setup wizard will guide you through:
        - Bot token setup
        - Admin account creation
        - Optional Google OAuth + 2FA

  3. {cog_note}

  {BOLD}Profile:{RESET} {profile}
  {BOLD}Useful commands:{RESET}
     Start bot:     {python} main.py
     Health check:  {python} -m bot.scripts.healthcheck

  {BOLD}Documentation:{RESET} see docs/ folder (if installed)
""")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="CogniX installer — minimal, modular setup.",
    )
    parser.add_argument("target", nargs="?", default=None, help="Target directory (default: script dir)")
    parser.add_argument(
        "--profile",
        choices=["core", "full"],
        default="core",
        help="core = minimal sparse clone + core deps (default); "
             "full = include cogs_store + full dependency bundle",
    )
    parser.add_argument(
        "--with-cogs-store",
        action="store_true",
        help="Include the cogs_store/ cog marketplace (implied by --profile full).",
    )
    parser.add_argument(
        "--with-docs",
        action="store_true",
        help="Include the docs/ folder.",
    )
    parser.add_argument(
        "--with-tests",
        action="store_true",
        help="Include the tests/ and bot/tests/ folders.",
    )
    parser.add_argument(
        "--requirements",
        default=None,
        help="Override the dependency file (default: requirements-core.txt / "
             "requirements.txt per profile).",
    )
    return parser.parse_args(argv)


def main() -> int:
    global ROOT, VENV_DIR, ENV_FILE, ENV_EXAMPLE

    args = parse_args(sys.argv[1:])

    # --profile full implies the cog store (and uses the full dependency bundle)
    with_cogs_store = args.with_cogs_store or args.profile == "full"

    requirements_file = Path(args.requirements) if args.requirements else (
        ROOT / "requirements.txt" if args.profile == "full" else ROOT / "requirements-core.txt"
    )

    print(f"\n{BOLD}  CogniX Installer{RESET}")
    print(f"  Modular Discord bot platform\n")

    target = Path(args.target).resolve() if args.target else ROOT

    try:
        check_python_version()
        clean_directory(target)
        ROOT = target
        VENV_DIR = ROOT / ".venv"
        ENV_FILE = ROOT / ".env"
        ENV_EXAMPLE = ROOT / ".env.example"
        clone_repo(
            target,
            with_cogs_store=with_cogs_store,
            with_docs=args.with_docs,
            with_tests=args.with_tests,
        )
        python = create_venv()
        install_deps(python, requirements_file)
        setup_env()
        setup_cogs_dir()
        run_migrations(python)
        print_next_steps(python, args.profile, with_cogs_store)
    except KeyboardInterrupt:
        error("\nInstallation cancelled by user")
        return 1
    except subprocess.CalledProcessError as exc:
        error(f"Command failed: {' '.join(exc.cmd or [])}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
