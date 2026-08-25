# Contributing

Thank you for considering it. This page covers the three conventions that
surprise people, then the practical mechanics.

## Conventions

### The code contains no comments

Not a style preference — an enforced rule. `scripts/check_no_comments.py` runs in
CI and fails the build on any comment or docstring in `src/hansard/`.

The reasoning: comments drift from the code they describe, and a comment is
often a signal that a name is wrong or a function is doing too much. Everything
this project needs to explain lives in `docs/`, where it is versioned, indexed
and read by the people who actually need it.

In practice this means expressive names, small functions, complete type
annotations, and named constants instead of magic numbers. If a piece of code
seems to need a comment, that is the moment to rewrite the code or to add a
paragraph to the relevant document.

`# noqa` and `# type:` pragmas are permitted, since they are instructions to
tools rather than prose. YAML, Dockerfiles and shell scripts may carry comments:
they are configuration that operators read directly.

### Quality claims need evidence

Any change touching recognition, diarization or attribution should come with a
benchmark run:

```bash
make bench
```

Paste the before and after into the pull request. `bench/results/` files record
the normalizer version and the hardware, so a reviewer can tell whether two runs
are comparable. If a number moves in the wrong direction, say so — a regression
you flagged is a discussion, a regression a reviewer discovers is a problem.

### Nothing may reach the network during inference

`scripts/check_no_egress.py` runs a transcription with every socket sealed and
fails if anything tries to connect. A dependency that phones home at import time,
or a model loader that falls back to a download, will be caught here.

This is the property the whole project exists to provide. If your change genuinely
needs a network call, it belongs behind explicit configuration, off by default,
and outside the inference path.

## Getting set up

```bash
git clone https://github.com/Haswell119/teams-retranscription
cd teams-retranscription
make install-dev
make models          # about 682 MB, SHA-256 verified
export HANSARD_RUNTIME__MODELS_DIR="$PWD/models"
make check           # lint, types, tests
```

`make check` is exactly what CI runs, minus the container builds.

## Architecture in one paragraph

Ports and adapters. `domain/` holds pure entities with no I/O. `ports/` declares
Protocol interfaces. `adapters/` implements them. `application/` orchestrates use
cases and depends only on ports. `interfaces/` exposes the CLI and the HTTP API.
The consequence worth knowing: adding a speech engine, a diarizer, a delivery
channel or an output format means writing one class and registering it, without
touching anything else. See [docs/architecture.md](docs/architecture.md).

## Making a change

- Branch from `main`.
- Keep the commit history readable; explain *why* in the message, since the
  code cannot.
- Add tests. The suite runs in about five seconds — there is no excuse.
- Tests must pass offline. Inject your HTTP client, your subprocess runner and
  your model loader so they can be replaced with fakes.
- Update the documentation in the same pull request. Documentation that lags is
  the failure mode this project is most exposed to.

## Both languages are first-class

Meetings are held in French and in English. A change that improves one and
degrades the other is not an improvement. Text handling, cue phrases, rendered
output and benchmark reporting all carry both languages, and new work is expected
to do the same.

Watch out in particular for: French diacritics (our normalizer keeps them
deliberately — stripping them silently improves word error rate and destroys the
measurement), typographic apostrophes, and the non-breaking space French uses
before `:` `;` `?` `!`.

## Reporting a problem

Open an issue with the output of `hansard doctor`, your versions, and what you
expected.

**Do not paste meeting content into a public issue.** If a bug can only be
demonstrated with real audio, say so and we will work out a private channel.
Security issues go to [SECURITY.md](SECURITY.md) rather than the tracker.
