"""Compiled and executed checks of the generated outputs. They need clang, clang++,
luajit and make, the build container's pinned toolchain; `just api-gen-test-vdev`
runs them there."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from api_gen.tests.support import C_BASE_TYPES, EXERCISES, KITCHEN_SINK, expected_constants, load, mutate, run_main

TESTS = Path(__file__).resolve().parent
TOOLS = ("clang", "clang++", "luajit", "make")
CFLAGS = ["-std=c17", "-fsyntax-only", "-Wall", "-Wextra", "-Werror"]
CXX_SYNTAX = ["clang++", "--std=c++20", "-fsyntax-only", "-Wall", "-Wextra", "-Werror"]

_build: tempfile.TemporaryDirectory | None = None
TMP = Path()
INC = Path()


def run(args: list[str | Path], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run([str(a) for a in args], capture_output=True, text=True, **kwargs)


def build_or_fail(args: list[str | Path]) -> None:
    result = run(args)
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(map(str, args))} failed:\n{result.stderr}")


def generate(definition: Path, generated: Path, exercise: str) -> None:
    code, _, stderr = run_main([str(definition), "--generated", str(generated), "--exercise", exercise])
    if code != 0:
        raise RuntimeError(f"api_gen failed on {definition}:\n{stderr}")


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def values_tu() -> str:
    """Asserts every constant's value, and every bit and plain constant's type, the one
    its group's `_base_type` names."""
    api = load(KITCHEN_SINK)
    lines = ['#include "xy_api.h"']
    for key, value in expected_constants(api).items():
        name = f"XY_{key}"
        if isinstance(value, str):
            lines.append(f'_Static_assert(sizeof({name}) == {len(value) + 1}, "{name}");')
        else:
            lines.append(f'_Static_assert({name} == ({value}), "{name}");')
    for group in (*api.bit_const_groups, *api.const_groups):
        for c in group.entries:
            name = f"XY_{c.name.upper()}"
            lines.append(f'_Static_assert(_Generic({name}, {C_BASE_TYPES[group.base_type]}: 1, default: 0), "{name} type");')
    lines.append("int main(void) { return 0; }")
    return "\n".join(lines) + "\n"


def require_tools() -> None:
    missing = [tool for tool in TOOLS if shutil.which(tool) is None]
    if missing:
        raise RuntimeError(f"the build container lacks {', '.join(missing)} on PATH")


def setUpModule() -> None:
    global _build, TMP, INC
    require_tools()
    _build = tempfile.TemporaryDirectory()
    TMP = Path(_build.name)
    INC = TMP / "generated" / "include" / "xy"

    generate(write(TMP / "xy_api.adef.toml", KITCHEN_SINK), TMP / "generated", "xy")
    write(TMP / "xy" / "driver" / "xy_ioctl.h", "#define XYD_FEAT_A 1\n")
    write(TMP / "bad" / "xy" / "driver" / "xy_ioctl.h", "#define XYD_FEAT_A 2\n")
    write(TMP / "values.c", values_tu())
    # the fake is the implementation: XY_IMPL pulls in the driver header, hence -I<tmp>
    build_or_fail(
        ["clang++", "-std=c++20", "-shared", "-fPIC", "-Wall", "-Wextra", "-Werror",
         f"-I{INC}", f"-I{TMP}", "-o", TMP / "libxy.so", TESTS / "fake_xy.cpp"]
    )
    build_or_fail(
        ["clang++", "-std=c++20", "-Wall", "-Wextra", "-Wshadow", "-Werror", f"-I{INC}",
         "-o", TMP / "consumer", TESTS / "consumer_xy.cpp", f"-L{TMP}", "-lxy", f"-Wl,-rpath,{TMP}"]
    )


def tearDownModule() -> None:
    if _build is not None:
        _build.cleanup()


class HeaderC(unittest.TestCase):
    def compile_values(self, *extra: str) -> subprocess.CompletedProcess:
        return run(["clang", "-x", "c", *CFLAGS, f"-I{INC}", *extra, TMP / "values.c"])

    def test_consumer_translation_unit_compiles(self) -> None:
        result = self.compile_values()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_implementation_translation_unit_compiles_with_pins(self) -> None:
        result = self.compile_values("-DXY_IMPL", f"-I{TMP}")
        self.assertEqual(result.returncode, 0, result.stderr)


