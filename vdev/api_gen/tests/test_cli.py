import inspect
import re
import tempfile
import unittest
from pathlib import Path

from api_gen import __main__ as api_gen_main
from api_gen.emitters import EMITTERS, emit_binding_cpp, emit_binding_lua, emit_c, emit_stub_cpp
from api_gen.emitters.emitter import Emitter
from api_gen.tests.support import FIXTURE, load, mutate, run_main


def output_paths(*, stem: str, exercise: str) -> dict[str, Path]:
    """Every output token and its path relative to the generated directory, as its
    emitter states it."""
    return {token: emitter.output_path(stem=stem, exercise=exercise) for token, emitter in EMITTERS.items()}


class EmitterShape(unittest.TestCase):
    def test_every_emitter_matches_the_protocol(self) -> None:
        def unbound(method: object) -> inspect.Signature:
            signature = inspect.signature(method)
            return signature.replace(parameters=list(signature.parameters.values())[1:])

        for token, emitter in EMITTERS.items():
            with self.subTest(token=token):
                self.assertIsInstance(emitter.LABEL, str)
                for name in ("validate", "output_path", "emit"):
                    self.assertEqual(inspect.signature(getattr(emitter, name)), unbound(getattr(Emitter, name)), name)

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


class Generate(unittest.TestCase):
    def test_writes_every_output_equal_to_its_emitter_and_reports_one_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            definition = Path(tmp) / "xy_api.adef.toml"
            definition.write_text(FIXTURE, encoding="utf-8")
            generated = Path(tmp) / "generated"
            code, _, stderr = run_main([str(definition), "--generated", str(generated), "--exercise", "tiny_compute"])
            self.assertEqual(code, 0)
            api = load(FIXTURE)
            modules = {"h": emit_c, "hpp": emit_binding_cpp, "lua": emit_binding_lua, "stub_cpp": emit_stub_cpp}
            for token, relpath in output_paths(stem="xy_api", exercise="tiny_compute").items():
                with self.subTest(output=str(relpath)):
                    expected = modules[token].emit(api, source_name="xy_api.adef.toml", stem="xy_api", library="libxy.so")
                    self.assertEqual((generated / relpath).read_text(encoding="utf-8"), expected)
                    self.assertIn(str(relpath), stderr)
            self.assertEqual(stderr.count("\n"), 1)

    def test_definition_name_must_end_in_the_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            definition = Path(tmp) / "xy_api.toml"
            definition.write_text(FIXTURE, encoding="utf-8")
            generated = Path(tmp) / "generated"
            code, _, stderr = run_main([str(definition), "--generated", str(generated), "--exercise", "xy"])
            self.assertEqual(code, 2)
            self.assertEqual(stderr, f"api_gen: {definition}: file name must end in .adef.toml\n")
            self.assertFalse(generated.exists())

    def test_not_implemented_exits_2_saying_so(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            definition = Path(tmp) / "xy_api.adef.toml"
            definition.write_text(mutate(FIXTURE, "max_units = 16", "max_units = 1.5"), encoding="utf-8")
            generated = Path(tmp) / "generated"
            code, _, stderr = run_main([str(definition), "--generated", str(generated), "--exercise", "xy"])
            self.assertEqual(code, 2)
            self.assertEqual(stderr, f"api_gen: {definition}: untyped_const.max_units: f64 constants are not implemented\n")
            self.assertFalse(generated.exists())

    def test_definition_error_exit_2_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            definition = Path(tmp) / "xy_api.adef.toml"
            definition.write_text("", encoding="utf-8")
            generated = Path(tmp) / "generated"
            code, _, stderr = run_main([str(definition), "--generated", str(generated), "--exercise", "tiny_compute"])
            self.assertEqual(code, 2)
            self.assertTrue(stderr.startswith(f"api_gen: {definition}: "))
            self.assertEqual(stderr.count("\n"), 1)
            self.assertFalse(generated.exists())

    def test_every_emitter_objection_is_reported_in_one_run_and_nothing_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            definition = Path(tmp) / "xy_api.adef.toml"
            text = mutate(mutate(FIXTURE, "bytes = ", "int = "), 'unit = "u32"', 'result = "u32"')
            definition.write_text(text, encoding="utf-8")
            generated = Path(tmp) / "generated"
            code, _, stderr = run_main([str(definition), "--generated", str(generated), "--exercise", "tiny_compute"])
            self.assertEqual(code, 2)
            # an objection shared by several emitters is one line naming them, in order of first appearance
            self.assertEqual(
                stderr.splitlines(),
                [
                    f"api_gen: {definition}: header, wrapper, stub: struct.stats.int: 'int' is a C keyword",
                    f"api_gen: {definition}: wrapper, lua: function.open_port.result: 'result' is a name the generated code uses",
                ],
            )
            self.assertFalse(generated.exists())

    def test_library_flag_overrides_the_definition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            definition = Path(tmp) / "xy_api.adef.toml"
            definition.write_text(FIXTURE, encoding="utf-8")
            generated = Path(tmp) / "generated"
            code, _, _ = run_main([
                str(definition), "--generated", str(generated), "--exercise", "tiny_compute", "--library", "libz.so",
            ])
            self.assertEqual(code, 0)
            lua_text = (generated / "binding" / "xy_api.lua").read_text(encoding="utf-8")
            self.assertIn('ffi.load("libz.so")', lua_text)

    def test_library_flag_gets_the_definition_library_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            definition = Path(tmp) / "xy_api.adef.toml"
            definition.write_text(FIXTURE, encoding="utf-8")
            generated = Path(tmp) / "generated"
            for library in ('lib"z.so', "lib\\z.so", "libz.so\n"):
                with self.subTest(library=library):
                    code, _, stderr = run_main([
                        str(definition), "--generated", str(generated), "--exercise", "tiny_compute", "--library", library,
                    ])
                    self.assertEqual(code, 2)
                    self.assertEqual(
                        stderr,
                        f"api_gen: {definition}: --library must not contain '\"', '\\' or a control character\n",
                    )
                    self.assertFalse(generated.exists())

    def test_empty_library_flag_is_a_usage_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            definition = Path(tmp) / "xy_api.adef.toml"
            definition.write_text(FIXTURE, encoding="utf-8")
            generated = Path(tmp) / "generated"
            code, _, stderr = run_main([
                str(definition), "--generated", str(generated), "--exercise", "tiny_compute", "--library", "",
            ])
            self.assertEqual(code, 2)
            self.assertIn("argument --library: must name a file", stderr)
            self.assertFalse(generated.exists())

    def test_missing_library_exits_2_with_nothing_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            definition = Path(tmp) / "xy_api.adef.toml"
            definition.write_text(mutate(FIXTURE, '_library = "libxy.so"\n', ""), encoding="utf-8")
            generated = Path(tmp) / "generated"
            code, _, stderr = run_main([str(definition), "--generated", str(generated), "--exercise", "tiny_compute"])
            self.assertEqual(code, 2)
            self.assertIn("pass --library", stderr)
            self.assertFalse(generated.exists())

    def test_every_output_starts_with_a_generated_banner_naming_the_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            definition = Path(tmp) / "xy_api.adef.toml"
            definition.write_text(FIXTURE, encoding="utf-8")
            generated = Path(tmp) / "generated"
            code, _, _ = run_main([str(definition), "--generated", str(generated), "--exercise", "tiny_compute"])
            self.assertEqual(code, 0)
            for relpath in output_paths(stem="xy_api", exercise="tiny_compute").values():
                first_line = (generated / relpath).read_text(encoding="utf-8").splitlines()[0]
                with self.subTest(output=str(relpath)):
                    self.assertIn("GENERATED", first_line)
                    self.assertIn("xy_api.adef.toml", first_line)


class Outputs(unittest.TestCase):
    def generate(self, text: str, *flags: str) -> tuple[int, str, Path]:
        """Run generation of `text` under a fresh directory; return (exit code, stderr,
        generated directory). The directory is removed at the end of the test."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        definition = Path(tmp.name) / "xy_api.adef.toml"
        definition.write_text(text, encoding="utf-8")
        generated = Path(tmp.name) / "generated"
        code, _, stderr = run_main([str(definition), "--generated", str(generated), "--exercise", "xy", *flags])
        return code, stderr, generated

    def test_tokens_are_the_registry_keys_and_each_names_its_path(self) -> None:
        self.assertEqual(api_gen_main.TOKENS, ("h", "hpp", "lua", "stub_cpp"))
        self.assertEqual(tuple(EMITTERS), api_gen_main.TOKENS)
        self.assertEqual(
            output_paths(stem="xy_api", exercise="xy"),
            {
                "h": Path("include/xy/xy_api.h"),
                "hpp": Path("include/xy/xy_api.hpp"),
                "lua": Path("binding/xy_api.lua"),
                "stub_cpp": Path("stub/xy_api.cpp"),
            },
        )

    def test_writes_only_the_selected_outputs(self) -> None:
        paths = output_paths(stem="xy_api", exercise="xy")
        for flag, selected in (
            ("--outputs=hpp,stub_cpp", {"hpp", "stub_cpp"}),
            ("--outputs=lua", {"lua"}),
            ("--outputs=stub_cpp,h,lua,hpp", set(paths)),
        ):
            with self.subTest(flag=flag):
                code, stderr, generated = self.generate(FIXTURE, flag)
                self.assertEqual(code, 0, stderr)
                written = {token for token, relpath in paths.items() if (generated / relpath).exists()}
                self.assertEqual(written, selected)
                self.assertEqual(sorted(p for p in generated.rglob("*") if p.is_file()),
                                 sorted(generated / paths[t] for t in selected))

    def test_unknown_or_repeated_token_is_a_usage_error_writing_nothing(self) -> None:
        for flag, message in (
            ("--outputs=h,rs", "unknown output 'rs' (valid: h, hpp, lua, stub_cpp)"),
            ("--outputs=", "unknown output '' (valid: h, hpp, lua, stub_cpp)"),
            ("--outputs=h,lua,h", "output 'h' repeated (valid: h, hpp, lua, stub_cpp)"),
        ):
            with self.subTest(flag=flag):
                code, stderr, generated = self.generate(FIXTURE, flag)
                self.assertEqual(code, 2)
                self.assertIn(message, stderr)
                self.assertFalse(generated.exists())

    def test_only_the_selected_emitters_validate(self) -> None:
        lua_keyword = mutate(FIXTURE, "bytes = ", "end = ")
        code, stderr, _ = self.generate(lua_keyword, "--outputs=h,hpp")
        self.assertEqual(code, 0, stderr)
        code, stderr, generated = self.generate(lua_keyword, "--outputs=h,lua")
        self.assertEqual(code, 2)
        self.assertIn("lua: struct.stats.end: 'end' is a Lua keyword", stderr)
        self.assertFalse(generated.exists())

    def test_shared_objection_names_only_the_selected_emitters(self) -> None:
        code, stderr, _ = self.generate(mutate(FIXTURE, "bytes = ", "int = "), "--outputs=h,stub_cpp")
        self.assertEqual(code, 2)
        self.assertEqual(stderr.count("\n"), 1)
        self.assertIn(": header, stub: struct.stats.int: 'int' is a C keyword\n", stderr)

    def test_library_is_required_only_for_lua(self) -> None:
        no_library = mutate(FIXTURE, '_library = "libxy.so"\n', "")
        code, stderr, _ = self.generate(no_library, "--outputs=h,hpp,stub_cpp")
        self.assertEqual(code, 0, stderr)


class Gendeps(unittest.TestCase):
    def run_gendeps(self, args: list[str]) -> tuple[int, str]:
        code, stdout, _ = run_main(["gendeps", *args])
        return code, stdout

    def test_fragment_lists_the_output_paths_in_one_grouped_rule(self) -> None:
        code, out = self.run_gendeps(["a.adef.toml"])
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines()[0], "# GENERATED by api_gen gendeps; do not edit.")
        targets = re.search(r"GENERATED := \\\n((?:  .*\\\n)*  .*)\n", out).group(1)
        self.assertEqual(
            [t.strip().rstrip(" \\") for t in targets.splitlines()],
            [f"$(GEN)/{p}" for p in output_paths(stem="a", exercise="$(BASE)").values()],
        )
        self.assertIn("$(GENERATED) &: a.adef.toml\n\t", out)
        self.assertIn("--outputs=h,hpp,lua,stub_cpp\n", out)

    def test_outputs_selects_the_targets_and_the_recipe_passes_it_on(self) -> None:
        code, out = self.run_gendeps(["--outputs=lua,h", "a.adef.toml"])
        self.assertEqual(code, 0)
        paths = output_paths(stem="a", exercise="$(BASE)")
        self.assertIn(f"GENERATED := \\\n  $(GEN)/{paths['h']} \\\n  $(GEN)/{paths['lua']}\n\n", out)
        self.assertIn(" --outputs=h,lua\n", out)

    def test_unknown_output_is_a_usage_error(self) -> None:
        code, stdout, stderr = run_main(["gendeps", "--outputs=rs", "a.adef.toml"])
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("unknown output 'rs' (valid: h, hpp, lua, stub_cpp)", stderr)

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
