"""Release workflow uses PyPI Trusted Publishing (OIDC) with separate testpypi / pypi environments."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from check_release_version import check

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github/workflows/release.yml"


def _wf() -> dict:
    data = yaml.safe_load(WF.read_text(encoding="utf-8"))
    # PyYAML reads the bare key `on` as True.
    data["on"] = data.pop(True, data.get("on"))
    return data


def test_single_release_workflow_file():
    assert WF.is_file()
    assert not (ROOT / ".github/workflows/testpypi.yml").exists(), "one workflow file per trusted publisher pair"


def test_workflow_triggers_and_default_permissions():
    wf = _wf()
    assert set(wf["on"]) == {"release", "workflow_dispatch"}
    assert wf["on"]["release"]["types"] == ["published"]
    assert wf["permissions"] == {"contents": "read"}


def test_publish_jobs_use_environments_and_oidc_only():
    jobs = _wf()["jobs"]
    test_job, prod_job = jobs["publish-testpypi"], jobs["publish-pypi"]
    assert test_job["environment"]["name"] == "testpypi"
    assert prod_job["environment"]["name"] == "pypi"
    for job in (test_job, prod_job):
        assert job["permissions"] == {"id-token": "write"}
        assert job["needs"] == "build"
        publish = [s for s in job["steps"] if str(s.get("uses", "")).startswith("pypa/gh-action-pypi-publish@")]
        assert len(publish) == 1
        assert "password" not in (publish[0].get("with") or {})
    assert test_job["steps"][-1]["with"]["repository-url"] == "https://test.pypi.org/legacy/"
    assert "github.event_name == 'release'" in prod_job["if"]
    assert "workflow_dispatch" in test_job["if"]
    assert "permissions" not in jobs["build"] or "id-token" not in jobs["build"]["permissions"]


def test_workflow_has_no_secrets():
    text = WF.read_text(encoding="utf-8")
    assert "secrets." not in text
    assert "PYPI_API_TOKEN" not in text


@pytest.mark.parametrize(
    "tag,ok",
    [("v2.2.1", True), ("2.2.1", True), ("v2.2.0", False), ("v2.2.1rc1", False), ("", True)],
)
def test_release_tag_must_match_package_version(tag: str, ok: bool):
    errors = check(ROOT, tag)
    assert (errors == []) is ok, errors