class BitThirtyOne(unittest.TestCase):
    """A u32 group's bit 31: the header and the wrapper carry it, the Lua module refuses it."""

    DEFINITION = mutate(
        KITCHEN_SINK, '_base_type = "u32"\nfeat_one = 0', '_base_type = "u32"\n_to_string = "wide_to_string"\nfeat_one = 31'
    )

    def test_header_and_wrapper_carry_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            definition = write(root / "xy_api.adef.toml", self.DEFINITION)
            code, _, stderr = run_main(
                [str(definition), "--generated", str(root / "generated"), "--exercise", "xy", "--outputs=h,hpp"]
            )
            self.assertEqual(code, 0, stderr)
            tu = write(root / "wide.cpp", (
                '#include "xy_api.hpp"\n'
                "static_assert(XY_FEAT_ONE == 0x80000000u);\n"
                "static_assert(xy::FEAT_ALL == 0x80000008u);\n"
                'int main() { return xy::wide_to_string(xy::FEAT_ALL) == "FEAT_ONE|0x8" ? 0 : 1; }\n'
            ))
            build_or_fail(["clang++", "-std=c++20", "-Wall", "-Wextra", "-Werror",
                           f"-I{root / 'generated' / 'include' / 'xy'}", "-o", root / "wide", tu])
            self.assertEqual(run([root / "wide"]).returncode, 0)

    def test_lua_refuses_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            definition = write(Path(tmp) / "xy_api.adef.toml", self.DEFINITION)
            code, _, stderr = run_main([str(definition), "--generated", str(Path(tmp) / "generated"), "--exercise", "xy"])
            self.assertEqual(code, 2)
            self.assertIn(": lua: untyped_bit_const.feat_one: value 0x80000000 exceeds 0x7fffffff;", stderr)


class Stub(unittest.TestCase):
    def compile_stub(self, pins: Path) -> subprocess.CompletedProcess:
        return run([*CXX_SYNTAX, f"-I{INC}", f"-I{pins}", TMP / "generated" / "stub" / "xy_api.cpp"])

    def test_compiles_against_its_header_with_pins_active(self) -> None:
        result = self.compile_stub(TMP)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_pin_mismatch_fails_the_implementation_build(self) -> None:
        result = self.compile_stub(TMP / "bad")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("XY_FEAT_A must match XYD_FEAT_A", result.stderr)


