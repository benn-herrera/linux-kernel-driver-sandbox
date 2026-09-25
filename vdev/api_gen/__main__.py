"""CLI: validate an .adef.toml definition and write its C header and
LuaJIT base module into the generated directory.
"""

import argparse
import sys
from pathlib import Path

from api_gen import emit_c, emit_lua, model

SUFFIX = ".adef.toml"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="generate userspace API artifacts from an API definition"
    )
    parser.add_argument("definition", type=Path, help="path to a *.adef.toml file")
    parser.add_argument("--generated", type=Path, required=True, help="output directory")
    parser.add_argument(
        "--exercise", required=True, help="exercise directory name, for the include subdirectory"
    )
    parser.add_argument(
        "--library",
        help="shared library file name the Lua module loads (default: general.library)",
    )
    args = parser.parse_args()

    definition: Path = args.definition
    if not definition.name.endswith(SUFFIX):
        print(f"api_gen: {definition}: file name must end in {SUFFIX}", file=sys.stderr)
        return 2

    stem = definition.name[: -len(SUFFIX)]
    source = definition.name
    try:
        api = model.load(definition)
        library = args.library or api.library
        if library is None:
            raise model.DefinitionError(
                "no library for the Lua module: pass --library or set general.library"
            )
        outputs = {
            Path("include") / args.exercise / f"{stem}.h": emit_c.header(api, source_name=source),
            Path("binding") / f"{stem}.lua": emit_lua.module(api, source_name=source, library=library),
        }
    except model.DefinitionError as e:
        print(f"api_gen: {definition}: {e}", file=sys.stderr)
        return 2

    generated: Path = args.generated
    for relpath, text in outputs.items():
        out_path = generated / relpath
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")

    paths = " ".join(str(relpath) for relpath in outputs)
    print(f"api_gen: {stem}: wrote {paths} under {generated}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
