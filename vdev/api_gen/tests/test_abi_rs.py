import re
import unittest
from pathlib import Path

from api_gen.emitters import emit_abi_rs, emit_binding_rs
from api_gen.tests.support import (
    DOCUMENTED_FUNCTION_GROUPS, FIXTURE, KITCHEN_SINK, NO_WRAPPED_API, UNSPELLED_PRELUDE_STRUCTS,
    assert_matches_expected, load, mutate,
)

EXPECTED = Path(__file__).resolve().parent / "expected_abi_xy.rs"
EXPECTED_BINDING = Path(__file__).resolve().parent / "expected_binding_xy.rs"
SAFETY = (
    "/// # Safety\n///\n"
    "/// Every pointer argument must be null or valid for the call as the C header declares it, no buffer may "
    "overlap another argument of the same call, and no other thread may read or write a buffer argument during "
    "the call. A panic in the implementation aborts the process.\n"
    '#[unsafe(no_mangle)]\npub unsafe extern "C" fn '
)


def relay(text: str = FIXTURE) -> str:
    return emit_abi_rs.emit(load(text), source_name="xy_api.adef.toml", name="xy_api", library=None, project="xy")


class Relay(unittest.TestCase):
    def test_byte_identical_to_expected(self) -> None:
        assert_matches_expected(self, EXPECTED, relay(KITCHEN_SINK))

    def test_enums_and_reexports_are_the_bindings_byte_for_byte(self) -> None:
        text, binding = relay(KITCHEN_SINK), EXPECTED_BINDING.read_text(encoding="utf-8")
        shared = re.search(r"^/// call outcome\n#\[repr\(i32\)\].*?pub use ffi::xy_wrap as Wrap;\n", text, re.M | re.S).group(0)
        self.assertIn(shared, binding)

    def test_a_blank_doc_line_follows_the_docstring_only_where_there_is_one(self) -> None:
        text = relay(KITCHEN_SINK)
        self.assertIn("/// release the port\n///\n/// # Safety\n", text)
        self.assertIn("/// buf: bytes to send\n///\n/// # Safety\n", text)
        self.assertIn("}\n\n" + SAFETY + "xy_spend(", text)
        with_param_doc = mutate(FIXTURE, "[function.send]\n", '[function.send]\n_docstring = "- sends"\n')
        self.assertIn("/// - sends\n///\n/// buf: bytes to send\n///\n/// # Safety\n", relay(with_param_doc))

    def test_no_wrapped_api_no_pins_and_no_module(self) -> None:
        text = relay(NO_WRAPPED_API)
        self.assertNotIn("wrapped_api", text)
        self.assertNotIn("assert!", text)

    def test_wrapped_api_module_rendered_without_pins(self) -> None:
        text = relay(mutate(FIXTURE, 'feat_a = "XYD_FEAT_A"\n', ""))
        self.assertIn('pub mod wrapped_api {', text)
        self.assertIn('include!(concat!(env!("OUT_DIR"), "/wrapped_api.rs"));', text)
        self.assertNotIn("assert!", text)