class Wrapper(unittest.TestCase):
    def test_consumer_builds_and_runs(self) -> None:
        code = run([TMP / "consumer"]).returncode
        self.assertEqual(code, 0, f"consumer exit {code}")

    def test_discarded_result_is_a_compile_error(self) -> None:
        result = run(["clang++", "--std=c++20", "-fsyntax-only", "-Werror=unused-result", f"-I{INC}",
                      TESTS / "nodiscard_xy.cpp"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unused-result", result.stderr)


class Lua(unittest.TestCase):
    def test_module_byte_compiles(self) -> None:
        result = run(["luajit", "-bl", TMP / "generated" / "binding" / "xy_api.lua"])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_module_runs_against_the_fake_library(self) -> None:
        module = TMP / "generated" / "binding" / "xy_api.lua"
        result = run(["luajit", TESTS / "check_xy.lua", module], env={**os.environ, "LD_LIBRARY_PATH": str(TMP)})
        self.assertEqual(result.returncode, 0, result.stderr)
        found = {}
        for line in result.stdout.splitlines():
            name, value = line.split("=", 1)
            found[name] = int(value) if value.lstrip("-").isdigit() else value
        self.assertEqual(found, expected_constants(load(KITCHEN_SINK)))

    def test_finalizer_runs_after_module_is_unreachable(self) -> None:
        module = TMP / "generated" / "binding" / "xy_api.lua"
        env = {**os.environ, "LD_LIBRARY_PATH": str(TMP)}

        result = run(["luajit", TESTS / "gc_xy.lua", module], env=env)
        self.assertEqual(result.returncode, 0, result.stderr)

        error_script = write(
            TMP / "gc_error_xy.lua",
            'local M = dofile(arg[1])\nlocal p = M.Port.new(1)\nerror("x")\n',
        )
        result = run(["luajit", error_script, module], env=env)
        self.assertEqual(result.returncode, 1, result.stderr)


class Gendeps(unittest.TestCase):
    def make_n(self, *flags: str) -> str:
        """`make -n` over the gendeps fragment for `flags`, printing each GENERATED target
        and then the recipe make would run; returns make's stdout."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "xy_api.adef.toml").touch()
            code, fragment, stderr = run_main(["gendeps", *flags, "xy_api.adef.toml"])
            self.assertEqual(code, 0, stderr)
            write(root / "frag.mk", fragment)
            write(
                root / "Makefile",
                "GEN := OUTDIR\nBASE := xy\nAPI_GEN := /pkg\ninclude frag.mk\n"
                "all: $(GENERATED)\n\t@echo $(foreach t,$(GENERATED),target=$(t))\n",
            )
            result = run(["make", "-n", "-f", "Makefile", "all"], cwd=root)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout

    def test_fragment_drives_gnu_make(self) -> None:
        out = self.make_n()
        self.assertIn("PYTHONPATH=/pkg", out)
        self.assertIn(
            "python3 -m api_gen xy_api.adef.toml --generated OUTDIR --exercise xy --outputs=h,hpp,lua,stub_cpp", out
        )

    def test_subset_fragment_makes_only_its_outputs(self) -> None:
        out = self.make_n("--outputs=hpp,lua")
        self.assertIn("python3 -m api_gen xy_api.adef.toml --generated OUTDIR --exercise xy --outputs=hpp,lua\n", out)
        self.assertIn("echo target=OUTDIR/include/xy/xy_api.hpp target=OUTDIR/binding/xy_api.lua\n", out)

    def test_gen_mk_outputs_come_from_the_makefile_or_command_line_never_the_environment(self) -> None:
        for makefile_line, command_line, expected in (
            ("", [], "h,hpp,lua,stub_cpp"),
            ("OUTPUTS := hpp\n", [], "hpp"),
            ("OUTPUTS := hpp\n", ["OUTPUTS=lua"], "lua"),
        ):
            with self.subTest(makefile=makefile_line, command_line=command_line), tempfile.TemporaryDirectory() as tmp:
                api_def = Path(tmp) / "xy" / "userspace" / "api_def"
                write(api_def / "xy_api.adef.toml", KITCHEN_SINK)
                write(api_def / "Makefile", f"{makefile_line}include {EXERCISES / 'gen.mk'}\n")
                out = Path(tmp) / "out"
                # make remakes the included adef.mk even under -n
                result = run(
                    ["make", "-n", f"OUT={out}", f"API_GEN={EXERCISES.parent / 'vdev'}", *command_line],
                    cwd=api_def, env={**os.environ, "OUTPUTS": "stub_cpp"},
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f" --outputs={expected}\n", (out / "generated" / "adef.mk").read_text(encoding="utf-8"))


class RealDefinition(unittest.TestCase):
    def test_every_exercise_definition_round_trips(self) -> None:
        api_defs = sorted(EXERCISES.glob("*/userspace/api_def"))
        self.assertTrue(api_defs, f"no */userspace/api_def under {EXERCISES}")
        for api_def in api_defs:
            exercise = api_def.parents[1].name
            with self.subTest(exercise=exercise), tempfile.TemporaryDirectory() as tmp:
                definitions = list(api_def.glob("*.adef.toml"))
                self.assertEqual(len(definitions), 1, definitions)
                definition = definitions[0]
                stem = definition.name.removesuffix(".adef.toml")
                generated = Path(tmp) / "generated"
                code, _, stderr = run_main([str(definition), "--generated", str(generated), "--exercise", exercise])
                self.assertEqual(code, 0, stderr)
                include = generated / "include" / exercise

                stub = run([*CXX_SYNTAX, f"-I{include}", f"-I{EXERCISES}", generated / "stub" / f"{stem}.cpp"])
                self.assertEqual(stub.returncode, 0, stub.stderr)
                tu = write(Path(tmp) / "tu.cpp", f'#include "{stem}.hpp"\nint main() {{ return 0; }}\n')
                wrapper = run([*CXX_SYNTAX, f"-I{include}", tu])
                self.assertEqual(wrapper.returncode, 0, wrapper.stderr)
                lua = run(["luajit", "-bl", generated / "binding" / f"{stem}.lua"])
                self.assertEqual(lua.returncode, 0, lua.stderr)


if __name__ == "__main__":
    unittest.main()
