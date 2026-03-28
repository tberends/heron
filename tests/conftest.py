"""Gedeelde pytest-fixtures voor de Heron-testsuite."""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
LAZ_FIXTURE_NAME = "X126000Y500000.laz"
# Zelfde plek als main.find_las_files("data/raw/"); reporoot is fallback (o.a. .gitignore).
LAZ_FIXTURE_CANDIDATES = (
    REPO_ROOT / "data" / "raw" / LAZ_FIXTURE_NAME,
    REPO_ROOT / LAZ_FIXTURE_NAME,
)


def resolve_laz_fixture_path() -> Path | None:
    for path in LAZ_FIXTURE_CANDIDATES:
        if path.is_file():
            return path
    return None


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "laz_fixture: tests die het repobestand X126000Y500000.laz nodig hebben",
    )


@pytest.fixture(scope="session")
def laz_fixture_path():
    """Absoluut pad naar het LAZ-tilebestand (data/raw/ of reporoot)."""
    found = resolve_laz_fixture_path()
    if found is not None:
        return found
    return LAZ_FIXTURE_CANDIDATES[0]


@pytest.fixture(scope="session")
def require_laz_fixture(laz_fixture_path):
    """Sla tests over als het LAZ-bestand ontbreekt (bijv. na gedeeltelijke checkout)."""
    found = resolve_laz_fixture_path()
    if found is None:
        opts = " of ".join(str(p) for p in LAZ_FIXTURE_CANDIDATES)
        pytest.skip(f"Ontbrekend testbestand {LAZ_FIXTURE_NAME}. Gezocht: {opts}.")
    return found
