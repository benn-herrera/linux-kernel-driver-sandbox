import inspect
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from api_gen import __main__ as api_gen_main
from api_gen.emitters import (
    EMITTERS, emit_abi_rs, emit_binding_cpp, emit_binding_lua, emit_binding_rs, emit_c, emit_stub_cpp, emit_stub_rs,
)
from api_gen.tests.support import FIXTURE, TWO_BAD_RETURNS, load, mutate, run_main


def output_paths(*, name: str, project: str) -> dict[str, Path]:
    """Every output token and its path relative to the generated directory, as its
    emitter states it."""
    return {token: emitter.output_path(name=name, project=project) for token, emitter in EMITTERS.items()}


class EmitterShape(unittest.TestCase):
    def test_every_emitter_module_defines_only_the_protocol(self) -> None:
        for token, emitter in EMITTERS.items():
            with self.subTest(token=token):
                defined_here = {
                    name
                    for name, value in vars(emitter).items()
                    if not name.startswith("_")
                    and not inspect.ismodule(value)
                    and getattr(value, "__module__", emitter.__name__) == emitter.__name__
                }
                self.assertEqual(defined_here, {"LABEL", "validate", "output_path", "emit"})


class GenerationCase(unittest.TestCase):
    def generate(self, text: str, *flags: str, file_name: str = "xy_api.adef.toml") -> tuple[int, str, Path, Path]:
        """Run generation of `text`, written as `file_name` under a fresh directory; return
        (exit code, stderr, generated directory, definition path). The directory is removed
        at the end of the test."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        definition = Path(tmp.name) / file_name
        definition.write_text(text, encoding="utf-8")
        generated = Path(tmp.name) / "generated"
        code, _, stderr = run_main([str(definition), "--generated", str(generated), "--project", "xy", *flags])
        return code, stderr, generated, definition


class Generate(GenerationCase):
    def test_writes_every_output_equal_to_its_emitter_and_reports_one_line(self) -> None:
        code, stderr, generated, _ = self.generate(FIXTURE)
        self.assertEqual(code, 0)
        api = load(FIXTURE)
        modules = {
            "h": emit_c, "hpp": emit_binding_cpp, "lua": emit_binding_lua, "stub_cpp": emit_stub_cpp,
            "rs": emit_binding_rs, "abi_rs": emit_abi_rs, "stub_rs": emit_stub_rs,
        }
        for token, relpath in output_paths(name="xy_api", project="xy").items():
            with self.subTest(output=str(relpath)):
                expected = modules[token].emit(api, source_name="xy_api.adef.toml", name="xy_api", library="libxy.so", project="xy")
                self.assertEqual((generated / relpath).read_text(encoding="utf-8"), expected)
                self.assertIn(str(relpath), stderr)
        self.assertEqual(stderr.count("\n"), 1)

    def test_definition_name_must_end_in_the_suffix(self) -> None:
        code, stderr, generated, definition = self.generate(FIXTURE, file_name="xy_api.toml")
        self.assertEqual(code, 2)
        self.assertEqual(stderr, f"api_gen: {definition}: file name must end in .adef.toml\n")
        self.assertFalse(generated.exists())

    def test_name_not_the_file_name_names_every_output(self) -> None:
        code, stderr, generated, _ = self.generate(FIXTURE, file_name="anything.adef.toml")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(sorted(p for p in generated.rglob("*") if p.is_file()),
                         sorted(generated / p for p in output_paths(name="xy_api", project="xy").values()))

    def test_name_is_a_required_identifier(self) -> None:
        for text, message in (
            (mutate(FIXTURE, '_name = "xy_api"\n', ""), "_general._name must be an identifier string"),
            (mutate(FIXTURE, '_name = "xy_api"', '_name = "xy-api"'), "_general._name: 'xy-api' is not an identifier"),
        ):
            with self.subTest(message=message):
                code, stderr, generated, definition = self.generate(text)
                self.assertEqual(code, 2)
                self.assertEqual(stderr, f"api_gen: {definition}: {message}\n")
                self.assertFalse(generated.exists())

    def test_not_implemented_exits_2_saying_so(self) -> None:
        code, stderr, generated, definition = self.generate(mutate(FIXTURE, "max_units = 16", "max_units = 1.5"))
        self.assertEqual(code, 2)
        self.assertEqual(stderr, f"api_gen: {definition}: untyped_const.max_units: f64 constants are not implemented\n")
        self.assertFalse(generated.exists())

    def test_definition_error_exit_2_writes_nothing(self) -> None:
        code, stderr, generated, definition = self.generate("")
        self.assertEqual(code, 2)
        self.assertTrue(stderr.startswith(f"api_gen: {definition}: "))
        self.assertEqual(stderr.count("\n"), 1)
        self.assertFalse(generated.exists())

    def test_every_loader_objection_is_its_own_line_and_nothing_written(self) -> None:
        code, stderr, generated, definition = self.generate(TWO_BAD_RETURNS)
        self.assertEqual(code, 2)
        self.assertEqual(
            stderr.splitlines(),
            [
                f"api_gen: {definition}: function.destroy_port._return: unknown typed_const 'nope'",
                f"api_gen: {definition}: function.spend._return: unknown typed_const 'gone'",
            ],
        )
        self.assertFalse(generated.exists())

    def test_every_emitter_objection_is_reported_in_one_run_and_nothing_written(self) -> None:
        text = mutate(mutate(FIXTURE, "bytes = ", "int = "), 'unit = "u32"', 'result = "u32"')
        code, stderr, generated, definition = self.generate(text)
        self.assertEqual(code, 2)
        # an objection shared by several emitters is one line naming them, in order of first appearance
        self.assertEqual(
            stderr.splitlines(),
            [
                f"api_gen: {definition}: header, wrapper, stub: struct.stats.int: 'int' is a C keyword",
                f"api_gen: {definition}: wrapper, lua, rust: function.open_port.result: 'result' is a name the generated code uses",
            ],
        )
        self.assertFalse(generated.exists())

    def test_library_flag_overrides_the_definition(self) -> None:
        code, _, generated, _ = self.generate(FIXTURE, "--library", "libz.so")
        self.assertEqual(code, 0)
        lua_text = (generated / "binding" / "xy_api.lua").read_text(encoding="utf-8")
        self.assertIn('ffi.load("libz.so")', lua_text)

    def test_project_flag_is_held_to_the_library_rule_and_must_name_a_directory(self) -> None:
        literal = "--project must not contain '\"', '\\' or a control character"
        for project, message in (('x"y', literal), ("x\\y", literal), ("", "--project must name a directory")):
            with self.subTest(project=project):
                code, stderr, generated, definition = self.generate(FIXTURE, "--project", project)
                self.assertEqual(code, 2)
                self.assertEqual(stderr, f"api_gen: {definition}: {message}\n")
                self.assertFalse(generated.exists())

    def test_library_flag_gets_the_definition_library_check_and_must_name_a_file(self) -> None:
        literal = "--library must not contain '\"', '\\' or a control character"
        for library, message in (
            ('lib"z.so', literal), ("lib\\z.so", literal), ("libz.so\n", literal), ("", "--library must name a file"),
        ):
            with self.subTest(library=library):
                code, stderr, generated, definition = self.generate(FIXTURE, "--library", library)
                self.assertEqual(code, 2)
                self.assertEqual(stderr, f"api_gen: {definition}: {message}\n")
                self.assertFalse(generated.exists())

    def test_a_library_flag_objection_is_reported_beside_the_definitions(self) -> None:
        code, stderr, generated, definition = self.generate(TWO_BAD_RETURNS, "--library", "")
        self.assertEqual(code, 2)
        self.assertEqual(
            stderr.splitlines(),
            [
                f"api_gen: {definition}: function.destroy_port._return: unknown typed_const 'nope'",
                f"api_gen: {definition}: function.spend._return: unknown typed_const 'gone'",
                f"api_gen: {definition}: --library must name a file",
            ],
        )
        self.assertFalse(generated.exists())
        code, stderr, generated, definition = self.generate(mutate(FIXTURE, "bytes = ", "int = "), "--library", "")
        self.assertEqual(code, 2)
        self.assertEqual(
            stderr.splitlines(),
            [
                f"api_gen: {definition}: header, wrapper, stub: struct.stats.int: 'int' is a C keyword",
                f"api_gen: {definition}: --library must name a file",
            ],
        )
        self.assertFalse(generated.exists())

    def test_missing_library_exits_2_with_nothing_written(self) -> None:
        code, stderr, generated, _ = self.generate(mutate(FIXTURE, '_library = "libxy.so"\n', ""))
        self.assertEqual(code, 2)
        self.assertIn(": lua, rust: no library named; set _general._library or --library\n", stderr)
        self.assertFalse(generated.exists())

    def test_rust_outputs_need_rustfmt_and_without_it_nothing_is_written(self) -> None:
        with mock.patch.dict(os.environ, {"PATH": ""}):
            for outputs in ("h,stub_rs", "rs,lua"):
                with self.subTest(outputs=outputs):
                    code, stderr, generated, _ = self.generate(FIXTURE, f"--outputs={outputs}")
                    self.assertEqual(code, 2)
                    self.assertEqual(stderr, "api_gen: rustfmt is required for the Rust outputs and was not found on PATH\n")
                    self.assertFalse(generated.exists())

    def test_a_failing_rustfmt_exits_2_with_its_error_and_nothing_is_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rustfmt = Path(tmp) / "rustfmt"
            rustfmt.write_text("#!/bin/sh\necho 'rustfmt: cannot format' >&2\nexit 1\n", encoding="utf-8")
            rustfmt.chmod(0o755)
            with mock.patch.dict(os.environ, {"PATH": tmp}):
                code, stderr, generated, _ = self.generate(FIXTURE)
        self.assertEqual(code, 2)
        self.assertEqual(stderr, "api_gen: rustfmt failed on a Rust output: rustfmt: cannot format\n")
        self.assertFalse(generated.exists())

    def test_every_output_starts_with_a_generated_banner_naming_the_source(self) -> None:
        code, _, generated, _ = self.generate(FIXTURE)
        self.assertEqual(code, 0)
        for relpath in output_paths(name="xy_api", project="xy").values():
            first_line = (generated / relpath).read_text(encoding="utf-8").splitlines()[0]
            with self.subTest(output=str(relpath)):
                self.assertIn("GENERATED", first_line)
                self.assertIn("xy_api.adef.toml", first_line)


class Outputs(GenerationCase):
    def test_tokens_are_the_registry_keys_and_each_names_its_path(self) -> None:
        self.assertEqual(api_gen_main.TOKENS, ("h", "hpp", "lua", "stub_cpp", "rs", "abi_rs", "stub_rs"))
        self.assertEqual(tuple(EMITTERS), api_gen_main.TOKENS)
        self.assertEqual(
            output_paths(name="xy_api", project="xy"),
            {
                "h": Path("include/xy/xy_api.h"),
                "hpp": Path("include/xy/xy_api.hpp"),
                "lua": Path("binding/xy_api.lua"),
                "stub_cpp": Path("stub/xy_api.cpp"),
                "rs": Path("rust/xy_api.rs"),
                "abi_rs": Path("rust/xy_api_abi.rs"),
                "stub_rs": Path("stub/xy_api.rs"),
            },
        )

    def test_every_label(self) -> None:
        self.assertEqual(
            [e.LABEL for e in EMITTERS.values()], ["header", "wrapper", "lua", "stub", "rust", "rust_abi", "rust_stub"]
        )

    def test_writes_only_the_selected_outputs(self) -> None:
        paths = output_paths(name="xy_api", project="xy")
        for flag, selected in (
            ("--outputs=hpp,stub_cpp", {"hpp", "stub_cpp"}),
            ("--outputs=lua", {"lua"}),
            ("--outputs=stub_rs", {"stub_rs"}),
            ("--outputs=abi_rs", {"abi_rs"}),
            ("--outputs=rs", {"rs"}),
            ("--outputs=rs,stub_rs,abi_rs,stub_cpp,h,lua,hpp", set(paths)),
        ):
            with self.subTest(flag=flag):
                code, stderr, generated, _ = self.generate(FIXTURE, flag)
                self.assertEqual(code, 0, stderr)
                written = {token for token, relpath in paths.items() if (generated / relpath).exists()}
                self.assertEqual(written, selected)
                self.assertEqual(sorted(p for p in generated.rglob("*") if p.is_file()),
                                 sorted(generated / paths[t] for t in selected))

    def test_unknown_or_repeated_token_is_a_usage_error_writing_nothing(self) -> None:
        for flag, message in (
            ("--outputs=h,py", "unknown output 'py' (valid: h, hpp, lua, stub_cpp, rs, abi_rs, stub_rs)"),
            ("--outputs=", "unknown output '' (valid: h, hpp, lua, stub_cpp, rs, abi_rs, stub_rs)"),
            ("--outputs=h,lua,h", "output 'h' repeated (valid: h, hpp, lua, stub_cpp, rs, abi_rs, stub_rs)"),
        ):
            with self.subTest(flag=flag):
                code, stderr, generated, _ = self.generate(FIXTURE, flag)
                self.assertEqual(code, 2)
                self.assertIn(message, stderr)
                self.assertFalse(generated.exists())

    def test_only_the_selected_emitters_validate(self) -> None:
        lua_keyword = mutate(FIXTURE, "bytes = ", "end = ")
        code, stderr, *_ = self.generate(lua_keyword, "--outputs=h,hpp")
        self.assertEqual(code, 0, stderr)
        code, stderr, generated, _ = self.generate(lua_keyword, "--outputs=h,lua")
        self.assertEqual(code, 2)
        self.assertIn("lua: struct.stats.end: 'end' is a Lua keyword", stderr)
        self.assertFalse(generated.exists())

    def test_shared_objection_names_only_the_selected_emitters(self) -> None:
        code, stderr, *_ = self.generate(mutate(FIXTURE, "bytes = ", "int = "), "--outputs=h,stub_cpp")
        self.assertEqual(code, 2)
        self.assertEqual(stderr.count("\n"), 1)
        self.assertIn(": header, stub: struct.stats.int: 'int' is a C keyword\n", stderr)

    def test_library_is_required_only_for_lua_and_the_rust_binding(self) -> None:
        no_library = mutate(FIXTURE, '_library = "libxy.so"\n', "")
        code, stderr, *_ = self.generate(no_library, "--outputs=h,hpp,stub_cpp,abi_rs,stub_rs")
        self.assertEqual(code, 0, stderr)
        for flag, labels in (("--outputs=lua", "lua"), ("--outputs=rs", "rust"), ("--outputs=lua,rs", "lua, rust")):
            with self.subTest(flag=flag):
                code, stderr, generated, _ = self.generate(no_library, flag)
                self.assertEqual(code, 2)
                self.assertIn(f": {labels}: no library named; set _general._library or --library\n", stderr)
                self.assertFalse(generated.exists())

    def test_the_rust_binding_needs_a_library_it_can_link(self) -> None:
        for library in ("xy.so", "libxy.so.1", "libxy", "lib.so", "libfoo/bar.so", "lib foo.so"):
            with self.subTest(library=library):
                code, stderr, generated, _ = self.generate(FIXTURE, "--outputs=rs,lua", f"--library={library}")
                self.assertEqual(code, 2)
                self.assertIn(f": rust: library '{library}' is not of the form lib<name>.so, the one a Rust binding links\n", stderr)
                self.assertNotIn("lua", stderr)
                self.assertFalse(generated.exists())
        code, stderr, *_ = self.generate(FIXTURE, "--outputs=lua,stub_rs", "--library=xy.so")
        self.assertEqual(code, 0, stderr)


class Gendeps(unittest.TestCase):
    def definition(self, text: str = FIXTURE) -> str:
        """`text` written as `a.adef.toml`, a file name unlike its `_name`, under a fresh
        directory removed at the end of the test; its path."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "a.adef.toml"
        path.write_text(text, encoding="utf-8")
        return str(path)

    def run_gendeps(self, args: list[str]) -> tuple[int, str]:
        code, stdout, _ = run_main(["gendeps", *args])
        return code, stdout

    def test_fragment_lists_the_output_paths_named_by_the_definition_in_one_grouped_rule(self) -> None:
        definition = self.definition()
        code, out = self.run_gendeps([definition])
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines()[0], "# GENERATED by api_gen gendeps; do not edit.")
        targets = re.search(r"GENERATED := \\\n((?:  .*\\\n)*  .*)\n", out).group(1)
        self.assertEqual(
            [t.strip().rstrip(" \\") for t in targets.splitlines()],
            [f"$(GEN)/{p}" for p in output_paths(name="xy_api", project="$(BASE)").values()],
        )
        self.assertIn(f"$(GENERATED) &: {definition}\n\t", out)
        self.assertIn("--outputs=h,hpp,lua,stub_cpp,rs,abi_rs,stub_rs\n", out)

    def test_outputs_selects_the_targets_and_the_recipe_passes_it_on(self) -> None:
        code, out = self.run_gendeps(["--outputs=lua,h", self.definition()])
        self.assertEqual(code, 0)
        paths = output_paths(name="xy_api", project="$(BASE)")
        self.assertIn(f"GENERATED := \\\n  $(GEN)/{paths['h']} \\\n  $(GEN)/{paths['lua']}\n\n", out)
        self.assertIn(" --outputs=h,lua\n", out)

    def test_a_definition_the_loader_refuses_exits_2_with_its_objections_and_nothing_on_stdout(self) -> None:
        definition = self.definition(TWO_BAD_RETURNS)
        code, stdout, stderr = run_main(["gendeps", definition])
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(
            stderr.splitlines(),
            [
                f"api_gen: {definition}: function.destroy_port._return: unknown typed_const 'nope'",
                f"api_gen: {definition}: function.spend._return: unknown typed_const 'gone'",
            ],
        )

    def test_unknown_output_is_a_usage_error(self) -> None:
        code, stdout, stderr = run_main(["gendeps", "--outputs=py", "a.adef.toml"])
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("unknown output 'py' (valid: h, hpp, lua, stub_cpp, rs, abi_rs, stub_rs)", stderr)

    def test_no_definitions_exits_2_with_nothing_on_stdout(self) -> None:
        code, stdout, stderr = run_main(["gendeps"])
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "api_gen: gendeps takes exactly one definition\n")

    def test_two_definitions_exits_2_with_nothing_on_stdout(self) -> None:
        code, stdout, stderr = run_main(["gendeps", "a.adef.toml", "b.adef.toml"])
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "api_gen: gendeps takes exactly one definition\n")

    def test_bad_name_exits_2_with_nothing_on_stdout(self) -> None:
        code, out = self.run_gendeps(["not_a_definition.txt"])
        self.assertEqual(code, 2)
        self.assertEqual(out, "")


if __name__ == "__main__":
    unittest.main()
