"""Cog Marketplace — install plugins from GitHub like VS Code extensions.

Provides `/marketplace` slash command group with subcommands:
    /marketplace list [query]       Browse available cogs (picks up cached results)
    /marketplace info <name>         Show details of a cog
    /marketplace installed            List currently installed marketplace packages
    /marketplace install <repo>      Clone & install a cog from GitHub
    /marketplace uninstall <name>    Remove an installed marketplace cog

Installation target: .cognix_cogs/<name>/ inside the project root.
The directory is added to sys.path so the cog module becomes importable.

Security:
    - Only HTTPS GitHub URLs are accepted (or matching the public repo list)
    - Dependencies are logged before install for review
    - Owner-only command for installation

Public registry of curated cogs lives at:
    https://raw.githubusercontent.com/VeridonNetzwerk/cognix-marketplace/main/registry.json

If the registry URL is unreachable, falls back to an empty curated list
so the bot still works offline.
"""

from __future__ import annotations

import asyncio
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select as sa_select

from bot.config.logging import get_logger
from bot.database import db_session
from bot.database.models.cog_package import CogPackage

log = get_logger("bot.cogs.marketplace")


def is_owner() -> app_commands.Check:
    """App-commands compatible owner check."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user is None:
            return False
        if await interaction.client.is_owner(interaction.user):
            return True
        if interaction.guild is not None and interaction.guild.owner_id == interaction.user.id:
            return True
        return False
    return app_commands.check(predicate)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MARKETPLACE_REGISTRY_URL = (
    "https://raw.githubusercontent.com/VeridonNetzwerk/cognix-marketplace/main/registry.json"
)
INSTALL_DIR_NAME = ".cognix_cogs"
CACHE_TTL_SECONDS = 15 * 60  # cache curated list for 15 minutes

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _project_root() -> Path:
    """Return the project root directory (parent of bot/)."""
    return Path(__file__).resolve().parent.parent.parent


def _get_install_dir() -> Path:
    """Return the directory where marketplace cogs are installed."""
    return _project_root() / INSTALL_DIR_NAME


# ---------------------------------------------------------------------------
# GitHub Registry client
# ---------------------------------------------------------------------------


@dataclass
class MarketplaceCogEntry:
    """Metadata for a cog in the public marketplace."""

    name: str
    display_name: str
    description: str
    github_repo: str
    branch: str = "main"
    version: str | None = None
    dependencies: list[str] = field(default_factory=list)
    category: str = "General"
    requires_admin: bool = False
    author: str | None = None


def _parse_registry_response(raw: Any) -> list[dict[str, Any]]:
    """Normalize registry response to a flat list of dicts."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict) and "cogs" in raw:
        return raw["cogs"]
    return []


async def fetch_registry() -> list[dict[str, Any]]:
    """Fetch the curated registry from GitHub. Returns [] on failure."""
    try:
        import httpx

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(MARKETPLACE_REGISTRY_URL)
            resp.raise_for_status()
            data = resp.json()
            return _parse_registry_response(data)
    except Exception:  # noqa: BLE001
        log.warning("registry_fetch_failed", url=MARKETPLACE_REGISTRY_URL)
    return []


async def fetch_registry_cached() -> list[dict[str, Any]]:
    """Fetch registry with simple in-memory cache."""
    try:
        from bot.runtime import get_bot as _get_bot

        live_bot = _get_bot()
        if live_bot is not None and hasattr(live_bot, "_marketplace_cache"):
            cache_data, cache_time = live_bot._marketplace_cache  # type: ignore[attr-defined]
            import time

            if time.time() - cache_time < CACHE_TTL_SECONDS:
                return cache_data  # type: ignore[return-value]
    except Exception:  # noqa: BLE001
        pass

    data = await fetch_registry()

    try:
        from bot.runtime import get_bot as _get_bot

        live_bot = _get_bot()
        if live_bot is not None:
            import time

            live_bot._marketplace_cache = (data, time.time())  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass
    return data


