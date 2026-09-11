"""Tests for the published action, which nothing else here can run.

`action.yml` is what `uses: IzanVil/datasemver@v1` executes in someone else's repository. It
never runs in this suite -- there is no GitHub around it -- so what is asserted is the set of
things that are silently wrong rather than loudly broken: a step order that posts the refusal
instead of the report, an action pinned to a tag someone else can move, an input the workflow
passes and the action does not have, a path to a script that moved.

The real check is the next pull request against this repository, which runs the action from
the working tree for exactly that reason.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
ACTION = ROOT / "action.yml"
WORKFLOW = ROOT / ".github" / "workflows" / "datasemver.yml"

# MANIFEST.in prunes both from the sdist, where this file still travels.
if not ACTION.is_file() or not WORKFLOW.is_file():
    pytest.skip("the action is not shipped in the sdist", allow_module_level=True)

PINNED = re.compile(r"^[\w.-]+/[\w.-]+@[0-9a-f]{40}$")


@pytest.fixture(scope="module")
def action() -> dict:
    return yaml.safe_load(ACTION.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def steps(action: dict) -> list[dict]:
    return action["runs"]["steps"]


def named(action: dict, fragment: str) -> dict:
    return next(step for step in steps(action) if fragment in step["name"].lower())


def test_the_action_is_a_composite_one(action):
    assert action["runs"]["using"] == "composite"
    assert action["name"] and action["description"]


def test_every_action_it_uses_is_pinned_to_a_commit(action):
    """A tag is a movable pointer, and this one runs in other people's repositories."""
    used = [step["uses"] for step in steps(action) if "uses" in step]

    assert used, "the action stopped using anything, which is worth noticing"
    for reference in used:
        assert PINNED.match(reference), reference


def test_every_shell_step_says_which_shell(action):
    """A composite step without `shell` fails at the point of use, not here."""
    for step in steps(action):
        if "run" in step:
            assert step.get("shell") == "bash", step["name"]


def test_the_script_it_runs_is_where_it_says(action):
    """The one path in the file that no YAML parser would catch."""
    command = named(action, "analyse")["run"]
    referenced = re.findall(r"\$GITHUB_ACTION_PATH/(\S+\.py)", command)

    assert referenced == ["scripts/run_datasemver_on_pr.py"]
    assert (ROOT / referenced[0]).is_file()


def test_the_report_is_posted_before_the_refusal(action):
    """A refusal that suppressed its own explanation blocks a merge and never says why."""
    order = [step["name"].lower() for step in steps(action)]

    assert order.index("comment on the pull request") < order.index("refuse the change")


def test_the_refusal_is_reached_through_an_output_rather_than_a_failure(action):
    """`continue-on-error` does not exist in a composite step, so the gate carries itself."""
    analyse = named(action, "analyse")
    refuse = named(action, "refuse")

    assert "continue-on-error" not in analyse
    assert "refused" in analyse["run"]
    assert refuse["if"] == "steps.analyse.outputs.refused == 'true'"


def test_a_fork_is_never_commented_on(action):
    """A pull request from a fork has a read-only token, and the report is printed anyway."""
    condition = named(action, "comment")["if"]

    assert "github.event.pull_request.head.repo.full_name == github.repository" in condition
    assert "inputs.comment == 'true'" in condition


def test_event_values_reach_the_shell_through_the_environment(action):
    """Interpolated inline, a ref named to look like shell would run as shell."""
    resolve = named(action, "resolve")

    assert "${{" not in resolve["run"]
    assert set(resolve["env"]) >= {"GIVEN", "EVENT_NAME", "BASE_REF", "BEFORE"}


def test_every_output_comes_from_a_step_that_exists(action):
    """An output wired to a renamed step reports an empty string, which reads as `none`."""
    ids = {step["id"] for step in steps(action) if "id" in step}

    for name, output in action["outputs"].items():
        step_id = re.search(r"steps\.([\w-]+)\.outputs", output["value"])
        assert step_id, name
        assert step_id.group(1) in ids, name


def test_the_duckdb_extra_is_installed_only_for_the_engines_that_need_it(action):
    install = named(action, "install")["run"]

    assert "[duckdb]" in install
    assert "$GITHUB_ACTION_PATH" in install


def test_this_repository_runs_its_own_action(workflow):
    """The first user of the action is the repository publishing it."""
    used = [step.get("uses") for step in workflow["jobs"]["analyse"]["steps"]]

    assert "./" in used


def test_the_workflow_only_passes_inputs_the_action_declares(action, workflow):
    """A renamed input is accepted in silence and ignored, which is the worst of both."""
    step = next(step for step in workflow["jobs"]["analyse"]["steps"] if step.get("uses") == "./")

    assert set(step.get("with", {})) <= set(action["inputs"])


def test_the_checkout_before_it_carries_the_history_it_needs(workflow):
    checkout = workflow["jobs"]["analyse"]["steps"][0]

    assert checkout["with"]["fetch-depth"] == 0
