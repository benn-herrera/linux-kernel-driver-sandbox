import unittest

from api_gen import emit_c, emit_lua, model
from api_gen.tests.test_api_gen import FIXTURE, load


class ModelErrors(unittest.TestCase):
    def assert_error(self, text: str, fragment: str) -> None:
        with self.assertRaises(model.DefinitionError) as caught:
            load(text)
        self.assertIn(fragment, str(caught.exception))

    def test_keyword_as_name(self) -> None:
        for text in (
            FIXTURE.replace("bytes = ", "end = "),
            FIXTURE.replace('unit = "u32"', 'int = "u32"'),
            FIXTURE + '\n[function.end]\nreturn = "status"\n',
        ):
            self.assert_error(text, "keyword or a name")

    def test_cpp_keyword_as_name(self) -> None:
        for text in (
            FIXTURE.replace("unit = ", "class = "),
            FIXTURE.replace("count = ", "template = "),
            FIXTURE + '\n[function.new]\nreturn = "status"\n',
        ):
            self.assert_error(text, "keyword")

    def test_generated_local_only_reserved_for_parameters(self) -> None:
        self.assert_error(FIXTURE.replace('unit = "u32"', 'result = "u32"'), "keyword or a name")
        load(FIXTURE.replace("status", "result"))

    def test_function_named_like_a_type(self) -> None:
        self.assert_error(FIXTURE + '\n[function.stats]\nreturn = "status"\n', "already defined by struct.stats")

    def test_struct_named_like_an_opaque_tag(self) -> None:
        self.assert_error(FIXTURE + '\n[struct.port_opaque]\nx = "u32"\n', "already defined by opaque_ref.port")

    def test_memory_needs_size(self) -> None:
        self.assert_error(FIXTURE.replace(', size = "len"', ""), "names its 'size' parameter")

    def test_size_serves_one_buffer(self) -> None:
        text = FIXTURE.replace('len = "u64"', 'len = "u64"\nbuf2 = { type = "memory", outref = true, size = "len" }')
        self.assert_error(text, "already the size of 'buf'")

    def test_functions_optional(self) -> None:
        api = load('[general]\nnamespace = "xy"\nversion = [0,0,0,1]\n')
        self.assertIn("M.raw = {\n}", emit_lua.module(api, source_name="x", library="libxy.so"))
        emit_c.header(api, source_name="x")

    def test_return_enum_needs_zero(self) -> None:
        self.assert_error(FIXTURE.replace("ok = 0", "ok = 1"), "no zero-valued entry")

    def test_quoted_library_rejected(self) -> None:
        self.assert_error(FIXTURE.replace('library = "libxy.so"', 'library = "lib\\"xy.so"'), "must not contain")
        self.assert_error(FIXTURE.replace('header = "xy/', 'header = "xy\\\\'), "must not contain")

    def test_bit_index_range(self) -> None:
        self.assert_error(FIXTURE.replace("value = 3,", "value = 31,"), "bit index must be 0..30")
        load(FIXTURE.replace("value = 3,", "value = 30,"))

    def test_version_first_byte_range(self) -> None:
        self.assert_error(FIXTURE.replace("[1, 2, 3, 4]", "[128, 2, 3, 4]"), "first byte must be 0..127")
        load(FIXTURE.replace("[1, 2, 3, 4]", "[127, 2, 3, 4]"))

    def test_version_value(self) -> None:
        self.assertEqual(load().version_value(), 0x01020304)

    def test_docstring_terminators_rejected(self) -> None:
        self.assert_error(FIXTURE.replace('docstring = "wire magic"', 'docstring = "wire */ magic"'), "must not contain")

    def test_int32_range(self) -> None:
        self.assert_error(FIXTURE.replace("ok = 0", "ok = 0x80000000"), "int32 range")

    def test_builtin_shadow(self) -> None:
        self.assert_error(FIXTURE + '\n[struct.u32]\nx = "u64"\n', "shadows builtin")

    def test_constant_uniqueness(self) -> None:
        self.assert_error(
            FIXTURE.replace("feat_a = 0\n", "feat_a = 0\napi_version = 5\n"),
            "already defined by the API version constant",
        )
        self.assert_error(
            FIXTURE.replace("ok = 0\n", "ok = 0\nfeat_a = 4\n"),
            "already defined by untyped_bit_const.feat_a",
        )

    def test_string_const_rejects_newline(self) -> None:
        self.assert_error(FIXTURE.replace('product = "xy widget"', 'product = "xy\\nwidget"'), "newline")

    def test_ctor_cannot_cache_a_memory_outref(self) -> None:
        self.assert_error(
            FIXTURE.replace(
                'generation = { type = "u32", outref = true }',
                'generation = { type = "u32", outref = true }\n'
                'blob = { type = "memory", outref = true, size = "unit" }',
            ),
            "a constructor cannot cache a memory outref",
        )


if __name__ == "__main__":
    unittest.main()
