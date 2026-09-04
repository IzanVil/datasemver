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
| 0.2.x | yes |
| < 0.2 | no |

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
- **No network access.** The library and the CLI never open a socket.

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

## The GitHub Action

`scripts/run_datasemver_on_pr.py` and the workflow that calls it run on `pull_request`, not
`pull_request_target`. A pull request from a fork therefore gets a read-only token and no
secrets, and the step that posts the comment is skipped for forks. Event values reach the
shell through the environment rather than `${{ }}` interpolation, so a branch named to look
like shell is data, not script.
