import re
import tempfile
import unittest
from pathlib import Path

from api_gen import __main__ as api_gen_main
from api_gen import emit_c, emit_cpp_stub, emit_cpp_wrapper, emit_lua
from api_gen.tests.support import FIXTURE, load, mutate, run_main


class Generate(unittest.TestCase):
    def test_writes_every_output_equal_to_its_emitter_and_reports_one_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            definition = Path(tmp) / "xy_api.adef.toml"
            definition.write_text(FIXTURE, encoding="utf-8")
            generated = Path(tmp) / "generated"
            code, _, stderr = run_main([str(definition), "--generated", str(generated), "--exercise", "tiny_compute"])
            self.assertEqual(code, 0)
            api, source = load(FIXTURE), "xy_api.adef.toml"
            expected = (
                emit_c.header(api, source_name=source),
                emit_cpp_wrapper.wrapper(api, source_name=source, stem="xy_api"),
                emit_lua.module(api, source_name=source, library="libxy.so"),
                emit_cpp_stub.stub(api, source_name=source, stem="xy_api"),
            )
            relpaths = api_gen_main.output_paths(stem="xy_api", exercise="tiny_compute")
            for relpath, text in zip(relpaths, expected, strict=True):
                with self.subTest(output=str(relpath)):
                    self.assertEqual((generated / relpath).read_text(encoding="utf-8"), text)
                    self.assertIn(str(relpath), stderr)
            self.assertEqual(stderr.count("\n"), 1)

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
            # one objection shared by three emitters is one line naming them; a second emitter's own objection follows it
            self.assertEqual(
                stderr.splitlines(),
                [
                    f"api_gen: {definition}: header, wrapper, stub: struct.stats.int: 'int' is a C keyword",
                    f"api_gen: {definition}: lua: function.open_port.result: 'result' is a name the generated code binds",
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
            for relpath in api_gen_main.output_paths(stem="xy_api", exercise="tiny_compute"):
                first_line = (generated / relpath).read_text(encoding="utf-8").splitlines()[0]
                with self.subTest(output=str(relpath)):
                    self.assertIn("GENERATED", first_line)
                    self.assertIn("xy_api.adef.toml", first_line)


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
            [f"$(GEN)/{p}" for p in api_gen_main.output_paths(stem="a", exercise="$(BASE)")],
        )
        self.assertIn("$(GENERATED) &: a.adef.toml\n\t", out)

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
