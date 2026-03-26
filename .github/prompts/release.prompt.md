---
description: 'Create a GitHub release with a git tag from the current version. Use when: releasing, tagging a release, publishing a new version.'
agent: 'agent'
---

Create a GitHub release for this project:

1. Read the current version from `custom_components/ledvance_wifi/manifest.json` (`"version"` field).
2. Ensure the working tree is clean (`git status --porcelain` returns empty). If not, stop and tell the user.
3. Create an annotated git tag `v{VERSION}` (e.g. `v1.0.0`) pointing at HEAD.
4. Push the tag: `git push origin v{VERSION}`.
5. Create a GitHub release via `gh release create v{VERSION} --title "v{VERSION}" --generate-notes`.
6. Report the release URL to the user.
