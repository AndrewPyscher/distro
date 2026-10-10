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
Failures stop at the affected stage and report its log. `./run` defaults to 8
compile jobs for the bootstrap, native toolkit, packages and applications.
Use `--jobs N` to choose another count.

Telorgon starts the local `custom` desktop session. Open applications from the
launcher and test mouse/keyboard behavior. The development profile adds the
source-built QEMU Guest Agent and private deployment channel.

### Build progress

`./run` and `python3 build.py run` show progress automatically, including on a
first build with no cached outputs. The display covers host/recipe checks,
downloads, the bootstrap toolchain and its verification, package tools, OS
packages, Telorgon EFI, the desktop SDK and applications, OS image assembly,
and private VM preparation/startup. Console/systemd builds omit desktop steps.

The bar counts completed steps. Package/application counts and bootstrap stage
names show progress inside larger steps; percentages describe completed work
units, rather than estimated time. Compiling GCC can hold the overall percentage
for a long time. The activity indicator and elapsed time keep updating while
commands run or cached inputs are checked. Verified cached steps are marked as
reused. Failures and interruptions stop the bar at the affected step.

In a terminal the display updates in place on stderr. Redirected output uses
plain progress lines with a heartbeat every 30 seconds. Structured events,
command log paths and progress details are saved to the printed
`out/logs/run-<profile>-<timestamp>.jsonl` file. Existing compiler and VM logs
remain in their usual locations. Use `./run --no-progress` to retain the previous
JSON event output without a progress display or additional progress log.

For normal desktops, 100% means the OS image and private VM preparation are
complete and QEMU has started; guest boot and GUI behavior still require actual
qualification. The bar stops before waiting for you to close QEMU. Console and
systemd runs finish the bar when their expected boot markers are observed.

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

## Clean build outputs

Stop builds, deployments and QEMU before cleaning. From the checkout root:

```sh
./clean --dry-run
./clean
./run --profile desktop-dev --name fresh-dev
```

`./clean` is a shell launcher for `python3 build.py clean`. It clears everything
under `out/` except `out/vms/`: bootstrap tools, compiled packages, images, SDKs,
generated source snapshots, Cargo caches, downloaded archives, build receipts,
logs and test evidence. Save any evidence you need before cleaning. Source
checkouts and their local changes remain in `sources/`. The next build needs
network access to fetch inputs again; cleanup does not clear host Rust tools
or caches outside `out/`.

The command scans first, then shows a progress bar based on the number of files,
directories and symlinks removed, rather than bytes or estimated time. Redirected
output uses periodic progress lines. `--dry-run` lists the directories and entry
counts without deleting anything. Cleanup refuses symlinked `out/` directories,
does not follow symlinks within the outputs, and stops if an existing managed
build, deployment or VM lock is busy. Do not start another job during cleanup;
individual build commands do not all share a global lock.

To also delete **all saved VM disks, guest files and firmware variables**:

```sh
./clean --all --dry-run
./clean --all
```

Both modes leave the `out/` directory itself in place. Keeping a saved VM does
not upgrade its disk: after rebuilding, use a new VM name for the fresh base.
For CI or an explicitly selected distro checkout, use
`python3 build.py --project /path/to/distro clean [--all] [--dry-run]`.

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

For CLI details use `python3 build.py --help`, `run --help`, `dev --help`, `deploy --help`,
`vm --help` or the individual stage help. Source snapshots, packages and logs
remain under `out/`; [architecture](architecture.md) maps their locations.
