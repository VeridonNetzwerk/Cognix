"""Tests for database.models — model structure and imports."""

from __future__ import annotations


class TestSystemConfigModel:
    """Tests for SystemConfig model — verifies the JSON import bug is fixed."""

    def test_can_import_system_config(self):
        from database.models.system_config import SystemConfig
        assert SystemConfig is not None

    def test_system_config_tablename(self):
        from database.models.system_config import SystemConfig
        assert SystemConfig.__tablename__ == "system_config"

    def test_system_config_has_enabled_cogs_column(self):
        from database.models.system_config import SystemConfig
        # The column should be accessible as a class attribute
        assert hasattr(SystemConfig, "enabled_cogs")

    def test_system_config_has_configured_column(self):
        from database.models.system_config import SystemConfig
        assert hasattr(SystemConfig, "configured")


class TestServerConfigModel:
    """Tests for ServerConfig model."""

    def test_can_import_server_config(self):
        from database.models.server_config import ServerConfig
        assert ServerConfig is not None

    def test_server_config_tablename(self):
        from database.models.server_config import ServerConfig
        assert ServerConfig.__tablename__ == "server_configs"

    def test_server_config_has_enabled_cogs(self):
        from database.models.server_config import ServerConfig
        assert hasattr(ServerConfig, "enabled_cogs")


class TestCogPackageModel:
    """Tests for CogPackage model."""

    def test_can_import_cog_package(self):
        from database.models.cog_package import CogPackage
        assert CogPackage is not None

    def test_cog_package_tablename(self):
        from database.models.cog_package import CogPackage
        assert CogPackage.__tablename__ == "cog_packages"

    def test_cog_package_has_required_fields(self):
        from database.models.cog_package import CogPackage
        assert hasattr(CogPackage, "name")
        assert hasattr(CogPackage, "installed")
        assert hasattr(CogPackage, "github_repo")
