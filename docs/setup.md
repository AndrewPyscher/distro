# Set up your development environment

Complete this guide once, then continue to [your first build](build.md#first-build).
This page prepares the host and workspace; the next guide builds the OS and VM.

You need an **x86_64 Linux host**, or **Ubuntu 24.04 under WSL2 with WSLg** on
Windows, Python 3.11 or newer, at least **16 GiB of Linux-visible RAM** and
**128 GiB of free disk** for the full desktop build. Build outputs and caches can
grow beyond that initial space budget. Internet access is needed for setup and
the first source downloads.

1. [Open a Linux terminal](#1-open-a-linux-terminal).
2. [Install host tools and Rust](#2-install-host-tools-and-rust).
3. [Create your workspace](#3-create-your-workspace).
4. [Verify the environment](#4-verify-the-environment).
5. Continue to [build and run](build.md#first-build).

Run the builder and QEMU as your normal Linux user. Host packages and the Rust
compiler are declared development seeds; the distro's runtime is built from
source. The build pipeline does not install host packages automatically.

## 1. Open a Linux terminal

### On Linux

Open a terminal on your x86_64 Linux host. The package commands below target
Ubuntu 24.04; other Linux distributions need equivalent tools. Continue to step 2.

### On Windows (WSL2)

In **Windows PowerShell as Administrator**, install WSL and Ubuntu if needed:

```powershell
wsl --install -d Ubuntu-24.04
```

Restart Windows if requested, open **Ubuntu**, and complete its first-run Linux
user setup. Use the Ubuntu terminal for the Linux commands in the rest of this
guide.

For an existing WSL installation, check it in **Windows PowerShell**:

```powershell
wsl --update
wsl --version
wsl --list --verbose
```

Ubuntu must show version `2`. If necessary, convert it with
`wsl --set-version Ubuntu-24.04 2`, using the name from the list. WSLg supplies
the GUI connection used by Linux QEMU; Microsoft's
[WSL installation](https://learn.microsoft.com/en-us/windows/wsl/install) and
[GUI application setup](https://learn.microsoft.com/en-us/windows/wsl/tutorials/gui-apps)
cover Windows and graphics-driver prerequisites.

Keep the workspace and `out/` in the **Linux filesystem**, such as `~/wip-os`,
rather than under `/mnt/c`. Check the resources visible to Linux:

```sh
free -h
df -h ~
```

If WSL has too little memory, follow [WSL memory and virtualization](#wsl-memory-and-virtualization)
before continuing.

## 2. Install host tools and Rust

In your **Ubuntu/Linux terminal**, install the complete host package list:

```sh
sudo apt update
sudo apt install -y build-essential bison bc m4 perl autoconf automake \
  libtool pkg-config meson ninja-build fakeroot zlib1g-dev xz-utils bzip2 \
  e2fsprogs gnupg python3 python3-venv python3-jinja2 cmake clang libclang-dev \
  curl ca-certificates git gh qemu-system-x86 qemu-system-gui ovmf
```

This includes GCC/G++, Meson/Ninja, Python virtual-environment support,
Clang/libclang for Rust bindings, the QEMU emulator and GUI, and OVMF firmware.
`gh` is the GitHub CLI used by the contributor workspace helper. The bootstrap
builds its pinned private Meson and additional generators under `out/`.

### Rustup and Rust toolchain

Install Rustup as your normal Linux user. Skip the installer if `rustup` is
already available. The [official Rustup instructions](https://rust-lang.github.io/rustup/installation/index.html)
allow installing the manager before selecting a compiler:

```sh
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain none
. "$HOME/.cargo/env"
rustup --version
```

Loading `$HOME/.cargo/env` makes a standard user installation available in the
current shell. Open a new terminal to pick up the installer's PATH changes in
later sessions. If an existing installation already provides `rustup` and
`cargo` on PATH, keep that installation.

Install the project-selected Rust compiler and both required targets:

```sh
rustup toolchain install nightly-2026-10-06 --profile minimal \
  --target x86_64-unknown-uefi --target x86_64-unknown-linux-gnu
```

Rustup supplies Cargo and Rust for the bootloader and desktop applications.
The build selects this toolchain explicitly; its bootloader pin is defined in
[`src/distro_build/boot.py`](../src/distro_build/boot.py).

## 3. Create your workspace

### Contributor workspace

For a new workspace, run in your **Linux terminal**:

```sh
mkdir -p ~/wip-os
git clone https://github.com/WIPOperatingSystemName/.github.git ~/wip-os/.github
python3 ~/wip-os/.github/setup.py
```

The helper clones `distro`, synchronizes its six source components to organization
`main`, asks you to sign in to GitHub if needed, and creates or reuses your personal
forks for distro and those components. It sets `origin` to the organization and
`fork` to your push destination. It preserves existing branches and local work;
rerunning it fast-forwards component clones when safe and stops on conflicts.
Older distro checkouts still use their legacy submodule setup until updated.

If `~/wip-os/.github` already exists, skip the clone and rerun its `setup.py`.
Open **`~/wip-os`** in your editor or coding agent so the organization docs and
component repositories are available together. The build checkout is
`~/wip-os/distro`, and application/framework source lives under its `sources/`.

Under WSL, the helper also offers to match WSLg's presentation rate to a selected
Windows display. Choose the display where you will use QEMU, or press Enter to
keep an existing setting or skip. It preserves other settings and backs up the
configuration before changes. If it requests a WSL restart, save work in every
WSL session, run `wsl --shutdown` in **Windows PowerShell**, and reopen Ubuntu.
This stops every WSL distribution; the helper never shuts it down automatically.
See [WSLg frame rate](#wslg-frame-rate) for verification and manual configuration.

### Build without a GitHub account

If you only want to build and run the distro, use this checkout **instead of**
the contributor helper:

```sh
mkdir -p ~/wip-os
git clone https://github.com/WIPOperatingSystemName/distro.git ~/wip-os/distro
cd ~/wip-os/distro
python3 build.py sources sync
```

For an existing checkout, inspect `git status`, update distro while preserving
local work, then run `python3 build.py sources sync`. Existing component clones
are reused and safely fast-forwarded to organization `main`; conflicting local
work requires deliberate integration. See [source modules](sources.md) for
migration details and `--offline` source replay.

## 4. Verify the environment

Run these checks in your **Linux terminal**, from the distro directory:

```sh
cd ~/wip-os/distro
python3 --version
python3 build.py doctor
cargo +nightly-2026-10-06 --version
rustc +nightly-2026-10-06 --version
rustup target list --installed --toolchain nightly-2026-10-06
qemu-system-x86_64 --version
qemu-system-x86_64 -display help
ls /usr/share/OVMF/OVMF_CODE_4M.fd /usr/share/OVMF/OVMF_VARS_4M.fd
```

You are ready to build when:

- Python is version 3.11 or newer and `doctor` finishes without an error.
- Cargo and Rust print their versions, and the target list contains
  `x86_64-unknown-linux-gnu` and `x86_64-unknown-uefi`.
- QEMU prints its version, its display list includes `gtk`, and both OVMF
  firmware files are present (the paths above are for Ubuntu).
- On WSL, `DISPLAY` or `WAYLAND_DISPLAY` is set by WSLg. You can check with
  `printenv DISPLAY WAYLAND_DISPLAY`; preserve the environment WSLg supplies.

`doctor` checks the declared host seeds and QEMU Guest Agent's Python venv
support. It does not check Rustup/Cargo, QEMU or firmware, so complete the
separate checks above. [KVM and firmware](#kvm-and-firmware) covers firmware
overrides and optional hardware acceleration on other hosts. Host systemd is not
required for the guest's systemd desktop session.

**Next: [build and open your first VM](build.md#first-build).**

## Optional host configuration

### WSL memory and virtualization

Check what Ubuntu can use with `free -h` and `df -h .`. If WSL's memory cap is
too low, adjust it in Windows WSL Settings or merge appropriate values into
`%USERPROFILE%\.wslconfig`. For a host with enough RAM, an example is:

```ini
[wsl2]
memory=16GB
swap=8GB
nestedVirtualization=true
guiApplications=true
```

Leave RAM available for Windows. Nested virtualization depends on the host and
WSL kernel; this setting alone does not establish KVM availability. Microsoft
documents these controls in [WSL configuration](https://learn.microsoft.com/en-us/windows/wsl/wsl-config).
Save work and stop running guest VMs before applying changes with
`wsl --shutdown` in PowerShell; it stops every WSL distribution. Reopen Ubuntu.

### WSLg frame rate

If you used the workspace helper, verify its setting after restarting WSL:

```sh
python3 ~/wip-os/.github/setup.py --wslg-refresh-rate check
```

To configure a particular active display rate through the helper, pass
`--wslg-refresh-rate 144` (replace 144 with your display's active rate).
`--wslg-refresh-rate skip` leaves it unchanged. Without an interactive terminal,
the default skips configuration. Verification checks Weston's configured rate;
visible FPS also depends on the guest and Windows display.

For manual configuration, follow the steps below. Legacy inbox WSL may require
an elevated Windows terminal to edit its system-wide configuration; the helper
reports a permissions failure rather than requesting elevation.

For high-refresh testing, configure WSLg's presentation rate before measuring
the VM. Microsoft's [frame-rate explanation](https://github.com/microsoft/wslg/wiki/Controlling-WSLg-frame-rate)
documents a default ceiling of 60 FPS. Match the setting to your Windows
display's active rate; the example below uses **144 Hz**.

For Store-installed WSL, edit **`%USERPROFILE%\.wslgconfig` on Windows**
(for example `C:\Users\your-name\.wslgconfig`). For inbox WSL, use
`C:\ProgramData\Microsoft\WSL\.wslgconfig`. Merge into the existing section,
preserving other entries:

```ini
[system-distro-env]
WESTON_RDP_MONITOR_REFRESH_RATE=144
```

This is `.wslgconfig`; the memory settings above belong in `.wslconfig`.
Microsoft documents the [file locations and restart requirement](https://github.com/microsoft/wslg/wiki/WSLg-Configuration-Options-for-Debugging).
After stopping the guest and saving work, run in **Windows PowerShell**:

```powershell
wsl --shutdown
```

Reopen Ubuntu and verify that WSLg read the setting:

```sh
rg 'rdp_monitor_refresh_rate' /mnt/wslg/weston.log
```

If `rg` is not installed, use `grep` for this check. For 144 Hz, the log should
report `rdp_monitor_refresh_rate: 144000` (millihertz). If it does not, check the
file location, section name and that WSL fully restarted.

For a first build, continue with [build and run](build.md#first-build). To reopen
an existing development VM, follow [saved VMs](build.md#reopen-a-saved-vm).
The WSLg setting needs no distro image rebuild. Use QEMU on the intended Windows
monitor and check the guest display mode too: its refresh rate is a separate
limit. Guest FPS and renderer CPU timings do not prove the rate visible on the
Windows monitor. Remove the entry and restart WSL to restore its default.

### KVM and firmware

The launcher probes KVM and otherwise uses slower TCG software emulation.
Check device access as your normal user:

```sh
ls -l /dev/kvm
test -r /dev/kvm && test -w /dev/kvm
```

If `/dev/kvm` exists and access is restricted to the `kvm` group, add your user
to that group with `sudo usermod -aG kvm "$USER"`, then start a new login session.
Do not run the whole builder as root. The launcher's `VM acceleration: KVM`
message and VM report establish whether its initialization probe succeeded.
On WSL, hardware/Windows/WSL support may still prevent nested KVM.

OVMF is detected from the installed firmware paths. For an explicit matching
Ubuntu firmware pair:

```sh
export OVMF_CODE=/usr/share/OVMF/OVMF_CODE_4M.fd
export OVMF_VARS=/usr/share/OVMF/OVMF_VARS_4M.fd
```

Use code and variables from the same build and size, without Secure Boot
enforcement. QEMU copies variables into its private VM directory.

## Troubleshooting setup

### Check host prerequisites

If `./run` reports `doctor failed; build-and-run stopped`, show the underlying
prerequisite error from `~/wip-os/distro`:

```sh
python3 build.py doctor
```

For example:

```text
{"error": "missing host seed tool: gcc", "command": "doctor"}
```

The host GCC/G++ compilers and Make are needed to bootstrap the source-built
toolchain. On Ubuntu, including Ubuntu under WSL, `build-essential` supplies
these tools and development headers. It is included in the installation
command in step 2; to fix a missing compiler on an otherwise configured host:

```sh
sudo apt update
sudo apt install build-essential
gcc --version
g++ --version
make --version
```

If the next error is `missing host seed tool: meson`, install the native build
tools from the installation command in step 2:

```sh
sudo apt install meson ninja-build pkg-config
meson --version
ninja --version
pkg-config --version
```

QEMU Guest Agent's build creates a private Python virtual environment. On
Ubuntu/Debian, `python3-venv` supplies the `ensurepip` support it needs; having
`python3` alone is insufficient. If the build reports `Python's ensurepip module
is not found` or `python venv creation failed`, install the missing prerequisite:

```sh
sudo apt install python3-venv
python3 build.py doctor
```

The host audit checks this support using the `/usr/bin/python3` interpreter used
by package builds. It accepts either `ensurepip` or an existing system pip and
setuptools. Retry your original build command without cleaning; matching
completed build outputs are reused.

Rerun `python3 build.py doctor` after installation. It stops at the first missing
required tool; if another is reported, complete the installation command in
step 2 and check again. Retry `./run` once the host audit succeeds. The build pipeline
does not install these host prerequisites automatically.

### QEMU availability

`./run` builds the guest OS image and starts a VM using QEMU on your Linux host.
QEMU and the OVMF firmware must already be installed; the build pipeline does
not install them. If you see
`QEMU is missing; set QEMU_SYSTEM_X86_64 to an existing host tool`, the launcher
cannot find the emulator executable.

On Ubuntu, including Ubuntu under WSL, install the emulator packages from the
installation command in step 2 and verify that QEMU runs:

```sh
sudo apt update
sudo apt install qemu-system-x86 qemu-system-gui ovmf
qemu-system-x86_64 --version
qemu-system-x86_64 -display help
```

The QEMU display list must include `gtk`. Under WSLg, `DISPLAY` or
`WAYLAND_DISPLAY` should already be set; preserve the environment WSLg supplies.
Host systemd is not required for the guest's systemd desktop session.

If QEMU is installed in a custom location, point to its existing executable:

```sh
export QEMU_SYSTEM_X86_64=/absolute/path/to/qemu-system-x86_64
"$QEMU_SYSTEM_X86_64" --version
```

An incorrect `QEMU_SYSTEM_X86_64` override also causes the missing-QEMU error.
Use `unset QEMU_SYSTEM_X86_64` to return to automatic discovery of the installed
system executable. After fixing QEMU, retry `./run` from your checkout in the
same terminal.

If a source download reports `Network is unreachable`, check internet access
inside the same Linux/WSL terminal. Installing more build tools will not repair
network routing. After restoring connectivity, retry the build; do not clean
completed outputs. For build-stage logs and other errors, use
[build troubleshooting](build.md#troubleshooting).
