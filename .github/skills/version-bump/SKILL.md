---
name: version-bump
description: 'Bump the project version (major, minor, or patch) before committing. Use when: releasing a new version, preparing a release, version bump, semver bump, incrementing version number.'
argument-hint: 'Specify bump type: major, minor, or patch'
---

# Version Bump

Bump the semantic version across all version files, then stage and commit.

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

## Procedure

1. **Read current version** from `custom_components/ha_ledvance_lights/manifest.json` (`"version"` field).
2. **Parse** as `MAJOR.MINOR.PATCH` integers.
3. **Apply bump** based on the requested type:
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
