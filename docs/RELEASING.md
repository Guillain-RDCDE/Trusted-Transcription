# Releasing

A release is a tag. Everything else follows from it.

## Every release

1. Bump `version` in `pyproject.toml` and `__version__` in
   `src/trusted_transcription/__init__.py` — they must agree.
2. Add the section to `CHANGELOG.md`.
3. Commit, then tag and push:

   ```bash
   git tag -a v0.9.0 -m "0.9.0: …"
   git push origin main v0.9.0
   ```

4. The `tests` workflow runs the suite on two Python versions and
   builds the wheel in a clean environment. The `publish` workflow
   builds again, checks that the tag and the package version agree,
   and uploads to PyPI.
5. Create the GitHub release from the tag with the changelog section
   as notes.

## One-time setup for PyPI

The `publish` workflow uses PyPI's trusted publishing: PyPI accepts
uploads from this repository's workflow directly, and no token is
stored in GitHub or on any machine.

1. On GitHub, the environment `pypi` exists (done).
2. On PyPI, signed in, open *Account settings → Publishing* and add a
   **pending publisher** — the project does not need to exist first:

   | Field | Value |
   |---|---|
   | PyPI project name | `trusted-transcription` |
   | Owner | `Guillain-RDCDE` |
   | Repository name | `Trusted-Transcription` |
   | Workflow name | `publish.yml` |
   | Environment name | `pypi` |

3. Run the upload for the current tag without cutting a new release:

   ```bash
   gh workflow run publish.yml --ref v0.12.0
   ```

   The first successful upload creates the project and turns the
   pending publisher into a regular one. Every later tag publishes on
   its own.

Until step 2 is done, the `publish` workflow fails at the upload step
and nothing else is affected; the `tests` workflow still proves the
wheel installs.

## What the wheel contains

Only `src/trusted_transcription`. The samples, the tests and the docs
travel in the source distribution, not in the wheel.
