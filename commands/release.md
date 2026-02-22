---
description: Bump version, tag, and push a new release to both otto and otto-marketplace repos
argument-hint: "<patch|minor|major>"
allowed-tools: []
---

Bump the Otto plugin version across both repos, commit, tag, and push. Follow these steps precisely.

**Important:** All git and file commands in this workflow assume the current working directory is the otto project root. Use absolute paths if running from a different directory.

## Step 1: Parse argument

Validate the argument is one of `patch`, `minor`, `major`. If missing or not one of those three values, show usage and stop:

```
Usage: /release <patch|minor|major>

Examples:
  /release patch   — 0.2.0 → 0.2.1
  /release minor   — 0.2.0 → 0.3.0
  /release major   — 0.2.0 → 1.0.0
```

## Step 2: Read current version

Run this via bash to extract the current version:

```bash
grep -m1 'version = ' pyproject.toml
```

Parse the result into three integers: MAJOR, MINOR, PATCH. The format is `version = "X.Y.Z"`.

## Step 3: Compute new version

Apply the bump type to the parsed integers:

- `patch`: PATCH + 1
- `minor`: MINOR + 1, PATCH = 0
- `major`: MAJOR + 1, MINOR = 0, PATCH = 0

Tell the user: "Bumping from {old} to {new}"

## Step 4: Pre-flight: clean working tree

Run via bash:

```bash
git status --porcelain
```

If the output is non-empty, abort with: "Working tree is not clean. Commit or stash your changes first."

Do NOT proceed past this point if the tree is dirty.

## Step 5: Pre-flight: tag doesn't exist

Run both of these via bash:

```bash
git tag -l v{new}
```

```bash
git ls-remote --tags origin refs/tags/v{new}
```

If either command returns any output, abort with: "Tag v{new} already exists."

## Step 6: Pre-flight: first-run baseline tag

Run via bash:

```bash
git tag -l
```

If no tags exist at all (empty output), create a baseline tag on HEAD:

```bash
git tag v{old}
git push origin v{old}
```

Tell the user: "Created baseline tag v{old}."

## Step 7: Update all 4 files in otto repo

Use the Edit tool for each file. Replace the old version with the new version using the exact patterns:

1. `pyproject.toml` — replace `version = "{old}"` with `version = "{new}"`
2. `src/otto/__init__.py` — replace `__version__ = "{old}"` with `__version__ = "{new}"`
3. `.claude-plugin/plugin.json` — replace `"version": "{old}"` with `"version": "{new}"`
4. `.claude-plugin/marketplace.json` — replace `"version": "{old}"` with `"version": "{new}"`

After all 4 edits, verify they took effect by running via bash:

```bash
grep -c "{new}" pyproject.toml src/otto/__init__.py .claude-plugin/plugin.json .claude-plugin/marketplace.json
```

Each file should report a count of at least 1. If any file shows 0, the edit failed — stop and investigate.

## Step 8: Commit and tag (do NOT push yet)

Run via bash:

```bash
git add pyproject.toml src/otto/__init__.py .claude-plugin/plugin.json .claude-plugin/marketplace.json
git commit -m "release: v{new}"
git tag v{new}
```

Do NOT push the otto repo yet. The marketplace must be pushed first.

## Step 9: Clone marketplace, update, push marketplace FIRST

Clone the marketplace repo to a temp directory:

```bash
git clone https://github.com/stemado/otto-marketplace.git /tmp/otto-marketplace-release
```

Detect the default branch:

```bash
git -C /tmp/otto-marketplace-release remote show origin | grep 'HEAD branch' | awk '{print $NF}'
```

Use the Edit tool to update `/tmp/otto-marketplace-release/.claude-plugin/marketplace.json` — replace `"version": "{old}"` with `"version": "{new}"`.

If the Edit tool cannot find the version string, the marketplace file format may have changed. Abort and tell the user: "Could not update the marketplace repo — the version pattern was not found in marketplace.json. Check the file format manually."

Then run via bash:

```bash
cd /tmp/otto-marketplace-release && git add .claude-plugin/marketplace.json && git commit -m "release: otto v{new}" && git push origin {detected-branch}
```

**If the marketplace push fails:** Tell the user the error, then **show** (do NOT execute) these manual recovery instructions and STOP. Do NOT push the otto repo. Do NOT run these recovery commands yourself — they are destructive and the user must choose to run them.

```
The marketplace push failed. To recover:
1. The otto repo has a local commit and tag that have NOT been pushed.
2. To undo the local otto changes:
   git tag -d v{new}
   git reset --soft HEAD~1
   git restore --staged pyproject.toml src/otto/__init__.py .claude-plugin/plugin.json .claude-plugin/marketplace.json
   git checkout -- pyproject.toml src/otto/__init__.py .claude-plugin/plugin.json .claude-plugin/marketplace.json
3. Fix the marketplace issue, then re-run /release {bump-type}
```

## Step 10: Push otto repo (only after marketplace succeeds)

Only run this after Step 9 succeeds. This pushes the release commit and tag from the master branch:

```bash
git push origin master --tags
```

**If the otto push fails:** The marketplace has already been updated, which is the safe failure mode. Tell the user:

```
The marketplace was updated successfully, but the otto push failed.
Your local commit and tag are intact. Try again with:
  git push origin master --tags
If the issue persists, check your network and GitHub permissions.
Claude Code will automatically retry fetching the new version on next refresh.
```

## Step 11: Clean up

Remove the temp clone:

```bash
rm -rf /tmp/otto-marketplace-release
```

## Step 12: Report success

Show the user a summary:

```
Release v{new} complete!

Version: {old} → {new}
Repos updated: otto, otto-marketplace
Git tag: v{new}

Files updated (5):
  - pyproject.toml
  - src/otto/__init__.py
  - .claude-plugin/plugin.json
  - .claude-plugin/marketplace.json
  - otto-marketplace/.claude-plugin/marketplace.json

Claude Code will pick up the new version automatically on next plugin refresh,
or manually via: /plugin update otto@otto-marketplace

Rollback (if needed):
  # Otto repo
  git tag -d v{new}
  git push origin :refs/tags/v{new}
  git revert HEAD
  git push origin master

  # Marketplace repo (replace {branch} with the repo's default branch)
  git clone https://github.com/stemado/otto-marketplace.git /tmp/otto-mp
  cd /tmp/otto-mp && git revert HEAD && git push origin {branch}
```
