import unittest

from api_gen import emit_cpp_wrapper, model
from api_gen.tests.support import FIXTURE, load


def wrapper(text: str = FIXTURE) -> str:
    return emit_cpp_wrapper.wrapper(load(text), source_name="xy_api.adef.toml", stem="xy_api")


class Wrapper(unittest.TestCase):
    def setUp(self) -> None:
        self.text = wrapper()

    def test_includes_the_c_header_then_only_standard_headers(self) -> None:
        includes = [line for line in self.text.splitlines() if line.startswith("#include")]
        self.assertEqual(includes[0], '#include "xy_api.h"')
        for include in includes[1:]:
            self.assertRegex(include, r"#include <\w+>")
        first_line = self.text.splitlines()[0]
        self.assertIn("GENERATED", first_line)
        self.assertIn("xy_api.adef.toml", first_line)
        self.assertTrue(self.text.rstrip().endswith("}  // namespace xy"))

    def test_no_exceptions_no_allocation(self) -> None:
        for absent in ("throw", "new ", "malloc", "iostream"):
            self.assertNotIn(absent, self.text)

    def test_class_only_for_opaque_with_ctor(self) -> None:
        self.assertIn("class Port {\n", self.text)
        self.assertNotIn("class Token", self.text)
        self.assertNotIn("xy_spend", self.text)

    def test_no_dtor_no_release(self) -> None:
        text = wrapper(FIXTURE.replace('dtor = "destroy_port"\n', ""))
        self.assertNotIn("~Port", text)
        self.assertNotIn("release()", text)
        self.assertIn("  Status destroy_port() {\n", text)

    def test_member_collision_is_an_error(self) -> None:
        with self.assertRaises(model.DefinitionError) as caught:
            wrapper(FIXTURE.replace("[function.send]", "[function.release]"))
        self.assertIn("C++ wrapper: class Port: release would be defined more than once", str(caught.exception))

    def test_namespace_collision_is_an_error(self) -> None:
        with self.assertRaises(model.DefinitionError) as caught:
            wrapper(FIXTURE.replace("[untyped_const]\n", "[untyped_const]\nx = 1\n") + '\n[struct.x]\nv = "u32"\n')
        self.assertIn("C++ wrapper: namespace xy: X would be defined more than once", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
