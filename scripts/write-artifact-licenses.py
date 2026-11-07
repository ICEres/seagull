#!/usr/bin/env python3
"""Write the project and runtime dependency licenses for a build artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
LICENSE_NAMES = ("LICENSE", "LICENCE", "COPYING", "NOTICE")


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read package metadata: {path}") from exc


def license_files(directory: Path) -> list[Path]:
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file()
        and any(path.name.upper().startswith(name) for name in LICENSE_NAMES)
    )


def license_text(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"cannot read license file: {path}") from exc
    if not text.strip():
        raise RuntimeError(f"license file is empty: {path}")
    return text.rstrip() + "\n"


def package_json_candidates(package: str, start: Path) -> Iterable[Path]:
    current = start.resolve()
    for directory in (current, *current.parents):
        if directory.name == "node_modules":
            yield directory / package / "package.json"
        else:
            yield directory / "node_modules" / package / "package.json"


def find_node_package(package: str, start: Path) -> Path | None:
    for candidate in package_json_candidates(package, start):
        if candidate.is_file():
            return candidate.resolve()
    return None


def node_dependencies(app_dir: Path, extras: list[str]) -> list[tuple[str, str, list[Path]]]:
    root_package = read_json(app_dir / "package.json")
    optional_roots = root_package.get("optionalDependencies") or {}
    names = dict.fromkeys([*(root_package.get("dependencies") or {}), *optional_roots, *extras])
    queue = [(name, app_dir, name in optional_roots) for name in names]
    seen: set[Path] = set()
    result: list[tuple[str, str, list[Path]]] = []

    while queue:
        name, parent_dir, optional = queue.pop(0)
        package_json = find_node_package(name, parent_dir)
        if package_json is None:
            if optional:
                continue
            raise RuntimeError(f"runtime Node package is not installed: {name}")
        package_dir = package_json.parent
        if package_dir in seen:
            continue
        seen.add(package_dir)
        metadata = read_json(package_json)
        for field in ("dependencies", "optionalDependencies", "peerDependencies"):
            queue.extend(
                (dependency, package_dir, field != "dependencies")
                for dependency in (metadata.get(field) or {})
            )

        files = license_files(package_dir)
        if package_dir.is_relative_to(ROOT / "packages"):
            # Workspace packages are covered by the project's root MIT license.
            result.append((metadata.get("name", name), metadata.get("version", "unknown"), []))
        else:
            if not files:
                raise RuntimeError(f"no license/notice file found for Node package: {name}")
            result.append((metadata.get("name", name), metadata.get("version", "unknown"), files))

    return sorted(result, key=lambda item: (item[0], item[1]))


def go_modules(module_dir: Path) -> list[tuple[str, str, list[Path]]]:
    command = ["go", "list", "-deps", "-json", "./cmd/lambda"]
    try:
        completed = subprocess.run(
            command,
            cwd=module_dir,
            check=True,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise RuntimeError("go list failed for ./cmd/lambda") from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip().splitlines()[-1] if exc.stderr else "unknown error"
        raise RuntimeError(f"go list failed for ./cmd/lambda: {detail}") from exc

    modules: dict[tuple[str, str, str], tuple[str, str, list[Path]]] = {}
    decoder = json.JSONDecoder()
    payload = completed.stdout
    offset = 0
    while offset < len(payload):
        while offset < len(payload) and payload[offset].isspace():
            offset += 1
        if offset == len(payload):
            break
        item, end = decoder.raw_decode(payload, offset)
        offset = end
        module = item.get("Module")
        if not module or not module.get("Dir") or module.get("Path") == "std":
            continue
        path = Path(module["Dir"]).resolve()
        if path == module_dir.resolve() or module.get("Path", "").startswith("seagull/"):
            continue
        key = (module.get("Path", ""), module.get("Version", ""), str(path))
        if key in modules:
            continue
        files = license_files(path)
        if not files:
            raise RuntimeError(f"no license/notice file found for Go module: {module.get('Path')}")
        modules[key] = (module.get("Path", ""), module.get("Version", "unknown"), files)

    goroot = subprocess.run(
        ["go", "env", "GOROOT"], check=True, capture_output=True, text=True
    ).stdout.strip()
    goroot_path = Path(goroot)
    goroot_files = license_files(goroot_path)
    if not goroot_files:
        goroot_files = license_files(goroot_path.parent)
    if not goroot_files:
        raise RuntimeError(f"no Go toolchain license found under GOROOT: {goroot}")
    modules[("Go toolchain", "runtime", str(goroot_path))] = ("Go toolchain", "runtime", goroot_files)
    return sorted(modules.values(), key=lambda item: (item[0], item[1]))


def write_output(output: Path, entries: list[tuple[str, str, list[Path]]]) -> None:
    root_license = ROOT / "LICENSE"
    if not root_license.is_file():
        raise RuntimeError(f"project LICENSE is missing: {root_license}")
    chunks = ["Seagull project\n================\n\n", license_text(root_license), "\n"]
    for name, version, files in entries:
        if not files:
            continue
        chunks.append(f"{name} {version}\n{'-' * (len(name) + len(version) + 1)}\n\n")
        for path in files:
            chunks.append(f"--- {path.name} ---\n")
            chunks.append(license_text(path))
            chunks.append("\n")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(chunks), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=("node", "go"))
    parser.add_argument("directory", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--extra", action="append", default=[])
    args = parser.parse_args()
    try:
        if args.kind == "node":
            entries = node_dependencies(args.directory.resolve(), args.extra)
        else:
            entries = go_modules(args.directory.resolve())
        write_output(args.output.resolve(), entries)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {args.output} ({len(entries)} components)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
