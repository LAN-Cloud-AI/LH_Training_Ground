"""Keep the released API identifier, Python package, and lockfile aligned."""

from importlib.metadata import version
from pathlib import Path
import os
import re
import tomllib

from csl_lab.version import RELEASE_VERSION
from csl_lab.webapp.app import app


ROOT = Path(__file__).resolve().parents[1]


def test_release_version_matches_package_and_api():
    match = re.fullmatch(r"(\d+\.\d+\.\d+)-beta\.(\d+)", RELEASE_VERSION)
    assert match, "Beta releases must use the component SemVer beta.N convention"
    python_version = f"{match[1]}b{match[2]}"
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    package = next(package for package in lock["package"] if package["name"] == "csl-lab")
    assert project["project"]["version"] == python_version
    assert package["version"] == python_version
    assert version("csl-lab") == python_version
    assert app.version == RELEASE_VERSION


def test_release_tag_matches_candidate_when_running_on_a_tag():
    if os.environ.get("GITHUB_REF_TYPE") == "tag":
        assert os.environ.get("GITHUB_REF_NAME") == f"training-ground-v{RELEASE_VERSION}"


def test_runtime_anyio_is_patched():
    installed = tuple(int(part) for part in version("anyio").split(".")[:3])
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    locked_version = next(package["version"] for package in lock["package"] if package["name"] == "anyio")
    locked = tuple(int(part) for part in locked_version.split(".")[:3])
    assert (4, 14, 2) <= installed < (5, 0, 0)
    assert (4, 14, 2) <= locked < (5, 0, 0)
