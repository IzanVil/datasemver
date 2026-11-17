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


def test_the_description_fits_what_the_marketplace_takes(action):
    """125 characters, refused at 126 -- and only when someone tries to publish.

    The listing is edited through a form that validates on submit, so a description that grew
    past the limit is found by a person clicking Publish months later, with nothing in the
    repository saying why it will not go. One assertion moves that to the commit that does it.
    """
    description = " ".join(action["description"].split())

    assert len(description) < 125, f"{len(description)} characters"


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


def test_the_version_is_written_only_when_asked_for(action):
    """Opt in, off by default: every repository already running the action expects no writes."""
    assert action["inputs"]["write-version"]["default"] == "false"


def test_the_write_flag_reaches_the_script_through_the_environment(action):
    analyse = named(action, "analyse")

    assert analyse["env"]["WRITE_VERSION"] == "${{ inputs.write-version }}"
    assert "--write-version" in analyse["run"]
    assert "${{" not in analyse["run"]


def test_the_files_that_changed_are_an_output(action):
    """What a later step stages, so it commits those and not whatever else the job touched."""
    output = action["outputs"]["version-files"]

    assert output["value"] == "${{ steps.analyse.outputs.version_files }}"


def test_the_action_never_commits_or_pushes(action):
    """Writing back to a branch is the workflow's decision, and this is why it is not ours.

    A commit pushed with the job's own token starts no workflow, so the checks a protected
    branch requires would never run on it; a fork's token cannot push at all. Both are the
    caller's to resolve, with the token and the branch they choose -- the action records the
    number in the checkout and names the files, and stops there.
    """
    for step in steps(action):
        script = step.get("run", "")
        assert "git commit" not in script, step["name"]
        assert "git push" not in script, step["name"]
        assert "git add" not in script, step["name"]


# --- what the analyse step hands the script ------------------------------------------------------
#
# Run for real, under bash, with a stand-in for `python` that writes down what it was given:
# what is being checked is word splitting, and reading the script does not show it.


def arguments_given(action, tmp_path, **environment):
    """Run the analyse step and return the arguments its script was called with."""
    import os
    import shutil
    import subprocess
    import sys

    if sys.platform == "win32" or shutil.which("bash") is None:
        pytest.skip("the step is run under bash")

    binaries = tmp_path / "bin"
    binaries.mkdir()
    recorded = tmp_path / "arguments.txt"
    stand_in = binaries / "python"
    stand_in.write_text(
        "#!/bin/sh\nshift\n"
        'for argument in "$@"; do printf \'%s\\n\' "$argument"; done > "$RECORD"\n',
        encoding="utf-8",
    )
    stand_in.chmod(0o755)
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "decoy.csv").write_text("a\n1\n", encoding="utf-8")

    defaults = {
        "BASE_REF": "origin/main",
        "REPORT_PATH": str(tmp_path / "report.md"),
        "DEFAULT_VERSION": "0.0.0",
        "FAIL_ON": "",
        "RULES": "",
        "PATHS": "",
        "WRITE_VERSION": "false",
    }
    subprocess.run(
        ["bash", "-eo", "pipefail", "-c", named(action, "analyse")["run"]],
        cwd=checkout,
        check=True,
        env={
            **defaults,
            **environment,
            "PATH": f"{binaries}{os.pathsep}{os.environ['PATH']}",
            "RECORD": str(recorded),
            "GITHUB_ACTION_PATH": str(tmp_path),
            "GITHUB_OUTPUT": str(tmp_path / "output.txt"),
        },
    )
    return recorded.read_text(encoding="utf-8").splitlines()


def paths_given(arguments):
    return arguments[arguments.index("--paths") + 1 :] if "--paths" in arguments else []


def test_paths_on_one_line_are_split_on_spaces_as_they_always_were(action, tmp_path):
    arguments = arguments_given(action, tmp_path, PATHS="data/a.csv  data/b.csv")

    assert paths_given(arguments) == ["data/a.csv", "data/b.csv"]


def test_paths_one_per_line_keep_the_spaces_inside_them(action, tmp_path):
    arguments = arguments_given(
        action, tmp_path, PATHS="data/monthly sales.csv\n\n  data/b.csv  \n"
    )

    assert paths_given(arguments) == ["data/monthly sales.csv", "data/b.csv"]


def test_a_pattern_in_paths_is_not_expanded_against_the_checkout(action, tmp_path):
    """`decoy.csv` is in the working directory, which is what `*` would have become."""
    assert paths_given(arguments_given(action, tmp_path, PATHS="*.csv")) == ["*.csv"]
    second = tmp_path / "second"
    second.mkdir()
    assert paths_given(arguments_given(action, second, PATHS="*\n?")) == ["*", "?"]


def test_no_paths_means_no_option_and_the_rest_arrives_whole(action, tmp_path):
    arguments = arguments_given(
        action,
        tmp_path,
        RULES="rules/my rules.yaml",
        FAIL_ON="major",
        WRITE_VERSION="true",
        BASE_REF="origin/release 1",
    )

    assert "--paths" not in arguments
    assert arguments[:2] == ["--base-ref", "origin/release 1"]
    assert arguments[arguments.index("--rules") + 1] == "rules/my rules.yaml"
    assert arguments[arguments.index("--fail-on") + 1] == "major"
    assert "--write-version" in arguments
