import re
import unittest

from api_gen import emit_c, emit_cpp_stub, model
from api_gen.tests.support import FIXTURE, KITCHEN_SINK, load, param_lists

STATUS_ERRORS = 'err_busy = { value = 9, docstring = "try later" }\nerr_other = { value = 0x7fffffff, format = "hex" }\n'


def stub(text: str = FIXTURE) -> str:
    return emit_cpp_stub.stub(load(text), source_name="xy_api.adef.toml", stem="xy_api")


class Stub(unittest.TestCase):
    def setUp(self) -> None:
        self.text = stub()

    def test_banner(self) -> None:
        first_line = self.text.splitlines()[0]
        self.assertIn("GENERATED", first_line)
        self.assertIn("xy_api.adef.toml", first_line)

    def test_preprocessor_lines_are_the_impl_guarded_include_then_the_std_headers(self) -> None:
        lines = [line for line in self.text.splitlines() if line.startswith("#")]
        self.assertEqual(
            lines,
            [
                "#define XY_IMPL",
                '#include "xy_api.h"',
                "#undef XY_IMPL",
                "#include <cerrno>",
                "#include <cstdint>",
                "#include <cstring>",
            ],
        )

    def test_signatures_match_the_header_in_document_order(self) -> None:
        api = load(KITCHEN_SINK)
        header = param_lists(emit_c.header(api, source_name="x"), r"XY_API xy_status ")
        definitions = param_lists(stub(KITCHEN_SINK), r"XY_API xy_status ")
        self.assertEqual(list(definitions), [f.name for f in api.functions])
        self.assertEqual(definitions, header)

    def test_failure_result_is_err_unsupported_else_first_nonzero(self) -> None:
        def returns(text: str) -> dict[str, str]:
            return dict(re.findall(r"xy_(\w+)\([^)]*\) \{.*?return (XY_\w+);", text, re.S))

        self.assertEqual(returns(stub()), {f.name: "XY_ERR_BUSY" for f in load().functions})
        self.assertEqual(
            returns(stub(KITCHEN_SINK)), {f.name: "XY_ERR_UNSUPPORTED" for f in load(KITCHEN_SINK).functions}
        )

    def test_no_nonzero_entry_is_an_error(self) -> None:
        with self.assertRaises(model.DefinitionError) as caught:
            stub(FIXTURE.replace(STATUS_ERRORS, ""))
        self.assertIn("cannot pick a failure result for the stub", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
