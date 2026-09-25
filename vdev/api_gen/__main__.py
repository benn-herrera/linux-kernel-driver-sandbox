"""Stub CLI: validates an .adef.toml definition parses, then writes empty
placeholders at the real emitters' output paths. Real emitters (C header,
ABI pin translation unit, LuaJIT base module) land later.
"""

import argparse
import sys
import tomllib
from pathlib import Path

SUFFIX = ".adef.toml"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="generate userspace API artifacts from an API definition "
        "(stub: empty placeholders)"
    )
    parser.add_argument("definition", type=Path, help="path to a *.adef.toml file")
    parser.add_argument("--generated", type=Path, required=True, help="output directory")
    args = parser.parse_args()

    definition: Path = args.definition
    if not definition.name.endswith(SUFFIX):
        print(f"api_gen: {definition}: file name must end in {SUFFIX}", file=sys.stderr)
        return 2

    try:
        with definition.open("rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        print(f"api_gen: {definition}: {e}", file=sys.stderr)
        return 2

    general = data.get("general")
    if not isinstance(general, dict):
        print(f"api_gen: {definition}: missing [general] table", file=sys.stderr)
        return 2
    if not isinstance(general.get("name"), str):
        print(f"api_gen: {definition}: missing general.name string", file=sys.stderr)
        return 2
    if "function" not in data:
        print(f"api_gen: {definition}: missing [function] table", file=sys.stderr)
        return 2

    stem = definition.name[: -len(SUFFIX)]
    generated: Path = args.generated
    generated.mkdir(parents=True, exist_ok=True)
    for name in (f"{stem}.h", f"{stem}_pins.cpp", f"{stem}.lua"):
        (generated / name).write_text("", encoding="utf-8")

    print(f"api_gen: {stem}: wrote placeholders to {generated}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
