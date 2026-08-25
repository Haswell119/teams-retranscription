# Security policy

## Reporting a vulnerability

Report security issues privately through GitHub's
[private vulnerability reporting](https://github.com/Haswell119/teams-retranscription/security/advisories/new).
Please do not open a public issue.

Include what you did, what happened, and what you expected. If a proof of
concept requires audio, describe it rather than attaching real meeting content.

We will acknowledge within five working days and keep you informed while we work
on a fix. If you would like credit in the advisory, say so and give us the name
you want used.

## What is in scope

Hansard processes meeting recordings, which are among the most sensitive
documents an organisation holds. We treat the following as security issues:

- Anything that causes audio, transcripts or minutes to leave the host — an
  unexpected outbound connection, a leak into logs, an artefact written outside
  the configured directory.
- Path traversal in artefact keys, filenames or delivery addresses.
- Secrets appearing in logs, error messages, metrics or rendered output.
- Authentication bypass on the HTTP API.
- Container escape or privilege escalation from the browser bot pod.
- Injection through untrusted input — a participant display name, a meeting
  title, a chat message — into rendered HTML, email or a Teams message.
- Dependency vulnerabilities reachable from a default configuration.

## What is not in scope

- The fact that the browser bot joins a meeting as a visible participant. That
  is the design; see [docs/sovereignty.md](docs/sovereignty.md).
- Missing hardening in a deployment you configured yourself — for example
  exposing the API without setting `HANSARD_API__API_KEY`.
- Vulnerabilities in Microsoft Teams itself.
- Reports generated solely by an automated scanner, without a demonstrated
  impact on this project.

## Guarantees we test for

Two properties are enforced in CI on every commit, and a regression in either is
a security bug:

- **No network in the inference path.** `scripts/check_no_egress.py` runs a
  transcription with every socket sealed.
- **No telemetry.** There is no analytics code. The `telemetry_enabled` setting
  exists only to raise an error if anyone attempts to turn it on.

## Supported versions

Until a 1.0 release, security fixes land on `main` and in the next tagged
release. There is no long-term support branch yet.
