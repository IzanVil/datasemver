# Security Policy

## Reporting a vulnerability

Report privately through GitHub, under **Security → Report a vulnerability** on this
repository, rather than opening a public issue. Include the version, the input that triggers
the problem, and what you expected instead. Expect an acknowledgement within a few days.

Please do not include real data in a report. A minimal file that reproduces the behaviour is
more useful than a large one, and safer for both of us.

## Supported versions

Fixes land on `main` and ship in the next release. Only the latest release is patched; there
are no maintained branches for older versions.

| Version | Supported |
| --- | --- |
| The latest release | yes |
| Anything older | no |

## What DataSemver does with the files you give it

The tool exists to read data nobody has vouched for, so it is worth being explicit about
what that means.

- **Reading a dataset parses it.** CSV and JSON are parsed by pandas and the standard
  library, which do not execute file content. Parquet is parsed by pyarrow, and the floor is
  `pyarrow>=23.0.1` because that is the first version clear of every advisory against it.
  CVE-2023-47248, rated critical, allowed arbitrary code execution while reading a malicious
  Parquet file. Do not lower that floor.
- **Rule files are YAML, loaded with `yaml.safe_load`.** No Python object is constructed
  from a rules file, so a rule set cannot execute code. Unknown rule names are rejected
  rather than ignored.
- **Nothing is written unless you ask.** `datasemver diff` writes only with `--output`, and
  only the changelog entry.
- **No network access of their own.** The library and the CLI open a socket only to read a
  database, when you give them a connection URL. Nothing is fetched, reported or checked for
  updates.

## Running the dashboard

The dashboard in `web/` is a local tool. It has no authentication, no authorisation and no
rate limiting, and it reads whatever is in `DATASEMVER_DATASETS_DIR`. Anyone who can reach
the port can read every dataset in that directory and spend CPU on analysis.

Bind it to the loopback interface, which is uvicorn's default:

```bash
uvicorn datasemver_web.backend.main:app          # 127.0.0.1, correct
uvicorn datasemver_web.backend.main:app --host 0.0.0.0   # exposed, only behind something that authenticates
```

Uploads are capped by `DATASEMVER_MAX_UPLOAD_MB` (25 MB by default) and the cap is applied
while the body is written, so a rejected upload costs at most one byte past the limit. That
bounds the disk a single request can use; it does not bound how many requests arrive. Put a
reverse proxy in front of anything reachable beyond your own machine.

What a file becomes is held to a limit as well, because the size that arrives says little about
what reading it costs. A gzip file is measured once decompressed against the cap itself;
Parquet, Feather and Excel, which are compressed on purpose, against twenty times it, decoded
a batch at a time so that finding out is not the attack. A table is refused past
`DATASEMVER_MAX_COLUMNS` columns (2,000 by default), since each column costs the same
whatever it holds. Every analysis runs off the server's event loop, so one does not hold up
the next request.

The dashboard also answers only to the names a browser has no way to borrow. A web page can
make your browser talk to `127.0.0.1`, and a hostname it controls that resolves there after the
page has loaded would let it read the answers too -- DNS rebinding. A request is refused with a
400 unless its `Host` is `localhost`, an IP address, or a name listed in
`DATASEMVER_ALLOWED_HOSTS` (comma separated, or `*` to turn the check off), which is what to
set when a reverse proxy serves it under a name of its own. Every response carries a
`Content-Security-Policy` that allows the page nothing but itself, and `nosniff`, a
same-origin frame policy and no referrer.

## The GitHub Action

Releases are published through Trusted Publishing rather than an API token: the workflow
mints a short-lived OIDC credential naming the repository, workflow and environment it came
from, and the index verifies that. There is no long-lived publishing secret in this
repository to steal. Every action is pinned to a commit SHA, so a moved tag cannot change
what runs in the job that holds that credential.

`scripts/run_datasemver_on_pr.py` and the workflow that calls it run on `pull_request`, not
`pull_request_target`. A pull request from a fork therefore gets a read-only token and no
secrets, and the step that posts the comment is skipped for forks. Event values reach the
shell through the environment rather than `${{ }}` interpolation, so a branch named to look
like shell is data, not script.

The comment is posted under the repository's own bot and its contents are chosen by whoever
opened the pull request: a path, a column heading, a version file. Everything of theirs in it
is set inside a code span, where Markdown, HTML and `@` mentions are only characters, and the
paths in "Reproduce locally" are quoted for the shell, so copying that block cannot run
anything a branch put there. A dataset that is a symbolic link out of the checkout is skipped
rather than read, and a version file that is one is not written through. The other workflows
do not keep the checkout token in `.git/config`, and every job has a time limit.
