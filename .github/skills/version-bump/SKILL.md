---
name: version-bump
description: 'Bump the project version (major, minor, or patch) before committing. Use when: releasing a new version, preparing a release, version bump, semver bump, incrementing version number.'
argument-hint: 'Specify bump type: major, minor, or patch'
---

# Version Bump

Bump the semantic version across all version files, then stage and commit.

## CRITICAL — Always Bump Before Commit+Push

Whenever the user asks to "commit and push", "commit", or triggers `/release`, you MUST:

1. **Check for staged/unstaged changes** beyond version files.
2. **Auto-detect the bump type** from the commit message the user provides (or that you generate).
3. **Bump the version FIRST**, then include the version files in the same commit.
4. Never commit code changes without bumping the version. If you forget, bump immediately in a follow-up commit before pushing.

## When to Use

- Before a release commit
- When the user says "bump version", "new release", or "increment version"
- When explicitly invoked via `/version-bump`

## Version Files

Both files must stay in sync:

| File | Field |
|------|-------|
| `custom_components/ha_ledvance_lights/manifest.json` | `"version": "X.Y.Z"` |
| `custom_components/ha_ledvance_lights/const.py` | `VERSION = "X.Y.Z"` |

## Auto-detecting Bump Type

If the user does not specify a bump type, detect it from commit messages since the last tag:

1. Run `git log $(git describe --tags --abbrev=0 2>/dev/null || echo "")..HEAD --oneline` to get commits since the last tag.
2. Apply these rules (first match wins):
   - **major** — any commit contains `BREAKING CHANGE` or a `!` after the type (e.g. `feat!:`, `refactor!:`)
   - **minor** — any commit starts with `feat:` or `feat(`
   - **patch** — all other cases (`fix:`, `chore:`, `refactor:`, `docs:`, etc.)
3. If no commits are found since the last tag, default to `patch`.
4. Report the detected bump type and the commits that determined it before proceeding.

## Procedure

1. **Read current version** from `custom_components/ha_ledvance_lights/manifest.json` (`"version"` field).
2. **Parse** as `MAJOR.MINOR.PATCH` integers.
3. **Determine bump type** — use the user-specified type, or auto-detect per the rules above.
4. **Apply bump** based on the type:
   - `major` → `MAJOR+1.0.0`
   - `minor` → `MAJOR.MINOR+1.0`
   - `patch` → `MAJOR.MINOR.PATCH+1`
4. **Update both files**:
   - In `manifest.json`: replace the `"version"` value.
   - In `const.py`: replace the `VERSION = "..."` value.
5. **Stage the two changed files**:
   ```sh
   git add custom_components/ha_ledvance_lights/manifest.json custom_components/ha_ledvance_lights/const.py
   ```
6. **Commit** with message:
   ```
   chore: bump version to X.Y.Z
   ```
7. **Report** the old and new version to the user.

## Rules

- Never skip a file — both must be updated in the same operation.
- Do not push automatically; only commit. The user decides when to push.
- If the current version cannot be parsed, stop and ask the user.
