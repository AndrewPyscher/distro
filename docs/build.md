# Build and run

Complete [environment setup](setup.md) first. Run commands from the distro root
in a Linux terminal. `./run` forwards arguments to `python3 build.py run`.

## Host setup

Use the [setup guide](setup.md) for host seeds, Rust, QEMU/OVMF, KVM and WSLg.
On Windows, apply the [WSLg frame-rate setting](setup.md#wslg-frame-rate) before
high-refresh testing. Run the pipeline as your normal user.

## Build and run

For source development, create a named development VM:

```sh
./run --profile desktop-dev --name dev
```

The pipeline audits the host, validates recipes, downloads verified sources,
builds/checks the bootstrap compiler, builds the private package toolkit and
runtime packages, builds Telorgon EFI and applications, composes the image and
opens QEMU. The first build needs network access and can take substantial time.
Failures stop at the affected stage and report its log.

Telorgon starts the local `custom` desktop session. Open applications from the
launcher and test mouse/keyboard behavior. The development profile adds the
source-built QEMU Guest Agent and private deployment channel.

## Desktop build

For a normal desktop without that channel:

```sh
./run
```

This defaults to `desktop-use`. Framework, loader and apps must form a compatible
source set. Builds include existing uncommitted source edits and never pull,
reset or advance submodules. A missing Rust feature/API requires a source fix
or an explicitly reviewed compatible source set; removing a requested feature
name does not supply its implementation.

Without `--name`, `run` chooses `test-<build-identity-prefix>`: the same image
build reuses its disk, while a different build gets a separate VM. This identity
is derived from build inputs, independently of filesystem timestamps in image
bytes. Use an explicit name when you want to retain one disk across builds.

## Reopen a saved VM

Reopen the development VM without compiling:

```sh
python3 build.py vm --use --development --name dev
```

For a normal desktop, use `python3 build.py vm --use --name my-desktop`.
`vm --use` defaults to the name `custom`; it does not automatically find the
VM selected by an earlier unnamed `run`. Reuse the exact printed name.

On first launch, `vm` needs an existing image. Its default base is
`out/images/custom-distro-desktop-dev.img` with `--development`, or
`out/images/custom-distro-desktop-use.img` otherwise. It does not build a missing
image or switch profiles. Use `run` for initial preparation.

Files, guest-installed packages and firmware variables live under
`out/vms/<name>/`. **An existing name retains its original disk even after the
base image is rebuilt.** Application deployment updates that disk explicitly.
Kernel, service-policy, runtime-library or loader changes need a newly composed
image and a new VM name for testing; application deployment cannot update them.
Do not delete a saved VM as a rebuild shortcut.

QEMU uses private virtual disks, copied firmware variables and user-mode
networking. It probes KVM and falls back to TCG. Normal desktop use has no boot
assertions or injected test input. Close the guest normally to retain its data;
closing QEMU or Ctrl+C also ends the launcher. Logs and the exact QEMU command
are saved alongside the VM state.

## Update changed applications automatically

Build a `desktop-dev` image once and keep its named VM running. Inspect the
first update in a second terminal:

```sh
python3 build.py dev --name dev --plan --adopt-base
python3 build.py dev --name dev --adopt-base --jobs 4
```

First adoption compares the recorded SDK and native package inventory with the
guest and records the current base inputs after a successful update. Confirm
that the VM was built from your intended base before adopting: this check cannot
reconstruct historical source edits used by an older image. `--plan` snapshots
source and writes a report under `out/`, but does not fetch, compile, install or
adopt the baseline. Review any reported base errors before continuing.

For subsequent edits:

```sh
python3 build.py dev --name dev --jobs 4
python3 build.py dev --name dev --build-profile release
```

The command discovers `packages/*/application.toml` and selects the application's
runtime dependency closure from the guest's image profile. It uses each app's
declared source projects, recipe, toolchain and SDK to calculate the same build
identity as the package builder. Already installed identities are skipped;
valid cached packages are reused. A shared framework change selects every app
that declares it. All selected packages use one verified guest pacman transaction.
No image composition or VM disk replacement occurs.

Before deployment, `dev` verifies canonical `origin` URLs, discovers their default
branches and fetches distro plus every registered source repository. If any
checkout lacks upstream commits, it stops with repository paths and commit IDs.
Have your coding agent integrate upstream in each owning contribution checkout,
preserve local work, adapt the changes and rerun affected checks, then retry.
Fetching updates remote references only: the builder never merges, stashes,
resets, advances pinned checkouts or updates distro gitlinks. A detached pin
behind upstream requires deliberate component integration, or an explicitly
selected current source workspace with `--source-root`. Pin updates remain a
separate authorized contribution. Other build commands retain their existing
source replay behavior; the freshness gate applies to `dev`.

`--offline` uses cached upstream references and Cargo inputs. It still rejects
known missing commits, but cannot establish network-verified freshness.
Source bundles without Git metadata remain usable with explicit `deploy`;
the `dev` upstream gate needs real repository checkouts.

Native recipe/runtime, SDK, loader, system-policy and base-profile changes stop
the app loop. Build a fresh image with `run` and use a new VM name, then inspect
and adopt that VM. `--adopt-base` cannot overwrite an existing baseline to bypass
this check. Adding an app that needs only existing native packages does not
require a new base; adding a new native dependency does.

Restart behavior comes from each app manifest: ordinary apps are listed for
manual reopening, services use declared user units, and shell changes restart
the desktop. **Save work before shell updates: a desktop restart closes apps.**
`--no-restart` defers all restarts. Installation/version checks do not qualify
GUI behavior; exercise the affected apps afterwards. The latest attempt is
recorded in `out/vms/<name>/development-report.json`; the last successful base
and package identities live in `development.json`. Failed attempts preserve the
last successful baseline. Rebuilding an image does not upgrade the saved disk.

Future apps join this workflow through the
[source and application catalogs](sources.md#register-another-application).

## Deploy applications into a running development VM

Implement fixes in the owning checkout under `sources/<module>/`. Generated
snapshots and experiments under `out/` cannot be the only copy of a fix.
Keep the named development VM running. In a second terminal:

```sh
python3 build.py deploy telorgon-file-explorer --name dev
```

The default deployment build profile is `dev`. For renderer/performance work,
use optimized code and rebuild every affected app. For a framework change:

```sh
python3 build.py deploy telorgon-shell telorgon-file-explorer \
  telorgon-settings-app telorgon-portal-picker --name dev --build-profile release --jobs 4
```

The pipeline snapshots the edited source, uses the recorded SDK, builds packages
with content-specific `.dev<build-identity>` versions, transfers and verifies
SHA256, runs **one guest `pacman -U --noconfirm` transaction**, and checks all
installed versions. It restarts the complete desktop session so clients release
old executable mappings. **Save work first: this closes desktop apps.**

Reopen apps and test the affected behavior. Installation and compositor startup
are separate from GUI verification. Record the source identity, VM/base image,
package versions/hashes, screenshots and measurements under `out/verification/`.
`out/vms/dev/deployment.json` records the transaction and restart result.

Useful options:

| Option | Behavior |
| --- | --- |
| `--build-profile dev` / `release` | Select debug iteration or optimized performance testing |
| `--online` | Permit fetching locked Cargo dependencies; deployment is otherwise offline |
| `--no-restart` | Keep the session; manually close/reopen updated applications to use new code |
| `--source-root PATH` | Explicit compatible workspace override; use the same workspace throughout |
| `--timeout SECONDS` | Guest command deadline, independent of compilation duration |

Development packages and receipts do not replace the ordinary package pointers
used for image composition. A later `./run` builds normal packages from the
source checkout. Never copy binaries over package-owned guest files to test a
fix. Ordinary library ABI changes require their corresponding runtime packages
and a fresh base; `deploy` handles application packages only.

## Incremental builds

Repeated `run` commands validate content inventories and reuse completed
bootstrap/runtime, loader, SDK, application and image stages when their inputs
and outputs match. Receipts live in `out/state/run/`; interrupted stages are not
reusable. Source changes normally reuse the essentials and SDK. Persistent Cargo
workspaces retain unchanged files and compiler outputs for deployment builds.

```sh
./run --profile desktop-dev --name dev --offline
./run --profile systemd --headless --verify
```

`--offline` requires cached archives, Cargo dependencies and the pinned compiler.
`--verify` runs the full preparation and integrity paths; it does not discard
valid lower-level compiler caches. Use `--jobs 2` for less compile parallelism.
There is no fixed compilation-time guarantee. Do not edit caches or receipts to
force reuse; inspect the failing inputs/log and retry after fixing the cause.

## Build speed and parallelism

Build commands choose a CPU/memory-aware job count by default, capped at eight.
The policy respects Linux CPU affinity and cgroup v2 CPU/memory limits and budgets
roughly 1.5 GiB per compiler job with 512 MiB left for coordination. Override it
explicitly for your machine:

```sh
./run --profile desktop-dev --name dev --jobs 8 --package-workers 2
python3 build.py build busybox zlib --jobs 8 --package-workers 2
```

`--jobs` is the total compiler budget. `--package-workers` limits simultaneous
native package builds, defaulting to two. Ready packages share that budget;
a lone ready package gets all available jobs. Target dependencies finish before
their consumers start. Runtime-only cycles do not serialize compilation. Use
`--package-workers 1` for sequential packages, or `--jobs 2` on a small machine.
Bootstrap, loader and app stages retain their existing ordering; this scheduler
parallelizes native packages, not independent Rust applications.

Native package cache keys follow each recipe's Python imports and their local
helpers, package resources, source pins, seed tools, bootstrap receipts and
native dependency archives. Computed Python imports use a conservative dependency
boundary for their consumer. Stage receipts track their own build code and inputs.
Adding an app or editing deployment/VM helpers does not invalidate native OS
packages. Timestamps or an identical file replacement alone do not invalidate a
stage; content, modes, ownership and symlink changes still do. The cache policy
upgrade requires one rebuild of existing native packages and stage receipts.

For optional C/C++ object reuse, the native package builder detects an existing
host `ccache`, or accepts an explicit executable:

```sh
DISTRO_CCACHE=/path/to/ccache python3 build.py build busybox zlib --jobs 8
DISTRO_CCACHE=0 ./run                         # Disable compiler caching
CCACHE_DIR="$PWD/out/compiler-cache" ccache --show-stats
```

The executable hash is recorded as a declared host seed. Objects stay in
`out/compiler-cache/` with a 5 GB limit. Builds hash the real compiler, toolchain
receipts and dependency bytes, use preprocessor mode, and exclude inherited
ccache configuration. They keep target sysroot checks in front of cache dispatch.
No host software is installed automatically. Without ccache, compilation runs
normally; Rust continues using its existing Cargo workspaces. Object-cache hits
also depend on compiler arguments and source paths; there is no promised speedup
for a first build. See the [ccache manual](https://ccache.dev/manual/latest.html)
for its cache behavior and statistics.

Keep build outputs between normal iterations. Use `dev` for app-only updates,
`vm --use` for reopening a VM, and `clean` when you need a full rebuild. A fresh
source build still compiles the bootstrap and kernel; these changes do not replace
source builds with prebuilt OS packages.

## Clean for a fresh build

Preview cleanup, then remove the generated toolchain, SDK, packages, application
compiler caches (including `out/compiler-cache/`), images, staging trees, build logs and build receipts:

```sh
./clean --dry-run
./clean
./run --profile desktop-dev --name fresh-dev --jobs 4
```

`./clean` forwards to `python3 build.py clean`. Stop builds and VMs first; cleanup
refuses to delete outputs when an existing build, deployment or saved-VM lock is
held. Do not start another build during cleanup. Persistent lock files remain so
the builder and cleaner continue to share the same locks.

Cleanup prints each target as it starts and finishes, with a live terminal bar,
elapsed time and a count of removed entries (files, directories and symlinks).
The percentage measures **completed top-level cleanup targets**, not bytes or
estimated time. Inside a large target, the entry counter and sampled current
path keep updating without a separate counting pass. Redirected/piped stderr
gets plain progress lines instead of terminal control sequences.

Live progress goes to stderr; stdout remains the final JSON summary, including
`entries_removed`, `seconds` and the saved `log` path. Every real cleanup saves a
unique timestamped log under `out/verification/clean/`, which survives cleanup.
Deletion failures and Ctrl+C record partial progress and the failure/interruption;
they do not report successful completion. Lock/path preflight failures happen
before deletion or log creation. `--dry-run` only prints the plan and creates no
cleanup log. An absent `out/` directory likewise needs no log or cleanup.

Source checkouts and local edits under `sources/` stay intact. Cleanup also
preserves downloaded archives under `out/sources/downloads/`, saved disks under
`out/vms/`, evidence under `out/verification/`, source bundles, contribution
checkouts and unrecognized output directories. It only deletes the pipeline's
known generated outputs; it does not run `git clean` or touch host caches.

Optional flags:

```sh
./clean --downloads             # Also remove downloaded source archives
./clean --vms                   # Also delete saved VM disks, data and firmware variables
./clean --downloads --vms       # Rebuild and download again with no saved VMs
```

The next build must recreate the toolchain and packages and can take substantial
time. Retaining archives avoids downloading them again; Cargo caches inside
generated app/loader directories are removed. Reusing a preserved VM name still
opens its original disk, so use a new name to test the freshly rebuilt base.
The cleaner does not repair cache invalidation or speed up ordinary iteration;
use `dev` for app updates and `vm --use` to reopen a saved disk.

## Base-system and desktop checks

For a systemd test window that stays open after startup checks, use
`./run --profile systemd`. For bounded checks that exit automatically:

```sh
./run --profile systemd --headless --output out/verification/systemd
./run --profile console --headless --output out/verification/console
```

These profiles use temporary disk snapshots. The default startup deadline is
600 seconds; `--timeout` accepts 1–3600. Accounts remain locked in the systemd
profile; it is a service/session test, rather than an interactive login.
See [testing](testing.md) for desktop, hover, password and upgrade procedures.

## Desktop qualification

The `desktop` image profile adds automated qualification units and a genuine
Wayland input/presentation probe. It is separate from normal `desktop-use` and
`desktop-dev` sessions. Follow the [desktop qualification procedure](testing.md#desktop-qualification)
after the normal desktop build inputs are ready.

## Audio and camera

Saved desktop launches support `--audio auto`, `pulse` or `none`; `auto` detects
WSLg/PulseAudio endpoints. To select a backend without rebuilding:

```sh
python3 build.py vm --use --development --name dev --audio pulse
python3 build.py vm --use --development --name dev --audio none
```

Choose one launch command at a time. Pulse mode requires a QEMU build with the
`pa` backend and an accessible `PULSE_SERVER`/WSLg socket. It exposes playback
and microphone input to the guest; the guest still needs working PipeWire/ALSA
policy. An initialized disk from an older image does not gain new media drivers
just by changing this flag.

`vm --use --usb-camera BUS:ADDRESS` optionally passes one Linux-attached USB
webcam to the VM. On WSL, first attach it to Linux using the
[Microsoft USB device instructions](https://learn.microsoft.com/en-us/windows/wsl/connect-usb).
Use its actual Linux bus/address and ensure read/write device access. The
launcher rejects a device without a USB video interface. Passing through a
camera does not establish portal consent, capture or screen-sharing behavior.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| QEMU window cannot open | Check GTK support and the WSLg display environment; see [setup](setup.md) |
| Low visible frame rate on WSL | Verify `.wslgconfig`, `weston.log`, Windows/guest display rates and KVM separately |
| TCG instead of KVM | Read the launcher's probe failure and check `/dev/kvm` access; do not run the builder as root |
| Rebuilt changes absent | Confirm the VM name and deployment receipt; a saved disk is not replaced by image composition |
| Missing guest-agent socket | Boot a `desktop-dev` image with `--use --development` and the matching name |
| Missing image | Use `run` to build it; `vm` only launches existing media |
| Cargo feature/API mismatch | Inspect actual framework/app sources and preserve local edits; review compatible changes together |
| Guest install fails | Inspect `deployment.json`; failed transactions/restarts do not imply rollback |
| Build fails | Read its reported log and fix the owning source/recipe, then retry |

For CLI details use `python3 build.py --help`, `run --help`, `clean --help`, `dev --help`, `deploy --help`,
`vm --help` or the individual stage help. Source snapshots, packages and logs
remain under `out/`; [architecture](architecture.md) maps their locations.
