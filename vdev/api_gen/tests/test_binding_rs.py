import unittest
from pathlib import Path

from api_gen.emitters import emit_binding_rs
from api_gen.tests.support import FIXTURE, KITCHEN_SINK, REFS, assert_matches_expected, load, mutate

EXPECTED = Path(__file__).resolve().parent / "expected_binding_xy.rs"


def binding(text: str = FIXTURE) -> str:
    return emit_binding_rs.emit(load(text), source_name="xy_api.adef.toml", name="xy_api", library="libxy.so", project="xy")


class Binding(unittest.TestCase):
    def test_byte_identical_to_expected(self) -> None:
        assert_matches_expected(self, EXPECTED, binding(KITCHEN_SINK))

    def test_plain_conversion_names_the_last_entry_of_a_shared_value(self) -> None:
        text = binding(mutate(KITCHEN_SINK, "extra = 4\n", "extra = 16\n"))
        self.assertIn('        EXTRA => "EXTRA",\n', text)
        self.assertNotIn("MAX_UNITS =>", text)

    def test_an_enums_conversion_is_its_display(self) -> None:
        self.assertIn(
            "            Status::ErrFloor => \"ERR_FLOOR\",\n        }\n    }\n}\n\n"
            "impl core::fmt::Display for Status {\n"
            "    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {\n"
            "        f.write_str(Status::to_string(*self))\n    }\n}\n",
            binding(KITCHEN_SINK),
        )
        self.assertNotIn("Display", binding(mutate(FIXTURE, '_to_string = "to_string"\n', "")))


class OpaqueByValue(unittest.TestCase):
    """An opaque parameter by value is its class by reference where it has one."""

    def test_an_opaque_with_a_class_is_the_class_by_reference(self) -> None:
        text = binding(KITCHEN_SINK + '[function.attach]\n_return = "status"\nhport = "port"\npeer = "link"\n')
        self.assertIn("    pub fn attach(&self, peer: &DataLink) -> Result<(), Status> {\n", text)
        self.assertIn("        let raw = unsafe { ffi::xy_attach(self.handle, peer.handle) };\n", text)


class OpaqueByReference(unittest.TestCase):
    """An opaque `in` is its class by reference where it has one, passing the address of
    its handle; an `inout` is the raw handle even with a class, and a raw handle the
    library reads makes the method unsafe."""

    def setUp(self) -> None:
        self.text = binding(REFS)

    def test_an_in_with_a_class_is_the_class_by_reference_and_safe(self) -> None:
        self.assertIn(
            "    pub fn link_to(&self, peer: &DataLink, maybe: Option<&DataLink>) -> Result<(), Status> {\n",
            self.text,
        )
        self.assertIn(
            "            ffi::xy_link_to(\n"
            "                self.handle,\n"
            "                &peer.handle,\n"
            "                maybe.map_or(core::ptr::null(), |c| &c.handle),\n"
            "            )\n",
            self.text,
        )

    def test_an_inout_with_a_class_is_the_raw_handle_and_unsafe(self) -> None:
        self.assertIn(
            "    /// # Safety\n    ///\n"
            "    /// `cur` must be a handle the library issued and has not yet destroyed.\n"
            "    pub unsafe fn relink(&self, cur: &mut ffi::xy_link) -> Result<(), Status> {\n",
            self.text,
        )
        self.assertIn("        let raw = unsafe { ffi::xy_relink(self.handle, cur) };\n", self.text)

    def test_an_in_without_a_class_is_the_raw_handle_and_unsafe(self) -> None:
        self.assertIn(
            "    /// # Safety\n    ///\n"
            "    /// `tok` must be a handle the library issued and has not yet destroyed.\n"
            "    pub unsafe fn lend(&self, tok: &ffi::xy_token) -> Result<(), Status> {\n",
            self.text,
        )
        self.assertIn("        let raw = unsafe { ffi::xy_lend(self.handle, tok) };\n", self.text)


class EnumByReference(unittest.TestCase):
    """An enum reached through `_ref` is converted back only after a successful call."""

    def setUp(self) -> None:
        self.text = binding(REFS)

    def test_writable_ones_are_written_back_after_the_check(self) -> None:
        self.assertIn(
            "            return Err(result);\n        }\n"
            '        *cur = Mode::try_from(cur_raw).expect("xy_steer wrote a cur value xy_mode does not name");\n'
            "        if let (Some(m), Some(v)) = (seen, seen_raw) {\n"
            '            *m = Mode::try_from(v).expect("xy_steer wrote a seen value xy_mode does not name");\n'
            "        }\n"
            "        if let (Some(m), Some(v)) = (last, last_raw) {\n"
            '            *m = Mode::try_from(v).expect("xy_steer wrote a last value xy_mode does not name");\n'
            "        }\n"
            "        Ok(())\n",
            self.text,
        )


