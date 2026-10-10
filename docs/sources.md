# Source modules

The distro repository owns recipes, build coordination, image profiles and
system policy. Component source lives in these Git submodules:

| Owning repository | Directory |
| --- | --- |
| [telorgon](https://github.com/WIPOperatingSystemName/telorgon) | `sources/telorgon` |
| [bootloader](https://github.com/WIPOperatingSystemName/bootloader) | `sources/telorgon-bootloader` |
| [file-explorer](https://github.com/WIPOperatingSystemName/file-explorer) | `sources/telorgon-file-explorer` |
| [settings](https://github.com/WIPOperatingSystemName/settings) | `sources/telorgon-settings-app` |
| [portal-picker](https://github.com/WIPOperatingSystemName/portal-picker) | `sources/telorgon-portal-picker` |
| [shell](https://github.com/WIPOperatingSystemName/shell) | `sources/test-shell` |

Each parent gitlink records an exact component commit. Inspect the selections:

```sh
git submodule status
git ls-files --stage sources/
```

Initialize a new checkout with `git submodule update --init --recursive`.
On an existing workspace, inspect component work first; restoring the parent's
pins can move a component checkout. Never use `submodule update --remote`, pull,
reset or patch the component as incidental build setup.

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

1. Register its owning repository under `sources/` in `.gitmodules`, with a
   reviewed immutable gitlink. Add its input paths to `source-projects.toml`,
   including `Cargo.toml`, `Cargo.lock`, source, assets and packaging files.
2. Add one package directory with `application.toml`. Follow an existing app's
   package, source, target-Cargo build, requirements and runtime declarations.
   List every source project affecting its build, including the framework.
   This dependency list determines which apps rebuild after shared changes.
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
before deployment. Keep immutable pins and package versions in their manifests.

## Portable source bundles

To export the current source checkouts, including local edits:

```sh
python3 build.py source-bundle export
```

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

## Reviewed pin updates

A component commit/PR and a distro gitlink update are separate review steps.
Pin updates require explicit authorization and a compatible reviewed component
set. Keep corresponding package revisions and dependency changes with the
integration, then rebuild and test affected behavior. Do not advance a detached
source checkout just because its upstream branch has moved.