class Validate(unittest.TestCase):
    RULE = "is not snake_case (an uppercase letter or '__'), which rustc requires of it"

    def validate(self, text: str) -> list[str]:
        return emit_abi_rs.validate(load(text))

    def test_rust_keyword_as_name(self) -> None:
        # gen is reserved from edition 2024
        for name in ("match", "crate", "gen"):
            with self.subTest(name=name):
                self.assertEqual(
                    self.validate(mutate(FIXTURE, "unit = ", f"{name} = ")),
                    [f"rust_abi: function.open_port.{name}: '{name}' is a Rust keyword"],
                )

    def test_a_name_whose_upper_camel_form_is_a_keyword(self) -> None:
        self.assertIn(
            "rust_abi: struct.self_: 'self_' renders as 'Self', a Rust keyword",
            self.validate(FIXTURE + '\n[struct.self_]\nv = "u32"\n'),
        )

    def test_field_parameter_count_or_local_rustc_calls_not_snake_case(self) -> None:
        for needle, replacement, where, names in (
            ("unit = ", "Unit = ", "function.open_port.Unit", ["Unit"]),
            ("bytes = ", "Bytes = ", "struct.stats.Bytes", ["Bytes"]),
            ("buf = ", "buf_ = ", "function.send.buf_", ["buf__count", "buf__local"]),
            ("generation = ", "generation_ = ", "function.open_port.generation_", ["generation__local"]),
        ):
            with self.subTest(names=names):
                self.assertEqual(
                    self.validate(mutate(FIXTURE, needle, replacement)),
                    [f"rust_abi: {where}: '{name}' {self.RULE}" for name in names],
                )

    def test_an_enum_conversion_rustc_calls_not_snake_case_as_the_binding_does(self) -> None:
        for name in ("toString", "name__x"):
            with self.subTest(name=name):
                text = mutate(FIXTURE, '_to_string = "to_string"', f'_to_string = "{name}"')
                message = f"typed_const.status._to_string: '{name}' {self.RULE}"
                self.assertEqual(self.validate(text), [f"rust_abi: {message}"])
                self.assertIn(f"rust: {message}", emit_binding_rs.validate(load(text)))

    def test_an_exported_functions_name_is_exempt(self) -> None:
        self.assertEqual(self.validate(mutate(FIXTURE, "[function.spend]", "[function.Spend]")), [])

    def test_opaque_field_is_not_implemented(self) -> None:
        self.assertEqual(
            self.validate(mutate(FIXTURE, 'bytes = "u64"', 'bytes = "token"')),
            ["rust_abi: struct.stats.bytes: a field of opaque_ref type is not implemented for Rust"],
        )

    def test_generated_names_are_refused_as_parameters_the_relay_writes_back(self) -> None:
        for name in emit_abi_rs._GENERATED_NAMES:
            for needle in ('generation = { _type = "u32", _ref = "out" }', 'pstats = { _type = "stats", _ref = "out"'):
                with self.subTest(name=name, needle=needle):
                    old = needle.split(" ")[0]
                    self.assertEqual(
                        self.validate(mutate(FIXTURE, needle, needle.replace(old, name, 1))),
                        [f"rust_abi: function.open_port.{name}: '{name}' is a name the generated code uses"],
                    )

    def test_names_the_body_reaches_only_before_its_result_or_through_a_path_are_not_refused(self) -> None:
        # by value, `in`, a buffer; the helpers are called through `self::` and the pin is a const
        for needle, name in (
            ('unit = "u32"', "result"),
            ('cfg = { _type', "result"),
            ('buf = { _type', "result"),
            ('unit = "u32"', "implementation"),
            ('buf = { _type', "c_bytes"),
            ('data = { _type', "c_bytes_mut"),
            ('pdst = { _type', "c_bytes_zeroed"),
            ('pdst = { _type', "c_len"),
        ):
            with self.subTest(name=name, needle=needle):
                text = mutate(KITCHEN_SINK, needle, needle.replace(needle.split(" ")[0], name, 1))
                self.assertEqual(self.validate(text), [])

    def test_a_parameter_named_like_another_parameters_local(self) -> None:
        self.assertEqual(
            self.validate(mutate(FIXTURE, 'unit = "u32"', 'pport_local = "u32"')),
            ["rust_abi: function.open_port.pport_local: 'pport_local' is a name the generated code uses"],
        )

    def test_module_scope_collisions(self) -> None:
        for text, message in (
            (FIXTURE + '\n[struct.none]\nv = "u32"\n', "None would be defined more than once, by the Rust prelude and struct.none"),
            (FIXTURE + '\n[struct.option]\nv = "u32"\n', "Option would be defined more than once, by the Rust prelude and struct.option"),
            (FIXTURE + '\n[struct.result]\nv = "u32"\n', "Result would be defined more than once, by the Rust prelude and struct.result"),
            # a boxed scalar is a tuple struct, so its re-export takes the value namespace the patterns reach too
            (FIXTURE + '\n[[boxed_scalar]]\n[boxed_scalar.err]\n_base_type = "u32"\n',
             "Err would be defined more than once, by the Rust prelude and boxed_scalar.err"),
            (FIXTURE + '\n[[boxed_scalar]]\n[boxed_scalar.ok]\n_base_type = "u32"\n',
             "Ok would be defined more than once, by the Rust prelude and boxed_scalar.ok"),
            (FIXTURE + '\n[[boxed_scalar]]\n[boxed_scalar.some]\n_base_type = "u32"\n',
             "Some would be defined more than once, by the Rust prelude and boxed_scalar.some"),
            (mutate(mutate(FIXTURE, '_namespace = "xy"', '_namespace = "c"'), "[function.spend]", "[function.bytes]"),
             "c_bytes would be defined more than once, by the relay's buffer helper and function.bytes"),
            (mutate(mutate(FIXTURE, '_namespace = "xy"', '_namespace = "c"'), "[function.spend]", "[function.len]"),
             "c_len would be defined more than once, by the relay's buffer helper and function.len"),
        ):
            with self.subTest(message=message):
                self.assertEqual(self.validate(text), [f"rust_abi: module scope: {message}"])

    def test_prelude_names_the_relay_does_not_spell_are_not_refused(self) -> None:
        self.assertEqual(self.validate(FIXTURE + UNSPELLED_PRELUDE_STRUCTS), [])

    def test_enum_collisions_are_the_bindings(self) -> None:
        text = mutate(FIXTURE, '_to_string = "to_string"', '_to_string = "try_from"')
        message = (
            "enum Status: try_from would be defined more than once, by the generated TryFrom conversion and "
            "typed_const.status._to_string"
        )
        self.assertEqual(self.validate(text), [f"rust_abi: {message}"])
        self.assertEqual(emit_binding_rs.validate(load(text)), [f"rust: {message}"])



class GroupDocstring(unittest.TestCase):
    def test_a_function_groups_docstring_is_a_line_above_its_first_export(self) -> None:
        text = relay(DOCUMENTED_FUNCTION_GROUPS)
        self.assertIn("\n// port lifecycle\n/// pstats: may be null\n///\n" + SAFETY + "xy_open_port(", text)
        self.assertIn("\n}\n\n/// release the port\n///\n" + SAFETY + "xy_destroy_port(", text)
        self.assertIn("\n// traffic\n/// buf: bytes to send\n///\n" + SAFETY + "xy_send(", text)


if __name__ == "__main__":
    unittest.main()
