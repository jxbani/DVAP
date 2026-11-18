# Releasing DVAP

A release is a `vX.Y.Z` tag. Pushing it runs `.github/workflows/release.yml`, which:

1. checks that the tag, `version` in `pyproject.toml`, `DVAP_VERSION` in `.env.example` and a
   `## [X.Y.Z] - <date>` section in `CHANGELOG.md` all agree (it stops before publishing anything
   if not);
2. builds each DVAP image for linux/amd64 and linux/arm64 and pushes it to
   `ghcr.io/<owner>/dvap-<service>:X.Y.Z`;
3. signs each image by digest with cosign (keyless: the signature is bound to this workflow's
   GitHub OIDC identity and logged in Sigstore's public transparency log, Rekor);
4. attaches a build-provenance attestation to each image, and generates an SPDX SBOM for it with syft;
5. creates the GitHub Release: the CHANGELOG section as notes, plus `dvap-X.Y.Z.zip` (with its own
   provenance attestation) and the eleven SBOMs as assets.

## Before the first release (once)

- **Repository → Settings → Actions → General → Workflow permissions:** "Read and write
  permissions" is not needed (each job asks for what it uses), but GitHub Actions must be allowed
  to create releases and packages.
- **Repository → Settings → Pages → Source:** "GitHub Actions" (for `docs.yml`).
- **Repository → Settings → Code security:** turn on private vulnerability reporting (SECURITY.md
  points there).
- After the first release: on each `dvap-*` package's page (your profile → **Packages**) →
  **Package settings**, set the visibility to **Public** and link it to this repository. GHCR makes
  new packages private, and `./dvap up` can't pull private images without a login.

## Cutting a release

Releases come from `main`, with CI green.

1. Pick the version (Semantic Versioning; see the note at the top of CHANGELOG.md for what counts as
   breaking for a challenge).
2. Bump it in both places:
   - `pyproject.toml`: `version = "X.Y.Z"`, then run `uv lock` (the lock records the project version);
   - `.env.example`: `DVAP_VERSION=X.Y.Z`.

   `tests/test_lab_safety.py` checks that the compose defaults match.
   Also update the default in `docker-compose.yml` (`${DVAP_VERSION:-X.Y.Z}`, 11 places).
3. In `CHANGELOG.md`, rename `## [Unreleased]` to `## [X.Y.Z] - YYYY-MM-DD` (today, UTC), add a
   fresh empty `## [Unreleased]` above it, and update the links at the bottom:
   ```
   [Unreleased]: https://github.com/jxbani/DVAP/compare/vX.Y.Z...HEAD
   [X.Y.Z]: https://github.com/jxbani/DVAP/releases/tag/vX.Y.Z
   ```
4. Check it locally:
   ```bash
   uv run pytest
   python3 scripts/make_dist.py X.Y.Z     # the zip the release will attach, in dist/
   ```
5. Commit (`Release X.Y.Z`), open a PR, and merge it once CI is green.
6. Tag the merge commit on `main` and push the tag:
   ```bash
   git switch main && git pull --ff-only
   git tag -a vX.Y.Z -m "DVAP X.Y.Z"
   git push origin vX.Y.Z
   ```
7. Watch the **Release** workflow (Actions tab). When it finishes, check the release page: notes,
   `dvap-X.Y.Z.zip`, and 11 `*.spdx.json` files.
8. Make the ghcr.io packages public if they aren't yet (the first release creates them private).
   Then watch the **Fresh install** workflow, which starts when Release succeeds. It downloads
   the zip and the published images anonymously, the way a new user would, on Ubuntu, in an
   Ubuntu container driving the host's Docker (the closest GitHub gets to WSL2) and on Intel macOS
   with colima. Each runs `./dvap doctor`, `./dvap up --mode replay`, solves C01 through the ticket
   form, checks the HMI reports the OVERFLOW incident, and fails if that took over 15 minutes.
   `macos-latest` (Apple Silicon) has no Docker on GitHub, so it only checks that the zip's CLI runs
   and that doctor reports the missing Docker. The same check runs weekly, and by hand from the
   Actions tab for any tag. On any machine with Docker:
   ```bash
   scripts/verify_fresh_install.sh                     # the latest release
   DVAP_TAG=vX.Y.Z scripts/verify_fresh_install.sh     # a given one
   ```

## Verifying a release (anyone)

```bash
# The image signature: signed by this repository's release workflow, for this tag.
cosign verify ghcr.io/jxbani/dvap-plc:X.Y.Z \
  --certificate-identity "https://github.com/jxbani/DVAP/.github/workflows/release.yml@refs/tags/vX.Y.Z" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com

# Build provenance, for an image or the zip.
gh attestation verify oci://ghcr.io/jxbani/dvap-plc:X.Y.Z --repo jxbani/DVAP
gh attestation verify dvap-X.Y.Z.zip --repo jxbani/DVAP
```

## If something goes wrong

- **`verify` fails:** nothing was published. Fix the versions or the changelog on `main`, delete
  the tag (`git push origin :refs/tags/vX.Y.Z && git tag -d vX.Y.Z`), and tag again.
- **An image job fails after others pushed:** re-run the failed jobs from the Actions tab. Pushing
  the same tag again overwrites the images, and their signatures are re-created.
- **A bad release went out:** don't reuse the version. Fix forward with X.Y.(Z+1). Mark the bad
  release as such in its notes, rather than deleting it, since people may have pulled it.
