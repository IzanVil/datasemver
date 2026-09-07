"""Tests for the release workflow's authentication with the package indexes.

Publishing is authenticated by Trusted Publishing: the job mints a short-lived OpenID
Connect token naming the repository, the workflow file and the environment it came from,
and the index checks that against what it was told to expect. Everything that arrangement
depends on is a line in a YAML file that nothing else reads, so a plausible edit can undo
it silently — a `password:` restored from an older example disables the attestations the
action produces, a dropped `id-token: write` fails the job, and a renamed environment fails
it in a way that reads like a misconfigured index rather than a typo here. The real check
is the next release; these are the parts worth knowing about before then.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "publish.yml"

# MANIFEST.in prunes `.github` from the sdist and ships `tests` in it, so this file travels
# to where the workflow it reads does not exist. Skipping keeps that a packaging fact rather
# than eleven errors and a failure against a source tree that is intact.
if not WORKFLOW.is_file():
    pytest.skip("the workflows are not shipped in the sdist", allow_module_level=True)

PUBLISH_ACTION = "pypa/gh-action-pypi-publish"

# The environment name is half of what each index verifies, so these are the names
# configured under Publishing on PyPI and TestPyPI, not free-form labels.
PUBLISH_JOBS = {"publish-testpypi": "testpypi", "publish-pypi": "pypi"}


@pytest.fixture(scope="module")
def workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def publish_steps(job: dict) -> list[dict]:
    return [step for step in job["steps"] if step.get("uses", "").startswith(PUBLISH_ACTION)]


def test_the_workflow_is_valid_yaml(workflow):
    assert workflow["jobs"]


@pytest.mark.parametrize("job_name", PUBLISH_JOBS)
def test_publishing_carries_no_password(workflow, job_name):
    """A password would authenticate the upload and discard the attestations with it."""
    for step in publish_steps(workflow["jobs"][job_name]):
        assert "password" not in step.get("with", {})


@pytest.mark.parametrize("job_name", PUBLISH_JOBS)
def test_publishing_can_mint_the_token_it_authenticates_with(workflow, job_name):
    assert workflow["jobs"][job_name]["permissions"]["id-token"] == "write"


def test_the_tag_check_covers_every_way_a_tag_is_published(workflow):
    """It ran only on `release`, so a publish dispatched from a tag skipped it entirely.

    That is the path the last three releases actually took, which made the check look like
    cover it was not providing. Keying on the ref type covers both, and still skips the
    dispatch from a branch, where `GITHUB_REF_NAME` is a branch name and matches nothing.
    """
    steps = workflow["jobs"]["build"]["steps"]
    check = next(s for s in steps if s["name"].startswith("Verify the tag"))

    assert check["if"] == "github.ref_type == 'tag'"


def test_the_build_job_cannot_mint_that_token():
    """It builds the artifacts the publish jobs upload and has no reason to hold a credential."""
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))

    assert "id-token" not in workflow["jobs"]["build"].get("permissions", {})


@pytest.mark.parametrize(("job_name", "environment"), PUBLISH_JOBS.items())
def test_each_publish_job_runs_in_the_environment_its_index_expects(
    workflow, job_name, environment
):
    assert workflow["jobs"][job_name]["environment"]["name"] == environment


@pytest.mark.parametrize("job_name", PUBLISH_JOBS)
def test_republishing_a_version_is_a_no_op_rather_than_a_failure(workflow, job_name):
    """A re-run of a release should not fail on the version it already uploaded."""
    for step in publish_steps(workflow["jobs"][job_name]):
        assert step["with"]["skip-existing"] is True


@pytest.mark.parametrize("job_name", PUBLISH_JOBS)
def test_every_publish_job_publishes(workflow, job_name):
    """The parametrised tests above pass vacuously if a job stops using the action."""
    assert publish_steps(workflow["jobs"][job_name])
