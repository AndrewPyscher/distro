#!/usr/bin/env python3
"""Render the complete component map, or check its coverage and committed assets."""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import sys
import textwrap
import tomllib
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)


def catalog() -> tuple[list[dict], dict[str, Path], dict[str, dict]]:
    layers = tomllib.loads((ROOT / "docs/architecture-components.toml").read_text())["layers"]
    packages = {}
    for filename in ("package.toml", "application.toml"):
        for path in sorted((ROOT / "packages").glob(f"*/{filename}")):
            name = tomllib.loads(path.read_text())["package"]["name"]
            if name in packages:
                raise ValueError(f"Duplicate package declaration: {name}")
            packages[name] = path.relative_to(ROOT)
    projects = tomllib.loads((ROOT / "source-projects.toml").read_text())["projects"]
    for key, declared in (("packages", packages), ("projects", projects)):
        entries = Counter(name for layer in layers for group in layer["groups"]
                          for name in group.get(key, []))
        missing = sorted(set(declared) - entries.keys())
        unknown = sorted(entries.keys() - set(declared))
        repeated = sorted(name for name, count in entries.items() if count != 1)
        if missing or unknown or repeated:
            raise ValueError(f"{key}: missing={missing}, unknown={unknown}, repeated={repeated}")
    return layers, packages, projects


def element(parent: ET.Element, tag: str, **attrs: object) -> ET.Element:
    return ET.SubElement(parent, f"{{{SVG_NS}}}{tag}", {
        key.replace("_", "-"): str(value) for key, value in attrs.items()
    })


def text(parent: ET.Element, x: int, y: int, content: str, *, size: int = 15,
         color: str = "#334155", weight: int = 400, mono: bool = False) -> None:
    node = element(parent, "text", x=x, y=y, fill=color, font_size=size,
                   font_weight=weight, font_family="DejaVu Sans Mono, monospace" if mono
                   else "DejaVu Sans, sans-serif")
    node.text = content


