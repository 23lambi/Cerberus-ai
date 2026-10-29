# Publishing a Cerberus release

[← README](../README.md) · [Launcher guide](launcher.md)

> **Desktop releases are paused.** The public installation path is the
> [terminal installation in the README](../README.md#download). Keep launcher
> releases as drafts until the launcher is ready. The packaging workflow is
> manual-only and does not create a draft unless explicitly requested.
> The instructions below are retained for future packaging work.

## What is a release?

A GitHub repository contains the source code. A release adds the ready-to-open
launcher ZIPs and application packages that people can download. Pushing code
alone does not create those files.

A **draft** is for your review. A **published stable release** is what the
launcher downloads. The repository must be **public** for people to download
without a GitHub account and for the launcher's unauthenticated release checks.

## First release

1. **Commit and push the prepared changes yourself.** Include the Windows fixes,
   release workflow, launcher, and documentation. Local uncommitted fixes are not
   included in GitHub builds.
2. In GitHub, open **Actions → Build desktop releases → Run workflow**.
3. Select `main`, enter an unused version such as `v0.4.0`, and leave
   **Create a draft release** enabled. Click **Run workflow**.
4. Wait for **all four platform builds**, assembly, and draft creation to pass.
   If a job fails, fix its error and push the fix before starting another build.
5. Open **Releases** and edit the generated draft. Test the platform downloads
   and review the release notes, system requirements, and unsigned-build status.
6. When ready for public testing, change the repository visibility under
   **Settings → General → Danger Zone → Change repository visibility → Public**.
   This exposes the repository and its commit history, not just the downloads.
7. Publish the draft as a **stable release**. Do not mark it as a prerelease;
   the current launcher looks for the latest stable release.
8. Test the README's Releases links in a signed-out browser and test a clean
   launcher installation. Update the README's preparation notice once downloads
   are available.

The workflow creates a draft only. It does not publish automatically, make the
repository public, commit files, or push local changes.

## Files that must be attached

For **each** of `linux-x86_64`, `windows-x86_64`, `macos-arm64`, and `macos-x86_64`:

- `cerberus-launcher-<target>.zip` — the small installer/updater users open.
- `cerberus-<target>.tar.gz` — the app package downloaded by the launcher.

Also include `release-manifest.json` with all four app checksums and `LICENSE.txt`.
The workflow assembles these together. Publishing only the launcher ZIP is not
enough for its Install button to work.

## Later updates

Before each release, rewrite the **What's new** section at the top of
`packaging/release-notes.md` for that version: a few short points, written for
users. The workflow puts the file on the release page, and Cerberus shows that
section in **Settings → Updates** before people download the update. Keep the
heading exactly `## What's new`.

Choose a new version and repeat the build/review/publish flow. Use a new version
if a tag already exists for different code; do not move an existing release tag.
Installed launchers find the latest published stable version through GitHub.
The launcher executable itself is updated by downloading its newer ZIP.

## “This version tag already points to another commit”

The chosen version already names older code. A manual run on `main` builds the
selected branch's current commit, so it cannot reuse a tag belonging to a
different commit. This check prevents a release from offering binaries that do
not match its source tag.

Keep the existing tag. After committing and pushing your fixes, open **Actions →
Build desktop releases → Run workflow**, select `main`, and enter an **unused**
version (for example `v0.4.1` if `v0.4.0` is taken). Start a new workflow run;
**Re-run jobs** on the old run retains its original version and commit.

The workflow checks this before the four platform builds and checks again before
creating the draft, in case the tag changes while builds are running.

## Linux distribution checks

CI builds the Linux downloads on Ubuntu. After the builds, the workflow runs the
built launcher and app in **Fedora**, **Arch Linux**, and **openSUSE** containers
with `--check-release`: each must reach GitHub over verified HTTPS using its own
bundled SSL library and read the latest published release. The draft is created
only when these pass. This catches problems like a bundled library that looks
for system files only where Ubuntu keeps them.
