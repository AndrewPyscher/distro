# Source modules

The distro repository owns recipes, build coordination, image profiles and
system policy. Component source lives in these local Git clones, declared in
`source-projects.toml`:

| Owning repository | Directory |
| --- | --- |
| [telorgon](https://github.com/WIPOperatingSystemName/telorgon) | `sources/telorgon` |
| [bootloader](https://github.com/WIPOperatingSystemName/bootloader) | `sources/telorgon-bootloader` |
| [file-explorer](https://github.com/WIPOperatingSystemName/file-explorer) | `sources/telorgon-file-explorer` |
| [settings](https://github.com/WIPOperatingSystemName/settings) | `sources/telorgon-settings-app` |
| [portal-picker](https://github.com/WIPOperatingSystemName/portal-picker) | `sources/telorgon-portal-picker` |
| [shell](https://github.com/WIPOperatingSystemName/shell) | `sources/test-shell` |

These components follow the organization's `main` branch. Initialize or update
all registered clones with:

```sh
python3 build.py sources sync
```

`run`, `loader`, `apps prepare/build`, `deploy`, `dev` and source-bundle export
also synchronize components before snapshotting. The pipeline verifies canonical
origins, fetches `main` and fast-forwards the current branch. Existing contribution
branches, commits and uncommitted work stay intact when Git can apply that update
safely. Diverged commits or overlapping edits stop with the affected repository;
resolve them in that owning checkout, then retry. Nothing is reset or stashed.
Network errors also stop online builds instead of silently using stale sources.
Online `./run` and `python3 build.py run` additionally update the distro checkout
itself before loading build catalogs, so new recipes and registered components
are included. See [automatic source updates](build.md#automatic-source-updates)
for restart, local-work and offline behavior.
Online builds can fetch the dependencies selected by each component's `Cargo.lock`;
`--online` remains accepted explicitly, and `--offline` disables both Git and Cargo
network access.

Use `--offline` to build the current local files without fetching or advancing
checkouts; required archives and Cargo dependencies must already be cached.
Exact commits, dirty state and content hashes remain in build receipts so each
build can be identified and replayed. Third-party OS archives and the Rust
compiler retain their verified checksums/toolchain versions.

### Existing submodule workspaces

After updating distro to this workflow, run `python3 build.py sources sync`.
Existing component directories, local edits, remotes and Git history are reused.
Detached checkouts migrate to a local `main` when safe. Do not delete `sources/`
or `.git/modules/`: existing clones may still use those Git object directories.
Fresh distro clones need no recursive checkout or submodule commands.

## Edit source and snapshot it

Edit the owning checkout directly. The build pipeline's default source root is
`sources/`; its snapshots include existing uncommitted work, Cargo locks,
content hashes, executable modes and Git HEAD/dirty state. Distro-specific
recorded overlays are applied only in generated snapshots. They must not become
the home for application/framework fixes.

`apps prepare`, `loader` and `source-bundle export` snapshot the selected inputs
under `out/`, excluding Git internals, output trees and vendor caches. Generated
copies are not development source. A fix is complete when it lives in the owning
source and its rebuilt package passes the affected checks.

For a separate development workspace, use `--source-root /absolute/workspace`.
It must contain the framework, bootloader and app directories in the layout above.
Pass the same root to `run`, `deploy` and source export as appropriate; record the
origin and source identity in test evidence. Use the
[pacman deployment loop](build.md#deploy-applications-into-a-running-development-vm)
for application iteration.

## Register another application

Application discovery uses `packages/*/application.toml`; source snapshot inputs
come from `source-projects.toml`. Adding a Cargo app does not require editing a
Python application list:

1. Add a project to `source-projects.toml` with its canonical organization
   `repository` URL, `branch = "main"` and input paths, including `Cargo.toml`,
   `Cargo.lock`, source, assets and packaging files. Register the new repository
   in the shared setup/checker catalogs before using it in distro CI.
2. Add one package directory with `application.toml`. Follow an existing app's
   package, source, target-Cargo build, requirements and runtime declarations.
   List every source project affecting its build, including the framework.
   This dependency list determines which apps rebuild after shared changes.
   Assign the package and source project a functional group in the
   [component map](components.md#updating-the-map), explain their individual
   purposes in `docs/component-details.toml`, and regenerate the documentation.
3. Add the package to the intended profile or another package's runtime
   dependencies. `dev` updates apps used by that VM profile and its dependency
   closure, rather than every app in the organization.

The default installer packages the declared binary and available license
inputs. Optional source-owned launcher/service files can be declared as:

```toml
[install]
files = [{ source = "packaging/org.example.terminal.desktop", destination = "usr/share/applications/org.example.terminal.desktop" }]

[development]
restart = "reopen"
```

Source/destination paths are relative to the primary source and package root.
Use `restart = "desktop"` for a compositor, or `restart = "services"` with
`services = ["example.service"]` for user services. Ordinary apps default to
`reopen`. Source projects default to package updates; `update = "base"` marks
loader/base inputs that require a fresh image. The current build adapter supports
target Cargo applications; a new build system needs a corresponding adapter.

Run `python3 build.py validate`, inspect `python3 build.py apps plan`, and test
the [automatic update plan](build.md#update-changed-applications-automatically)
before deployment. Keep repository declarations and package versions in their
manifests.

## Portable source bundles

To synchronize and export source checkouts, including local edits:

```sh
python3 build.py source-bundle export
```

Add `--offline` to export the exact current files without synchronization.
The command reports a deterministic archive and SHA256 under `out/bundles/`.
On a clean worker, import that archive with its independently reviewed digest:

```sh
python3 build.py source-bundle import /path/to/telorgon-sources.tar.xz --sha256 REVIEWED_SHA256
```

Replace the path and digest with the export's actual values. Import verifies the
archive and records its extracted workspace in `out/bundles/current.json`.
Use that root explicitly:

```sh
CD_SOURCE_WORKSPACE=$(python3 -c 'import json; print(json.load(open("out/bundles/current.json"))["root"])')
./run --profile desktop-dev --name bundle-test --source-root "$CD_SOURCE_WORKSPACE"
```

Bundles carry source, assets, license inputs and locks; they exclude credentials,
Git internals and build outputs. An imported bundle is a replay input. Implement
subsequent fixes in the owning repository and export again.

## Component changes

Submit framework and application fixes to their owning repositories. Once merged,
the next online build uses organization `main` without a separate distro pin PR.
Rebuild affected consumers and test the behavior; a moving branch alone does not
establish compatibility. Source bundles provide explicit replay inputs for CI or
qualification; their contents are verified rather than synchronized with Git.
