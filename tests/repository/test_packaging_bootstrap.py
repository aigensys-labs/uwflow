"""Tests for clean-checkout editable installation and packaging output paths."""

from __future__ import annotations

from configparser import ConfigParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_setuptools_metadata_base_exists_in_a_clean_source_package() -> None:
    config = ConfigParser()
    assert config.read(ROOT / "setup.cfg") == [str(ROOT / "setup.cfg")]

    egg_base = Path(config.get("egg_info", "egg_base"))
    assert egg_base == Path("var")
    assert (ROOT / egg_base).is_dir()
    assert (ROOT / egg_base / "README.md").is_file()

    # Editable installation must not depend on a generated var/build directory.
    assert egg_base != Path("var/build")
    assert "include var/README.md" in (ROOT / "MANIFEST.in").read_text(encoding="utf-8")


def test_setuptools_build_outputs_remain_inside_var() -> None:
    config = ConfigParser()
    config.read(ROOT / "setup.cfg")

    assert Path(config.get("build", "build_base")) == Path("var/build")
    assert Path(config.get("sdist", "dist_dir")) == Path("var/dist")
    assert Path(config.get("bdist_wheel", "dist_dir")) == Path("var/dist")