def render_svg(layers: list[dict], package_count: int, project_count: int) -> str:
    width, margin, gap = 1200, 32, 16
    content_width = width - 2 * margin
    positions = []
    y = 160
    for layer in layers:
        y += 64
        rows = []
        groups = layer["groups"]
        for offset in range(0, len(groups), 3):
            row = []
            row_groups = groups[offset:offset + 3]
            card_width = (content_width - (len(row_groups) - 1) * gap) // len(row_groups)
            for group in row_groups:
                notes = textwrap.wrap(group["description"], width=(card_width - 32) // 8)
                entries = [("P", name) for name in group.get("packages", [])]
                entries += [("S", f"sources/{name}") for name in group.get("projects", [])]
                height = 76 + len(notes) * 18 + len(entries) * 22
                row.append((group, notes, entries, height))
            row_height = max(card[3] for card in row)
            rows.append((y, row_height, card_width, row))
            y += row_height + gap
        positions.append((layer, rows))
        y += 12
    height = y + 54
    svg = ET.Element(f"{{{SVG_NS}}}svg", {
        "width": str(width), "height": str(height), "viewBox": f"0 0 {width} {height}",
        "role": "img", "aria-labelledby": "title description",
    })
    element(svg, "title", id="title").text = "Custom Distro component architecture"
    element(svg, "desc", id="description").text = (
        f"All {package_count} declared packages and {project_count} source projects, grouped "
        "by function from applications to the Linux kernel. Boot, development and alternate "
        "components are shown separately. See components.md for linked text equivalents."
    )
    element(svg, "rect", width=width, height=height, fill="#f8fafc")
    text(svg, margin, 48, "Custom Distro", size=30, weight=700, color="#0f172a")
    text(svg, margin, 78, "Component architecture · from applications to the Linux kernel", size=19)
    text(svg, margin, 108, f"{package_count} package recipes · {project_count} source projects · grouped by function", size=15)
    text(svg, margin, 137, "P = package recipe     S = source repository     Placement shows responsibility, not every dependency.", size=14)
    for index, (layer, rows) in enumerate(positions, start=1):
        top = rows[0][0] - 64
        color = layer["color"]
        element(svg, "rect", x=margin, y=top, width=5, height=43, rx=2, fill=color)
        text(svg, margin + 17, top + 20, f"{index:02d}  {layer['title']}", size=20,
             color=color, weight=700)
        text(svg, margin + 17, top + 43, layer["description"], size=14)
        for row_y, row_height, card_width, row in rows:
            for column, (group, notes, entries, _) in enumerate(row):
                x = margin + column * (card_width + gap)
                element(svg, "rect", x=x, y=row_y, width=card_width,
                        height=row_height, rx=9, fill="#ffffff", stroke="#cbd5e1")
                element(svg, "rect", x=x, y=row_y + 12, width=4,
                        height=row_height - 24, rx=2, fill=color)
                text(svg, x + 16, row_y + 29, group["title"], size=17,
                     color="#0f172a", weight=700)
                line_y = row_y + 53
                for note in notes:
                    text(svg, x + 16, line_y, note, size=14)
                    line_y += 18
                line_y += 14
                for kind, name in entries:
                    badge_color = "#1d4ed8" if kind == "P" else "#7c3aed"
                    text(svg, x + 16, line_y, kind, size=12, color=badge_color, weight=700)
                    text(svg, x + 36, line_y, name, size=14, mono=True)
                    line_y += 22
    text(svg, margin, height - 35, "Catalog view: profiles select installed components; SDK features determine available capabilities.", size=14)
    text(svg, margin, height - 13, "Recipe and source manifests remain authoritative. Linked component index: docs/components.md", size=14)
    ET.indent(svg, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(svg, encoding="unicode") + "\n"


def render_markdown(layers: list[dict], packages: dict[str, Path], projects: dict[str, dict]) -> str:
    lines = [
        "# Component architecture",
        "",
        "<!-- Generated by tools/render-architecture.py; edit docs/architecture-components.toml. -->",
        "",
        "This map places every declared OS package and every registered source repository",
        "by its primary function. Read the [runtime overview](architecture.md#runtime-layers)",
        "first for the relationships between applications, the shell, services and Linux.",
        "",
        f"Coverage: **{len(packages)} package recipes and {len(projects)} source projects**.",
        "Kernel subsystems and transitive Cargo dependencies remain inside their owning",
        "components. Repository infrastructure is listed [below](#repository-infrastructure).",
        "",
        "[![Layered map of all package recipes and source projects, grouped by function](diagrams/components.svg)](diagrams/components.svg)",
        "",
        "Open the image for the full-size diagram. The linked tables below provide the",
        "same grouping as text. **P** means a package recipe; **S** means a source repository.",
        "",
        "## Reading the map",
        "",
        "- Layers group responsibilities, rather than requiring calls to pass through",
        "  every layer. Applications and services can use libraries and kernel APIs directly.",
        "- A group can include daemons, libraries, command-line tools and data. Only the",
        "  service programs run as daemons; their libraries are loaded by callers.",
        "- Telorgon is shared Rust SDK code used by both the shell and applications, and",
        "  by the bootloader for boot UI. It is not a separate desktop service. Its",
        "  source workspace contains the SDK, its macro companion and a shader build tool.",
        "- This is the available catalog. [Profiles](../profiles) select an installed",
        "  runtime closure; the map does not claim that every package is in every image.",
        "  Desktop profiles use systemd's udev/libudev provider instead of standalone eudev.",
        "- Boot handoff and development/build components have separate bands. The",
        "  bootloader runs before Linux; the QEMU Guest Agent is for `desktop-dev`.",
        "- Component presence does not establish runtime qualification. In particular,",
        "  the CPU desktop's screen-sharing support depends on the selected SDK capability.",
        "",
        "## Component index",
        "",
    ]
    for layer in layers:
        lines += [f"### {layer['title']}", "", layer["description"], "",
                  "| Function | Components | Responsibility |",
                  "| --- | --- | --- |"]
        for group in layer["groups"]:
            links = [f"P: [`{name}`](../{packages[name].as_posix()})"
                     for name in group.get("packages", [])]
            links += [f"S: [`sources/{name}`]({projects[name]['repository'].removesuffix('.git')})"
                      for name in group.get("projects", [])]
            lines.append(f"| {group['title']} | {'<br>'.join(links)} | {group['description']} |")
        lines.append("")
    lines += [
        "## Repository infrastructure",
        "",
        "These areas define or produce the system; they are outside the running kernel",
        "and userspace stack. Host seed tools and bootstrap generators are build inputs.",
        "",
        "| Area | Role |",
        "| --- | --- |",
        "| [`sources/`](sources.md), [`source-projects.toml`](../source-projects.toml) | Owning component clones and registered source inputs |",
        "| [`packages/`](../packages), [`profiles/`](../profiles) | Package definitions and image/runtime selection |",
        "| [`system/`](../system) | Guest init scripts, service units, session defaults and system policy installed in images |",
        "| [`bootstrap/`](../bootstrap) | Source pins and stages for the cross-toolchain and native build generators |",
        "| [`src/distro_build/`](../src/distro_build), [`build.py`](../build.py), [`run`](../run), [`clean`](../clean), [`pyproject.toml`](../pyproject.toml) | Python coordination for source synchronization, package builds, image composition, VMs, deployment and cleanup |",
        "| [`tools/`](../tools), [`tests/`](../tests) | Qualification utilities, documentation rendering and automated checks |",
        "| [`.github/workflows/`](../.github/workflows), [`.integration/`](../.integration) | CI definitions and integration bundle records |",
        "| [`docs/`](README.md), [`README.md`](../README.md), [`AGENTS.md`](../AGENTS.md), [`LICENSE`](../LICENSE) | Project documentation, contribution rules and licensing |",
        "| `out/` | Generated snapshots, caches, packages, images, private VM state and actual test evidence; see the [artifact inventory](architecture.md#artifact-inventory) |",
        "",
        "Package versions, archive checksums, dependency lists and source origins remain",
        "authoritative in their manifests. This map intentionally records only functional",
        "placement. See [packages](packages.md) for dependency semantics and",
        "[source modules](sources.md) for repository ownership.",
        "",
        "## Updating the map",
        "",
        "When adding or renaming a package or registered source project, update its group",
        "in [`architecture-components.toml`](architecture-components.toml), then regenerate:",
        "",
        "```sh",
        "python3 tools/render-architecture.py",
        "python3 tools/render-architecture.py --check",
        "```",
        "",
        "Run these commands from the distro root. The check rejects missing, unknown or",
        "multiply listed components and stale generated documentation. It runs in CI.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check coverage and generated files without writing")
    args = parser.parse_args()
    try:
        layers, packages, projects = catalog()
        outputs = {
            ROOT / "docs/diagrams/components.svg": render_svg(layers, len(packages), len(projects)),
            ROOT / "docs/components.md": render_markdown(layers, packages, projects),
        }
        stale = []
        for path, content in outputs.items():
            if args.check:
                if not path.is_file() or path.read_text() != content:
                    stale.append(str(path.relative_to(ROOT)))
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
        if stale:
            raise ValueError(f"Stale component documentation: {', '.join(stale)}; run python3 tools/render-architecture.py")
    except (ValueError, KeyError) as error:
        print(error, file=sys.stderr)
        return 1
    print(f"{'Checked' if args.check else 'Rendered'} {len(packages)} packages and {len(projects)} source projects")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
