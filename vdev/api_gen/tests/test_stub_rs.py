import unittest
from pathlib import Path

from api_gen.emitters import emit_stub_rs
from api_gen.tests.support import FIXTURE, KITCHEN_SINK, assert_matches_expected, load, mutate

EXPECTED = Path(__file__).resolve().parent / "expected_stub_xy.rs"


class Stub(unittest.TestCase):
    def test_byte_identical_to_expected(self) -> None:
        assert_matches_expected(self, EXPECTED, emit_stub_rs.emit(
            load(KITCHEN_SINK), source_name="xy_api.adef.toml", name="xy_api", library=None, project="xy",
        ))


class Validate(unittest.TestCase):
    RULE = "is not snake_case (an uppercase letter or '__'), which rustc requires of it"

    def test_rust_keyword_as_name(self) -> None:
        self.assertEqual(
            emit_stub_rs.validate(load(mutate(FIXTURE, "unit = ", "match = "))),
            ["rust_stub: function.open_port.match: 'match' is a Rust keyword"],
        )

    def test_function_or_parameter_name_rustc_calls_not_snake_case(self) -> None:
        for needle, replacement, where, name in (
            ("[function.send]", "[function.Send]", "function.Send", "Send"),
            ("[function.send]", "[function.se__nd]", "function.se__nd", "se__nd"),
            ("unit = ", "Unit = ", "function.open_port.Unit", "Unit"),
            ("unit = ", "u__nit = ", "function.open_port.u__nit", "u__nit"),
        ):
            with self.subTest(name=name):
                self.assertEqual(
                    emit_stub_rs.validate(load(mutate(FIXTURE, needle, replacement))),
                    [f"rust_stub: {where}: '{name}' {self.RULE}"],
                )

    def test_an_import_shadowing_a_prelude_name_or_rendering_a_keyword(self) -> None:
        # the stub imports a struct parameter's re-export and each return enum
        for text, message in (
            (mutate(FIXTURE, "[struct.stats]", "[struct.ok]").replace('"stats"', '"ok"'),
             "module scope: Ok would be defined more than once, by the Rust prelude and struct.ok"),
            (mutate(FIXTURE, "[struct.stats]", "[struct.option]").replace('"stats"', '"option"'),
             "module scope: Option would be defined more than once, by the Rust prelude and struct.option"),
            (mutate(FIXTURE, "[typed_const.status]", "[typed_const.self_]").replace('"status"', '"self_"'),
             "typed_const.self_: 'self_' renders as 'Self', a Rust keyword"),
        ):
            with self.subTest(message=message):
                self.assertEqual(emit_stub_rs.validate(load(text)), [f"rust_stub: {message}"])

    def test_a_type_the_stub_does_not_import_is_not_refused(self) -> None:
        self.assertEqual(emit_stub_rs.validate(load(FIXTURE + '\n[struct.ok]\nv = "u32"\n')), [])

    def test_names_the_stub_does_not_render_are_not_refused(self) -> None:
        # the namespace, a trailing '_' and the count it brings, a conversion, a struct field
        for needle, replacement in (
            ('_namespace = "xy"', '_namespace = "Xy"'),
            ("buf = ", "buf_ = "),
            ('_to_string = "to_string"', '_to_string = "toString"'),
            ("bytes = ", "Bytes = "),
        ):
            with self.subTest(replacement=replacement):
                self.assertEqual(emit_stub_rs.validate(load(mutate(FIXTURE, needle, replacement))), [])


if __name__ == "__main__":
    unittest.main()
