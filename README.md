# Custom Distro

Custom Distro builds an independent Linux system from source, with the Telorgon
bootloader, desktop shell, framework, File Explorer, Settings and portal picker.
The desktop also includes Foot for command-line access.
Python coordinates the toolchain, packages, images and private QEMU VMs. The
guest uses source-built pacman/libalpm; it does not import another distro's
runtime packages or root filesystem.

## Get started

Follow these guides in order:

1. **[Set up your environment](docs/setup.md)** — prepare Linux or WSL2, install
   the host tools and Rustup, configure Git, KVM and desktop access, create your
   workspace and verify prerequisites.
2. **[Build and open your first VM](docs/build.md#first-build)** — choose a
   desktop profile, build the OS from source and check the running desktop.
3. **[Develop and test changes](docs/build.md#update-changed-applications-automatically)**
   — rebuild changed applications and install them into a saved development VM.

The environment guide covers one-time setup. The build guide covers daily
commands, progress, incremental builds, cleanup and troubleshooting. Rebuilding
an image does not upgrade an existing named VM's disk; use application deployment
or a new VM name when testing a new base.

## Explore the project

| Guide | What you will find |
| --- | --- |
| [Documentation index](docs/README.md) | All current guides and the recommended reading order |
| [Architecture](docs/architecture.md) | Runtime layers and the purpose of each package, source module, service and system policy component |
| [Component map](docs/components.md) | Layered diagram of every declared package and source module, grouped by function |
| [Source modules](docs/sources.md) | Component ownership, latest-main clones and portable source bundles |
| [Contributing](docs/contributing.md) | Source changes, package recipes, checks and pull requests |
| [Testing](docs/testing.md) | Reusable build, boot, installation and desktop test procedures |
| [Release requirements](docs/release.md) | Gates for installer/recovery, public updates and physical hardware |

Implement application and framework changes in their owning repositories under
`sources/`. Generated snapshots, caches and evidence belong under `out/`.
This is a development system; runtime reports qualify only the images and
packages they identify.
