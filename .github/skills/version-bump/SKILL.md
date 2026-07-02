---
name: version-bump
description: 'Explain or manually perform a version bump. Versions are normally bumped AUTOMATICALLY by the Release workflow — use this skill only to understand the flow or for a manual emergency bump.'
argument-hint: 'Specify bump type: major, minor, or patch'
---

# Version Bump

## Versions are bumped automatically — do NOT bump in feature branches

Since the label-driven release pipeline, the version is bumped **on `main`
by the Release workflow** (`.github/workflows/release.yml`) after the
`development` → `main` PR merges:

1. Pushes to `development` make `auto-pr.yml` open/update the
   `development` → `main` PR and suggest a `major`/`minor`/`patch` label
   from conventional commits (a human can override; `no-release` skips
   releasing entirely).
2. `version-label.yml` enforces exactly one release label on PRs to `main`.
3. On merge, `release.yml` bumps the version files on `main`, commits
   `Bump version to X.Y.Z`, tags `vX.Y.Z`, publishes the GitHub release,
   and merges `main` back into `development`.

**Never commit a manual version bump in a feature branch** — it would
double-bump when the release workflow applies the label on top.

## Version Files (kept in sync by the workflow)

| File | Field |
|------|-------|
| `custom_components/ha_ledvance_lights/manifest.json` | `"version": "X.Y.Z"` |
| `custom_components/ha_ledvance_lights/const.py` | `VERSION = "X.Y.Z"` |
| `pyproject.toml` | `version = "X.Y.Z"` |

## Controlling the bump type

Use conventional commit messages — `auto-pr.yml` derives the label:

- **major** — commit contains `BREAKING CHANGE` or `!` after the type (`feat!:`)
- **minor** — commit starts with `feat:` or `feat(`
- **patch** — everything else (`fix:`, `chore:`, `ci:`, `docs:`, …)

To override, change the label on the auto-created `development` → `main`
PR before merging (the workflow never downgrades a human-set label).

## Manual bump (emergency fallback only)

Only when the Release workflow is unavailable:

1. Read the current version from `manifest.json`, parse `MAJOR.MINOR.PATCH`.
2. Apply the bump (`major` → `MAJOR+1.0.0`, `minor` → `MAJOR.MINOR+1.0`,
   `patch` → `MAJOR.MINOR.PATCH+1`).
3. Update **all three** files listed above to the same version.
4. Commit as `chore: bump version to X.Y.Z`.
5. Report old and new version to the user.
