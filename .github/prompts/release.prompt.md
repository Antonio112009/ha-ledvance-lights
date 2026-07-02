---
description: 'Release the current state of development. Normal path: merge the auto-created development → main PR (release publishes automatically). Manual tag+release steps remain as an emergency fallback.'
agent: 'agent'
---

Release this project:

## Normal path (automated)

1. Ensure everything to release is merged into `development`.
2. Find the auto-created PR `development` → `main` (opened by the
   "Auto PR to main" workflow on every push to `development`). If it does
   not exist, check that the `RELEASE_TOKEN` secret is configured and
   re-run the workflow.
3. Verify the PR carries the intended release label (`major`, `minor`,
   `patch`, or `no-release`) — adjust if needed.
4. Merge the PR. The Release workflow bumps the version on `main`, tags
   `vX.Y.Z`, publishes the GitHub release, and syncs `main` back into
   `development`. Report the release URL to the user.

## Emergency fallback (Actions unavailable)

1. Read the current version from `custom_components/ha_ledvance_lights/manifest.json` (`"version"` field).
2. Ensure the working tree is clean (`git status --porcelain` returns empty). If not, stop and tell the user.
3. Bump the version manually per the version-bump skill (all three version files), commit.
4. Create an annotated git tag `v{VERSION}` pointing at HEAD and push it: `git push origin v{VERSION}`.
5. Create a GitHub release via `gh release create v{VERSION} --title "v{VERSION}" --generate-notes`.
6. Report the release URL to the user.