class Validate(unittest.TestCase):
    def validate(self, text: str) -> list[str]:
        return emit_binding_rs.validate(load(text))

    def test_rust_keyword_as_name(self) -> None:
        self.assertEqual(
            self.validate(mutate(FIXTURE, "unit = ", "match = ")),
            ["rust: function.open_port.match: 'match' is a Rust keyword"],
        )

    def test_name_rustc_calls_not_snake_case(self) -> None:
        rule = "is not snake_case (an uppercase letter or '__'), which rustc requires of it"
        enum_local = mutate(REFS, 'cur = { _type = "mode", _ref = "inout" }', 'cur_ = { _type = "mode", _ref = "inout" }')
        for text, where, name in (
            (mutate(FIXTURE, "[function.send]", "[function.Send]"), "function.Send", "Send"),
            (mutate(FIXTURE, "[function.send]", "[function.se__nd]"), "function.se__nd", "se__nd"),
            (mutate(FIXTURE, "unit = ", "Unit = "), "function.open_port.Unit", "Unit"),
            (mutate(FIXTURE, "bytes = ", "Bytes = "), "struct.stats.Bytes", "Bytes"),
            (mutate(FIXTURE, "bytes = ", "by__tes = "), "struct.stats.by__tes", "by__tes"),
            (mutate(FIXTURE, "buf = ", "buf_ = "), "function.send.buf_", "buf__count"),
            (enum_local, "function.steer.cur_", "cur__raw"),
            (mutate(FIXTURE, '_to_string = "limit_to_string"', '_to_string = "limitToString"'),
             "untyped_const[0]._to_string", "limitToString"),
            (mutate(FIXTURE, '_to_string = "to_string"', '_to_string = "toString"'), "typed_const.status._to_string", "toString"),
        ):
            with self.subTest(name=name):
                self.assertIn(f"rust: {where}: '{name}' {rule}", self.validate(text))

    def test_names_rustc_exempts_are_not_refused(self) -> None:
        # an extern-block function's name and the namespace in it; a parameter only the
        # extern block renders; a method's first parameter, which `self` replaces
        for needle, replacement in (
            ('_namespace = "xy"', '_namespace = "Xy"'),
            ('_namespace = "xy"', '_namespace = "xy_"'),
            ("[function.spend]", "[function.Spend]"),
            ('htoken = "token"', 'hToken = "token"'),
            ('[function.send]\n_return = "status"\nhport = ', '[function.send]\n_return = "status"\nhPort = '),
            ('[function.send]\n_return = "status"\nhport = ', '[function.send]\n_return = "status"\nhandle = '),
        ):
            with self.subTest(replacement=replacement):
                self.assertEqual(self.validate(mutate(FIXTURE, needle, replacement)), [])

    def test_a_name_whose_upper_camel_form_is_a_keyword(self) -> None:
        for text, where in (
            (FIXTURE + '\n[struct.self_]\nv = "u32"\n', "struct.self_"),
            (mutate(FIXTURE, "ok = 0\n", "ok = 0\nself_ = 3\n"), "typed_const.status.self_"),
            (FIXTURE + '\n[boxed_scalar.self_]\n_base_type = "u8"\n', "boxed_scalar.self_"),
        ):
            with self.subTest(where=where):
                self.assertIn(f"rust: {where}: 'self_' renders as 'Self', a Rust keyword", self.validate(text))

    def test_opaque_field_is_not_implemented(self) -> None:
        self.assertEqual(
            self.validate(mutate(FIXTURE, 'bytes = "u64"', 'bytes = "token"')),
            ["rust: struct.stats.bytes: a field of opaque_ref type is not implemented for Rust"],
        )

    def test_generated_names_are_refused_as_parameters_a_class_renders(self) -> None:
        for name in emit_binding_rs._GENERATED_NAMES:
            with self.subTest(name=name):
                self.assertEqual(
                    self.validate(mutate(FIXTURE, 'unit = "u32"', f'{name} = "u32"')),
                    [f"rust: function.open_port.{name}: '{name}' is a name the generated code uses"],
                )
                # spend has no class, so only the extern block renders its parameter
                self.assertEqual(self.validate(mutate(FIXTURE, 'htoken = "token"', f'{name} = "token"')), [])

    def test_names_the_class_reaches_only_through_a_path_or_a_field_are_not_refused(self) -> None:
        boxed = FIXTURE + '\n[boxed_scalar.offset]\n_base_type = "u64"\n'
        for text in (
            *(mutate(boxed, 'unit = "u32"', f'{name} = "u32"')
              for name in ("ffi", "handle", "core", "xy_send", "xy_port", "xy_port_opaque", "xy_status", "u32", "f64", "xy_offset")),
            mutate(boxed, 'pport = { _type = "port"', 'handle = { _type = "port"'),
            mutate(boxed, "[function.send]", "[function.xy_stats]"),
            mutate(boxed, "[function.send]", "[function.u32]"),
        ):
            with self.subTest(text=text):
                self.assertEqual(self.validate(text), [])

    def test_an_enum_local_is_refused_as_a_parameter_of_its_function(self) -> None:
        want = 'want = { _type = "mode", _ref = "in" }\n'
        self.assertEqual(
            self.validate(mutate(REFS, want, want + 'want_raw = "u32"\n')),
            ["rust: function.steer.want_raw: 'want_raw' is a name the generated code uses"],
        )
        # an enum `out` the caller receives is a local of its own name, with no `_raw` one
        peek = '\n[function.peek]\n_return = "status"\nhport = "port"\nst = { _type = "status", _ref = "out" }\nst_raw = "u32"\n'
        self.assertEqual(self.validate(FIXTURE + peek), [])

    def test_module_scope_collisions(self) -> None:
        for text, message in (
            (mutate(FIXTURE, "[[untyped_const]]\n", "[[untyped_const]]\nx = 1\n") + '\n[struct.x]\nv = "u32"\n',
             "X would be defined more than once, by untyped_const.x and struct.x"),
            (mutate(FIXTURE, '_to_string = "limit_to_string"', '_to_string = "feat_to_string"'),
             "feat_to_string would be defined more than once, by untyped_bit_const[0]._to_string and untyped_const[0]._to_string"),
            (FIXTURE + '\n[opaque_ref.h]\n_ctor = "mk"\n_class = "port"\n[function.mk]\n_return = "status"\np = { _type = "h", _ref = "out" }\n',
             "Port would be defined more than once, by opaque_ref.port._class and opaque_ref.h._class"),
        ):
            with self.subTest(message=message):
                self.assertEqual(self.validate(text), [f"rust: module scope: {message}"])

    def test_each_prelude_name_the_binding_spells_is_refused_at_module_scope(self) -> None:
        for name in emit_binding_rs._PRELUDE_NAMES:
            with self.subTest(name=name):
                snake = "".join(f"_{ch.lower()}" if ch.isupper() else ch for ch in name).lstrip("_")
                self.assertEqual(
                    self.validate(FIXTURE + f'\n[struct.{snake}]\nv = "u32"\n'),
                    [f"rust: module scope: {name} would be defined more than once, by the Rust prelude and struct.{snake}"],
                )

    def test_enums_conversions_never_collide_with_a_groups(self) -> None:
        self.assertEqual(self.validate(mutate(FIXTURE, '_to_string = "limit_to_string"', '_to_string = "to_string"')), [])

    def test_enum_collisions(self) -> None:
        self.assertEqual(
            self.validate(mutate(FIXTURE, "ok = 0\n", "ok = 0\nerr__busy = 3\n")),
            ["rust: enum Status: ErrBusy would be defined more than once, by typed_const.status.err__busy and "
             "typed_const.status.err_busy"],
        )
        self.assertEqual(
            self.validate(mutate(FIXTURE, '_to_string = "to_string"', '_to_string = "try_from"')),
            ["rust: enum Status: try_from would be defined more than once, by the generated TryFrom conversion and "
             "typed_const.status._to_string"],
        )

    def test_class_collisions(self) -> None:
        self.assertEqual(
            self.validate(mutate(FIXTURE, "[function.send]", "[function.release]")),
            ["rust: class Port: release would be defined more than once, by the class's own member and function.release"],
        )
        self.assertEqual(
            self.validate(mutate(FIXTURE, 'generation = { _type = "u32", _ref = "out" }', 'send = { _type = "u32", _ref = "out" }')),
            ["rust: class Port: send would be defined more than once, by function.send and function.open_port.send"],
        )
        self.assertEqual(
            self.validate(mutate(FIXTURE, "[function.send]", "[function.create]")),
            ["rust: class Port: create would be defined more than once, by the class's own member and function.create"],
        )

    def test_release_is_a_method_name_when_no_release_is_generated(self) -> None:
        text = mutate(mutate(FIXTURE, '_dtor = "destroy_port"\n', ""), "[function.send]", "[function.release]")
        self.assertEqual(self.validate(text), [])


if __name__ == "__main__":
    unittest.main()