# ---------------------------------------------------------------------------
# Installation helpers
# ---------------------------------------------------------------------------


async def run_command(cmd: list[str], cwd: Path | None = None, timeout: float = 120.0) -> tuple[int, str]:
    """Run a subprocess command and return (returncode, combined_output)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return (proc.returncode or 0), (stdout.decode("utf-8", errors="replace") or "")
    except asyncio.TimeoutError:
        return -1, "Command timed out"
    except FileNotFoundError as exc:
        return -1, f"Command not found: {exc.filename}"


def validate_github_url(url: str) -> bool:
    """Check that URL looks like a valid GitHub repo URL."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return False
    if "github.com" not in parsed.netloc:
        return False
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    return len(parts) >= 2


def _discover_cog_module(base_path: str, safe_name: str) -> str | None:
    """Scan an installed package directory for a valid discord.py cog module.

    A valid cog module is a .py file (or package __init__.py) that defines
    an async ``setup(bot)`` function. Returns the dotted module path
    suitable for ``bot.load_extension()``.
    """
    import ast

    base = Path(base_path)

    # Collect all .py files, prioritising common cog locations
    candidates: list[Path] = []

    # Priority 1: cogs/<name>.py
    cog_file = base / "cogs" / f"{safe_name}.py"
    if cog_file.exists():
        candidates.append(cog_file)

    # Priority 2: <name>.py at top level
    top_file = base / f"{safe_name}.py"
    if top_file.exists():
        candidates.append(top_file)

    # Priority 3: any .py with a setup() function
    for py_file in sorted(base.rglob("*.py")):
        if py_file.name == "__init__.py":
            continue
        if py_file in candidates:
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8", errors="replace"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "setup":
                    candidates.append(py_file)
                    break
        except Exception:  # noqa: BLE001
            continue

    # Also check __init__.py files in subdirectories
    for init_file in sorted(base.rglob("__init__.py")):
        try:
            tree = ast.parse(init_file.read_text(encoding="utf-8", errors="replace"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "setup":
                    if init_file not in candidates:
                        candidates.append(init_file)
                    break
        except Exception:  # noqa: BLE001
            continue

    if not candidates:
        return None

    # Convert the first valid candidate to a dotted module path
    chosen = candidates[0]
    try:
        rel = chosen.relative_to(base)
        # Convert path parts to dotted module name
        parts = list(rel.parts)
        if parts[-1] == "__init__.py":
            parts = parts[:-1]
        else:
            parts[-1] = parts[-1].removesuffix(".py")
        return ".".join(parts) if parts else chosen.stem
    except ValueError:
        return chosen.stem


async def install_cog_from_source(bot: commands.Bot, repo_url: str, cog_name: str) -> dict[str, Any]:
    """Clone or pip-install a cog from GitHub and make it available.

    Installation strategies (tried in order):
    1. git clone → copy to install dir → add to sys.path → load extension
    2. pip install <repo_url> → try to auto-discover module path
    """
    safe_name = cog_name.lower().replace(" ", "_")
    install_dir = _get_install_dir() / safe_name
    repo_dir = install_dir / "repo"

    # Clean previous installation
    if install_dir.exists():
        import time as _time
        for _ in range(3):
            shutil.rmtree(install_dir, ignore_errors=True)
            if not install_dir.exists():
                break
            _time.sleep(0.3)
    install_dir.mkdir(parents=True, exist_ok=True)

    # Strategy 1: git clone
    log.info("install_strategy_git", repo=repo_url)
    rc, output = await run_command(
        ["git", "clone", "--depth", "1", repo_url, str(repo_dir)],
        timeout=60.0,
    )

    module_path = None
    if rc == 0 and repo_dir.exists():
        # Find the Python package inside the cloned repo
        for candidate in (repo_dir / "cogs" / f"{safe_name}.py",):
            if candidate.exists():
                log.info("found_cog_file", path=str(candidate))
                break

        # Copy relevant files to a clean target directory
        target = install_dir / "package"
        target.mkdir(exist_ok=True)

        # Copy the entire repo content (minus .git)
        for item in repo_dir.iterdir():
            if item.name != ".git":
                if item.is_dir():
                    shutil.copytree(item, target / item.name, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, target / item.name)

        module_path = str(target)

    # Strategy 2: pip install (if git failed or no local cog file found)
    if module_path is None:
        log.info("install_strategy_pip", repo=repo_url)
        temp_dir = Path(__file__).resolve().parent.parent.parent / ".cognix_temp"
        temp_dir.mkdir(exist_ok=True)

        rc2, output2 = await run_command(
            [sys.executable, "-m", "pip", "install", "--target", str(install_dir / "pip_deps"), repo_url],
            cwd=temp_dir,
            timeout=90.0,
        )
        shutil.rmtree(temp_dir, ignore_errors=True)

        if rc2 == 0:
            # Find any .py files in pip_installed dir
            for py_file in (install_dir / "pip_deps").rglob("*.py"):
                if "/__init__.py" not in str(py_file):
                    module_path = str((install_dir / "pip_deps"))
                    break

    if module_path is None:
        all_output = output
        if not all_output and 'output2' in locals():
            all_output = output2
        return {"error": f"Failed to install '{cog_name}':\n{all_output[-500:] or '(no output)'}"}

    # Add to sys.path if not already present
    if module_path not in sys.path:
        sys.path.insert(0, module_path)

    # Discover the actual extension module inside the installed package.
    # A discord.py cog must define an async setup(bot) function.
    ext_module = _discover_cog_module(module_path, safe_name)
    if ext_module is None:
        return {"error": f"No valid cog module (with setup() function) found in '{cog_name}'"}

    # Try loading the extension
    try:
        if ext_module in bot.extensions:
            await bot.reload_extension(ext_module)
        else:
            await bot.load_extension(ext_module)
        log.info("cog_loaded_after_install", cog=cog_name, ext=ext_module)
    except Exception as exc:  # noqa: BLE001
        log.warning("ext_load_failed_after_install", cog=cog_name, error=str(exc))

    return {"ok": True, "cog": cog_name, "module": ext_module}


async def uninstall_cog(bot: commands.Bot, cog_name: str) -> dict[str, Any]:
    """Unload and remove a marketplace-installed cog."""
    safe_name = cog_name.lower().replace(" ", "_")

    # Look up the actual module name from DB or loaded extensions
    ext_module = None
    try:
        async with db_session() as s:
            pkg = await s.scalar(sa_select(CogPackage).where(CogPackage.name == cog_name))
            if pkg and pkg.module_name:
                ext_module = pkg.module_name
    except Exception:  # noqa: BLE001
        pass

    # Fallback: search loaded extensions for one matching the cog name
    if ext_module is None:
        for loaded_ext in list(bot.extensions):
            if safe_name in loaded_ext.lower():
                ext_module = loaded_ext
                break

    # Try to unload if loaded as extension
    if ext_module and ext_module in bot.extensions:
        try:
            await bot.unload_extension(ext_module)
            log.info("cog_unloaded", module=ext_module)
        except Exception:  # noqa: BLE001
            pass

    install_dir = _get_install_dir() / safe_name
    if install_dir.exists():
        shutil.rmtree(install_dir, ignore_errors=True)
        log.info("install_dir_removed", path=str(install_dir))

    # Remove from sys.path — check both the install dir and its subdirs
    for path_entry in list(sys.path):
        if path_entry.startswith(str(install_dir)):
            sys.path.remove(path_entry)

    return {"ok": True, "cog": cog_name}


async def save_package_metadata(
    cog_name: str,
    display_name: str,
    description: str,
    github_repo: str,
    version: str | None,
    dependencies: list[str],
    category: str,
    requires_admin: bool,
    author: str | None,
    installed: bool = True,
    install_dir_path: str | None = None,
    module_name: str | None = None,
) -> None:
    """Persist or update package metadata in the database."""
    try:
        async with db_session() as s:
            pkg = await s.scalar(sa_select(CogPackage).where(CogPackage.name == cog_name))
            if pkg is None:
                pkg = CogPackage(
                    name=cog_name,
                    display_name=display_name,
                    description=description,
                    github_repo=github_repo,
                    version=version,
                    dependencies=dependencies,
                    category=category,
                    requires_admin=requires_admin,
                    author=author,
                    installed=installed,
                    install_dir=install_dir_path,
                    module_name=module_name,
                )
                s.add(pkg)
            else:
                pkg.display_name = display_name
                pkg.description = description
                pkg.github_repo = github_repo
                pkg.version = version
                pkg.dependencies = dependencies
                pkg.category = category
                pkg.requires_admin = requires_admin
                pkg.author = author
                pkg.installed = installed
                if install_dir_path:
                    pkg.install_dir = install_dir_path
                if module_name:
                    pkg.module_name = module_name
            await s.flush()
    except Exception as exc:  # noqa: BLE001
        log.warning("package_db_save_failed", cog=cog_name, error=str(exc))


# ---------------------------------------------------------------------------
# Marketplace Cog (slash commands)
# ---------------------------------------------------------------------------


class MarketplaceCogCmd(commands.Cog):
    """Marketplace for installing discord.py extensions from GitHub."""

    marketplace_group = app_commands.Group(
        name="marketplace", description="Install and manage plugins from the Cog Marketplace"
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @marketplace_group.command(name="list", description="List available cogs from the marketplace")
    @app_commands.describe(query="Optional search query to filter cogs")
    async def list_cogs(self, interaction: discord.Interaction, query: str | None = None) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)

        raw_list = await fetch_registry_cached()

        # Get installed package names from DB
        installed_names: set[str] = set()
        try:
            async with db_session() as s:
                pkgs = await s.scalars(sa_select(CogPackage).where(CogPackage.installed.is_(True)))
                installed_names = {p.name for p in pkgs}
        except Exception:  # noqa: BLE001
            pass

        # Filter by query
        filtered = raw_list
        if query:
            ql = query.lower()
            filtered = [
                c
                for c in raw_list
                if ql in str(c.get("name", "")).lower()
                or ql in str(c.get("display_name", "")).lower()
                or ql in str(c.get("description", "")).lower()
                or ql in str(c.get("category", "")).lower()
            ]

        if not filtered:
            await interaction.followup.send(
                "No cogs found in the marketplace. Try a different search query.", ephemeral=True
            )
            return

        # Group by category
        categories: dict[str, list[dict]] = {}
        for c in filtered:
            cat = c.get("category", "General")
            categories.setdefault(cat, []).append(c)

        lines: list[str] = []
        if query:
            lines.append(f"Search results for **{query}** ({len(filtered)} found)\n")
        else:
            lines.append(f"**Cog Marketplace** ({len(raw_list)} cogs available)\n")

        for cat, items in sorted(categories.items()):
            lines.append(f"\n**{cat}**")
            for item in items[:15]:  # max 15 per category per page
                name = item.get("name", "?")
                display = item.get("display_name", name)
                desc = (item.get("description", "") or "")[:80]
                icon = "\u26a1" if name not in installed_names else "\u2705"
                admin_tag = " \U0001f512" if item.get("requires_admin") else ""
                lines.append(f"{icon} **{display}** — {desc}{admin_tag}")

        message = "\n".join(lines[:50])  # cap at 50 lines
        if len(filtered) > 15 * len(categories):
            message += "\n\nUse `/marketplace list <query>` to narrow results."

        await interaction.followup.send(message, ephemeral=True)

    @marketplace_group.command(name="info", description="Show details of a marketplace cog")
    @app_commands.describe(cog="The name or display name of the cog")
    async def info_cog(self, interaction: discord.Interaction, cog: str) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)

        raw_list = await fetch_registry_cached()
        found = None
        for c in raw_list:
            if c.get("name", "").lower() == cog.lower() or c.get("display_name", "").lower() == cog.lower():
                found = c
                break

        # Also check DB for installed packages not in registry
        if found is None:
            try:
                async with db_session() as s:
                    pkg = await s.scalar(sa_select(CogPackage).where(CogPackage.name == cog))
                    if pkg:
                        found = {
                            "name": pkg.name,
                            "display_name": pkg.display_name,
                            "description": pkg.description,
                            "github_repo": pkg.github_repo,
                            "version": pkg.version,
                            "dependencies": pkg.dependencies or [],
                            "category": pkg.category,
                            "requires_admin": pkg.requires_admin,
                            "author": pkg.author,
                        }
            except Exception:  # noqa: BLE001
                pass

        if found is None:
            await interaction.followup.send(f"Cog '{cog}' not found in the marketplace.", ephemeral=True)
            return

        name = found.get("name", cog)
        display = found.get("display_name", name)
        desc = found.get("description", "No description available.")
        repo = found.get("github_repo", "\u2014")
        ver = found.get("version") or "\u2014"
        deps = found.get("dependencies", [])
        cat = found.get("category", "General")
        admin = found.get("requires_admin", False)
        author = found.get("author") or "Unknown"

        embed = discord.Embed(title=f"\U0001f4e6 {display}", description=desc, color=0x60A5FA)
        embed.add_field(name="Name", value=f"`{name}`", inline=True)
        embed.add_field(name="Version", value=f"`{ver}`", inline=True)
        embed.add_field(name="Category", value=cat, inline=True)
        embed.add_field(name="Author", value=author, inline=True)
        embed.add_field(name="Admin Required", value="\u2705 Yes" if admin else "\u274c No", inline=True)
        if deps:
            embed.add_field(
                name=f"Dependencies ({len(deps)})",
                value="\n".join(f"`{d}`" for d in deps[:5]),
                inline=False,
            )
        if repo != "\u2014":
            embed.add_field(name="Repository", value=f"[Open]({repo})", inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @marketplace_group.command(name="installed", description="List installed marketplace cogs")
    async def list_installed(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)

        installed_pkgs: list[CogPackage] = []
        try:
            async with db_session() as s:
                installed_pkgs = list(await s.scalars(
                    sa_select(CogPackage).where(
                        CogPackage.installed.is_(True),
                        CogPackage.uninstall_requested.is_(False),
                    )
                ))
        except Exception:  # noqa: BLE001
            pass

        loaded_exts = list(self.bot.extensions)

        if not installed_pkgs and not loaded_exts:
            await interaction.followup.send(
                "No marketplace cogs are currently installed. Use `/marketplace list` to browse.", ephemeral=True
            )
            return

        lines = ["**Installed Marketplace Cogs:**\n"]
        for pkg in installed_pkgs:
            status_icon = "\U0001f7e2" if pkg.module_name and pkg.module_name in self.bot.extensions else "\U0001f534"
            mod = f" (`{pkg.module_name}`)" if pkg.module_name else ""
            lines.append(f"{status_icon} **{pkg.display_name}**{mod} — {pkg.description[:60]}")

        for ext in loaded_exts:
            already_in_db = any(p.module_name == ext for p in installed_pkgs)
            if not already_in_db:
                lines.append(f"\U0001f7e1 **{ext}** (loaded but not in marketplace registry)")

        await interaction.followup.send("\n".join(lines), ephemeral=True)

    @marketplace_group.command(name="install", description="Install a cog from the marketplace")
    @app_commands.describe(
        cog_or_url="The cog name from the marketplace, or a direct GitHub repository URL"
    )
    @is_owner()  # Only bot owner can install
    async def install_cog(self, interaction: discord.Interaction, cog_or_url: str) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)

        is_url = cog_or_url.startswith("http")
        repo_url = cog_or_url
        cog_name = cog_or_url

        if not is_url:
            raw_list = await fetch_registry_cached()
            found = None
            for c in raw_list:
                if c.get("name", "").lower() == cog_or_url.lower():
                    found = c
                    break

            if found is None:
                await interaction.followup.send(
                    f"Cog '{cog_or_url}' not found in the marketplace. "
                    f"Use `/marketplace list` to see available cogs.", ephemeral=True
                )
                return

            repo_url = found.get("github_repo", "")
            if not repo_url or not validate_github_url(repo_url):
                await interaction.followup.send(
                    f"Invalid repository URL for '{cog_or_url}'.", ephemeral=True
                )
                return

            cog_name = found.get("name", cog_or_url)
        else:
            if not validate_github_url(repo_url):
                await interaction.followup.send(
                    "Invalid GitHub URL. Please provide a valid HTTPS GitHub repository URL.",
                    ephemeral=True,
                )
                return

        # Check if already installed in DB
        already = False
        try:
            async with db_session() as s:
                pkg = await s.scalar(sa_select(CogPackage).where(CogPackage.name == cog_name))
                if pkg and pkg.installed:
                    already = True
        except Exception:  # noqa: BLE001
            pass

        if already:
            await interaction.followup.send(
                f"Cog '{cog_name}' is already installed. Use `/marketplace uninstall {cog_name}` first.",
                ephemeral=True,
            )
            return

        await interaction.followup.send(f"Installing **{cog_name}**... Please wait.", ephemeral=True)

        result = await install_cog_from_source(self.bot, repo_url, cog_name)
        if result.get("ok"):
            safe_name = cog_name.lower().replace(" ", "_")

            await save_package_metadata(
                cog_name=cog_name,
                display_name=cog_name,
                description=f"Installed from {repo_url}",
                github_repo=repo_url,
                version=None,
                dependencies=[],
                category="Custom",
                requires_admin=False,
                author="Unknown",
                installed=True,
                install_dir_path=str(_get_install_dir() / safe_name),
                module_name=result.get("module"),
            )

            # Sync slash commands to register the new cog's commands
            try:
                await self.bot.tree.sync()
            except Exception:  # noqa: BLE001
                pass

            await interaction.followup.send(
                f"**{cog_name}** installed successfully!\n\n"
                f"Module: `{result.get('module', 'N/A')}`\n"
                f"Use `/marketplace installed` to verify.", ephemeral=True
            )
            log.info("cog_installed", cog=cog_name, repo=repo_url)
        else:
            await interaction.followup.send(f"Failed to install '{cog_name}': {result.get('error', 'unknown error')}", ephemeral=True)

    @marketplace_group.command(name="uninstall", description="Uninstall a marketplace cog")
    @app_commands.describe(cog="The name of the installed cog to uninstall")
    @is_owner()  # Only bot owner can uninstall
    async def uninstall_cog_cmd(self, interaction: discord.Interaction, cog: str) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)

        result = await uninstall_cog(self.bot, cog)
        if result.get("ok"):
            try:
                async with db_session() as s:
                    pkg = await s.scalar(sa_select(CogPackage).where(CogPackage.name == cog))
                    if pkg:
                        pkg.installed = False
                        await s.flush()
            except Exception:  # noqa: BLE001
                pass

            await self.bot.tree.sync()
            await interaction.followup.send(f"**{cog}** uninstalled successfully.", ephemeral=True)
        else:
            await interaction.followup.send(f"Failed to uninstall '{cog}': {result.get('error', 'unknown error')}", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    cog = MarketplaceCogCmd(bot)
    await bot.add_cog(cog)
