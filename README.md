# Custom Distro

Custom Distro builds an independent Linux system from source, with the Telorgon
bootloader, desktop shell, framework, File Explorer, Settings and portal picker.
Python coordinates the toolchain, packages, images and private QEMU VMs. The
guest uses source-built pacman/libalpm; it does not import another distro's
runtime packages or root filesystem.

## Start here

Set up [Linux or WSL2/WSLg](docs/setup.md) first, including
[Rustup and Cargo](docs/setup.md#rustup-and-rust-toolchain),
[host compiler checks](docs/setup.md#check-host-prerequisites),
[QEMU and OVMF](docs/setup.md#qemu-availability) and the
[WSLg frame-rate setting](docs/setup.md#wslg-frame-rate) for high-refresh testing.
Run from the checkout in a Linux terminal:

```sh
./run --profile desktop-dev --name dev
```

This builds the development image and opens a saved VM. Builds choose a
CPU/memory-aware job count up to 8; set `--jobs N` to choose another count.
Open File Explorer and Settings from Telorgon's launcher. Close the guest normally when finished;
its disk and firmware variables remain under `out/vms/dev/`.

`./run` shows a live progress bar with the current build step and elapsed time,
from the toolchain through OS image assembly and VM startup. Progress counts
completed steps, whose durations vary. Use `--no-progress` for JSON event output.

To reopen that VM without building:

```sh
python3 build.py vm --use --development --name dev
```

## Change source and test it

Edit the owning repository under `sources/`. Keep QEMU running, then use a second
Linux terminal to discover, build and install changed apps through guest pacman:

```sh
python3 build.py dev --name dev --plan --adopt-base
python3 build.py dev --name dev --adopt-base --build-profile release
```

Use `--adopt-base` only for the VM's first development update, after reviewing
the plan and confirming its base matches your workspace. Later updates use
`python3 build.py dev --name dev --build-profile release`.
The command fetches canonical upstream references and stops if integration is
needed; it preserves local edits and source pins. It rebuilds only changed app
packages, including consumers of framework changes, and leaves the OS image
alone. Shell updates restart the desktop and close apps, so save work first;
ordinary apps need reopening. Test the actual interaction after installation.
See the [automatic update workflow](docs/build.md#update-changed-applications-automatically)
for base changes, offline work and new application registration.
Generated snapshots under `out/` are build outputs; implement fixes in source.

For a normal desktop image without the deployment channel, use `./run`.
For a bounded base-system boot check, use:

```sh
./run --profile systemd --headless
```

See [build and run](docs/build.md) for saved-disk behavior, cache reuse, profiles,
audio/camera controls and troubleshooting. Rebuilding an image does not upgrade
an existing named VM's disk; deploy apps or use a new VM name for a fresh base.

Build commands automatically choose a CPU/memory-aware job count. Native packages
share that budget across ready builds; `--jobs` and `--package-workers` override
the defaults. Optional ccache support keeps C/C++ objects under `out/`. See
[build speed](docs/build.md#build-speed-and-parallelism) for cache behavior and controls.

For a fresh source build, preview with `./clean --dry-run`, then run `./clean`.
It shows live progress and saves cleanup logs under `out/verification/clean/`.
It keeps saved VM disks and downloaded archives; `--vms` and `--downloads`
explicitly remove those too, or use `--all` for both. See
[cleanup options](docs/build.md#clean-for-a-fresh-build).

## Documentation

The [documentation index](docs/README.md) covers environment setup, daily
commands, testing, architecture, packages, source ownership and contributions.
Runtime reports belong under `out/verification/` and identify their actual
images and installed packages. This is a development system; installer/recovery,
public update delivery and physical hardware need the separate gates in
[release requirements](docs/release.md).
