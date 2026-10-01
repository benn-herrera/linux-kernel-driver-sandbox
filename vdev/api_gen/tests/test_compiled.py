"""Compiled and executed checks of the generated outputs. They need clang, clang++,
luajit, make, rustc, rustfmt, clippy-driver and bindgen, the build container's pinned
toolchain; `just api-gen-test-vdev` runs them there. Every Rust compile gate runs under
clippy at each of `EDITIONS`, the generated Rust being edition-agnostic, and clippy is
rustc with lints added, so it gates both; a check that a build fails, or a build that only
produces a program or library to run, uses rustc at the newest."""

import contextlib
import functools
import os
import shutil
import signal
import subprocess
import tempfile
import unittest
from pathlib import Path

from api_gen import model
from api_gen.tests.support import (
    C_BASE_TYPES, EXERCISES, KITCHEN_SINK, REFS, UNSPELLED_PRELUDE_STRUCTS, expected_constants, load, mutate, run_main,
)

TESTS = Path(__file__).resolve().parent
TOOLS = ("clang", "clang++", "luajit", "make", "rustc", "rustfmt", "clippy-driver", "bindgen")
CFLAGS = ["-std=c17", "-fsyntax-only", "-Wall", "-Wextra", "-Werror"]
CXX_SYNTAX = ["clang++", "--std=c++20", "-fsyntax-only", "-Wall", "-Wextra", "-Werror"]
EDITIONS = ("2021", "2024")
EDITION = EDITIONS[-1]
# as the generator runs it: rustfmt's layout depends on the style edition, so it is checked at one
RUSTFMT_CHECK = ["rustfmt", "--check", "--edition", "2024", "--config-path", "/dev/null"]


def rust_cdylib(edition: str, *, compiler: str = "rustc") -> list[str]:
    return [compiler, "--edition", edition, "--crate-type", "cdylib", "-D", "warnings"]


def clippy_cdylib(edition: str) -> list[str]:
    return rust_cdylib(edition, compiler="clippy-driver")


def clippy_lib(edition: str) -> list[str]:
    """A lib crate type-checks a binding's `extern` block without linking the library, and
    is where clippy sees the binding's public API, as it lints only what a crate exports."""
    return ["clippy-driver", "--edition", edition, "--crate-type", "lib", "-D", "warnings"]


_build: tempfile.TemporaryDirectory | None = None
TMP = Path()
INC = Path()
RUST_DIR = Path()  # the generated rust/ directory of KITCHEN_SINK, API_GEN_RUST_DIR
RS_FAKE = Path()  # the directory holding fake_xy.rs built as libxy.so; TMP holds fake_xy.cpp's
HEADER = Path()  # the fixture's wrapped API header, its pinned macro matching
BAD_HEADER = Path()  # the same header, its pinned macro mismatched


def run(args: list[str | Path], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run([str(a) for a in args], capture_output=True, text=True, **kwargs)


def build_or_fail(args: list[str | Path]) -> None:
    result = run(args)
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(map(str, args))} failed:\n{result.stderr}")


def generate(definition: Path, generated: Path, project: str) -> None:
    code, _, stderr = run_main([str(definition), "--generated", str(generated), "--project", project])
    if code != 0:
        raise RuntimeError(f"api_gen failed on {definition}:\n{stderr}")


@functools.cache
def wrapped_out_dir(header: Path, include: Path | None = None) -> Path:
    """The directory holding `wrapped_api.rs`, `bindgen`'s rendering of the C `header`, as a
    crate's `build.rs` writes it into `OUT_DIR`; rendered once per header for the run.
    `include` is the header's own include directory."""
    out = Path(tempfile.mkdtemp(prefix="bindgen", dir=TMP))
    build_or_fail(["bindgen", header, "-o", out / "wrapped_api.rs", *([] if include is None else ["--", f"-I{include}"])])
    return out


def crate_env(*, rust_dir: Path, header: Path | None, include: Path | None = None) -> dict[str, str]:
    """The environment a crate over the relay builds in, as the implementation's build
    supplies it: `API_GEN_RUST_DIR` naming `rust_dir`, the generated `rust/` directory,
    and, with a wrapped API `header`, `OUT_DIR` holding its `wrapped_out_dir()` rendering."""
    env = {**os.environ, "API_GEN_RUST_DIR": str(rust_dir)}
    if header is not None:
        env["OUT_DIR"] = str(wrapped_out_dir(header, include))
    return env


def fakes() -> dict[str, Path]:
    """Each fake implementation of KITCHEN_SINK, by the directory its `libxy.so` is in."""
    return {"C++ fake": TMP, "Rust fake": RS_FAKE}


def library_env(library: Path) -> dict[str, str]:
    return {**os.environ, "LD_LIBRARY_PATH": str(library)}


def stub_library(text: str, root: Path) -> Path:
    """Definition `text`'s Rust binding and relay generated under `root`, and its Rust stub
    built over the relay as `libxy.so`, the library the binding links: a stub returns
    `Ok(())` and the relay writes each `out` from its default, a fake like any other.
    Returns the binding's path."""
    definition = write(root / "xy_api.adef.toml", text)
    code, _, stderr = run_main(
        [str(definition), "--generated", str(root / "generated"), "--project", "xy", "--outputs=rs,abi_rs,stub_rs"]
    )
    if code != 0:
        raise RuntimeError(f"api_gen failed:\n{stderr}")
    env = crate_env(rust_dir=root / "generated" / "rust", header=HEADER)
    result = run([*rust_cdylib(EDITION), "-o", root / "libxy.so", root / "generated" / "stub" / "xy_api.rs"], env=env)
    if result.returncode != 0:
        raise RuntimeError(f"the stub failed to build:\n{result.stderr}")
    return root / "generated" / "rust" / "xy_api.rs"


def run_beside(binding: Path, name: str, main: str, library: Path) -> subprocess.CompletedProcess:
    """`main`, a Rust program declaring `mod xy_api;`, written as `name.rs` beside `binding`
    and built against the `libxy.so` in `library`, then run."""
    source = write(binding.parent / f"{name}.rs", main)
    build_or_fail(["rustc", "--edition", EDITION, f"-L{library}", "-o", binding.parent / name, source])
    return run([binding.parent / name], env=library_env(library))


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
    global _build, TMP, INC, RUST_DIR, RS_FAKE, HEADER, BAD_HEADER
    require_tools()
    _build = tempfile.TemporaryDirectory()
    TMP = Path(_build.name)
    INC = TMP / "generated" / "include" / "xy"
    RUST_DIR = TMP / "generated" / "rust"
    RS_FAKE = TMP / "rsfake"

    generate(write(TMP / "xy_api.adef.toml", KITCHEN_SINK), TMP / "generated", "xy")
    HEADER = write(TMP / "xy" / "driver" / "xy_ioctl.h", "#define XYD_FEAT_A 1\n")
    BAD_HEADER = write(TMP / "bad" / "xy" / "driver" / "xy_ioctl.h", "#define XYD_FEAT_A 2\n")
    write(TMP / "values.c", values_tu())
    # the fake is the implementation: XY_IMPL pulls in the wrapped API header, hence -I<tmp>
    build_or_fail(
        ["clang++", "-std=c++20", "-shared", "-fPIC", "-Wall", "-Wextra", "-Werror",
         f"-I{INC}", f"-I{TMP}", "-o", TMP / "libxy.so", TESTS / "fake_xy.cpp"]
    )
    # the same implementation in Rust behind the generated relay, a second libxy.so
    RS_FAKE.mkdir()
    env = crate_env(rust_dir=RUST_DIR, header=HEADER)
    result = run([*rust_cdylib(EDITION), "-o", RS_FAKE / "libxy.so", TESTS / "fake_xy.rs"], env=env)
    if result.returncode != 0:
        raise RuntimeError(f"fake_xy.rs failed to build over the generated relay:\n{result.stderr}")
    # each consumer runs against either fake, LD_LIBRARY_PATH choosing which
    build_or_fail(
        ["clang++", "-std=c++20", "-Wall", "-Wextra", "-Wshadow", "-Werror", f"-I{INC}",
         "-o", TMP / "consumer", TESTS / "consumer_xy.cpp", f"-L{TMP}", "-lxy"]
    )


def tearDownModule() -> None:
    wrapped_out_dir.cache_clear()
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
                [str(definition), "--generated", str(root / "generated"), "--project", "xy", "--outputs=h,hpp"]
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
            code, _, stderr = run_main([str(definition), "--generated", str(Path(tmp) / "generated"), "--project", "xy"])
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


class StubRs(unittest.TestCase):
    """The relay and the stub over it, built as the implementation's crate root is."""

    def stub(self) -> Path:
        return TMP / "generated" / "stub" / "xy_api.rs"

    def build(
        self, *, compiler: list[str], header: Path | None = None, rust_dir: Path | None = None, source: Path | None = None
    ) -> subprocess.CompletedProcess:
        """`source`, the stub by default, as a cdylib over the relay in `rust_dir`, KITCHEN_SINK's
        by default, its `OUT_DIR` holding bindgen's rendering of `header`, `HEADER` by default."""
        env = crate_env(rust_dir=rust_dir or RUST_DIR, header=header or HEADER)
        library = Path(tempfile.mkdtemp(dir=TMP)) / "libxy_stub.so"
        return run([*compiler, "-o", library, source or self.stub()], env=env)

    def test_relay_and_stub_are_rustfmt_clean(self) -> None:
        result = run([*RUSTFMT_CHECK, RUST_DIR / "xy_api_abi.rs", self.stub()])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_builds_clippy_clean_with_pins_active_against_the_wrapped_header(self) -> None:
        for edition in EDITIONS:
            with self.subTest(edition=edition):
                result = self.build(compiler=clippy_cdylib(edition))
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_pin_mismatch_fails_the_implementation_build(self) -> None:
        result = self.build(compiler=rust_cdylib(EDITION), header=BAD_HEADER)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("XY_FEAT_A must match XYD_FEAT_A", result.stderr)

    def test_a_relay_regenerated_for_a_changed_function_fails_the_stub_naming_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            definition = write(Path(tmp) / "xy_api.adef.toml", mutate(KITCHEN_SINK, 'offset = "u64"\n', 'offset = "u64"\nwhence = "u32"\n'))
            code, _, stderr = run_main([str(definition), "--generated", str(Path(tmp) / "generated"), "--project", "xy", "--outputs=abi_rs"])
            self.assertEqual(code, 0, stderr)
            result = self.build(compiler=rust_cdylib(EDITION), rust_dir=Path(tmp) / "generated" / "rust")
            self.assertNotEqual(result.returncode, 0)
            # the pin's mismatch, naming the implementation
            self.assertIn("error[E0308]", result.stderr)
            self.assertIn("{seek}", result.stderr)

    def test_the_pin_refuses_an_implementation_the_relay_could_not_call_soundly(self) -> None:
        # each a one-line edit of fake_xy.rs's send: a borrow kept past the call, an unsafe
        # fn with no stated precondition, and a signature the definition does not have
        send = "pub fn send(hport: ffi::xy_port, buf: Option<&[u8]>)"
        fake = (TESTS / "fake_xy.rs").read_text(encoding="utf-8")
        self.assertEqual(fake.count(send), 1)
        with tempfile.TemporaryDirectory() as tmp:
            for name, replacement, expected in (
                ("static", "pub fn send(hport: ffi::xy_port, buf: Option<&'static [u8]>)", "one type is more general than the other"),
                ("unsafe", "pub unsafe fn send(hport: ffi::xy_port, buf: Option<&[u8]>)", "expected safe fn, found unsafe fn"),
                ("extra", "pub fn send(hport: ffi::xy_port, buf: Option<&[u8]>, _extra: u32)", "aborting due to 1 previous error"),
            ):
                with self.subTest(variant=name):
                    source = write(Path(tmp) / f"{name}.rs", fake.replace(send, replacement))
                    result = self.build(compiler=rust_cdylib(EDITION), source=source)
                    self.assertNotEqual(result.returncode, 0)
                    for text in ("error[E0308]", "{send}", expected):
                        self.assertIn(text, result.stderr)

    def test_structs_named_like_prelude_names_the_relay_does_not_spell_build_clean(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            definition = write(root / "xy_api.adef.toml", KITCHEN_SINK + UNSPELLED_PRELUDE_STRUCTS)
            code, _, stderr = run_main([str(definition), "--generated", str(root / "generated"), "--project", "xy", "--outputs=abi_rs,stub_rs"])
            self.assertEqual(code, 0, stderr)
            stub = root / "generated" / "stub" / "xy_api.rs"
            result = self.build(compiler=clippy_cdylib(EDITION), rust_dir=root / "generated" / "rust", source=stub)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_refs_binding_relay_and_stub_build_clean(self) -> None:
        """support.REFS's binding, relay and stub: each rustfmt-clean, the stub built over the
        relay as a cdylib and the binding as a lib, under clippy at each edition."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            definition = write(root / "xy_api.adef.toml", REFS)
            code, _, stderr = run_main([str(definition), "--generated", str(root / "generated"), "--project", "xy", "--outputs=rs,abi_rs,stub_rs"])
            self.assertEqual(code, 0, stderr)
            rust_dir, stub = root / "generated" / "rust", root / "generated" / "stub" / "xy_api.rs"
            result = run([*RUSTFMT_CHECK, rust_dir / "xy_api.rs", rust_dir / "xy_api_abi.rs", stub])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for edition in EDITIONS:
                with self.subTest(stub=edition):
                    result = self.build(compiler=clippy_cdylib(edition), rust_dir=rust_dir, source=stub)
                    self.assertEqual(result.returncode, 0, result.stderr)
                with self.subTest(binding=edition):
                    result = run([*clippy_lib(edition), "-o", root / f"libxy_api_{edition}.rlib", rust_dir / "xy_api.rs"])
                    self.assertEqual(result.returncode, 0, result.stderr)


class RustFake(unittest.TestCase):
    """fake_xy.rs behind the generated relay, and a bare C caller of it."""

    @classmethod
    def setUpClass(cls) -> None:
        build_or_fail(
            ["clang", "-std=c17", "-Wall", "-Wextra", "-Werror", f"-I{INC}",
             "-o", RS_FAKE / "edge", TESTS / "edge_xy.c", f"-L{RS_FAKE}", "-lxy"]
        )

    def test_builds_clippy_clean_at_each_edition(self) -> None:
        env = crate_env(rust_dir=RUST_DIR, header=HEADER)
        for edition in EDITIONS:
            with self.subTest(edition=edition):
                result = run([*clippy_cdylib(edition), "-o", RS_FAKE / "libxy_gate.so", TESTS / "fake_xy.rs"], env=env)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_relay_answers_what_no_binding_sends(self) -> None:
        code = run([RS_FAKE / "edge"], env=library_env(RS_FAKE)).returncode
        self.assertEqual(code, 0, f"edge_xy exit {code}; edge_xy.c's header names each case's code")

    def test_a_panic_in_the_implementation_aborts_the_process(self) -> None:
        result = run([RS_FAKE / "edge", "panic"], env=library_env(RS_FAKE))
        self.assertEqual(result.returncode, -signal.SIGABRT, result.stderr)
        self.assertIn("fake seek: offset u64::MAX", result.stderr)
        # the abort is the `extern "C"` boundary's, not an unwind that failed to start
        self.assertIn("panic in a function that cannot unwind", result.stderr)


class BindingRs(unittest.TestCase):
    def binding(self) -> Path:
        return RUST_DIR / "xy_api.rs"

    def test_is_rustfmt_clean(self) -> None:
        result = run([*RUSTFMT_CHECK, self.binding()])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_is_clippy_clean_as_a_lib(self) -> None:
        for edition in EDITIONS:
            with self.subTest(edition=edition):
                result = run([*clippy_lib(edition), "-o", TMP / "libxy_api_clippy.rlib", self.binding()])
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_consumer_builds_clippy_clean_and_runs_against_either_fake(self) -> None:
        # consumer_xy.rs beside the binding its `mod xy_api;` names
        source = RUST_DIR / "consumer_xy.rs"
        shutil.copyfile(TESTS / "consumer_xy.rs", source)
        for edition in EDITIONS:
            program = TMP / f"consumer_rs_{edition}"
            result = run(["clippy-driver", "--edition", edition, "-D", "warnings", f"-L{TMP}", "-o", program, source])
            self.assertEqual(result.returncode, 0, result.stderr)
            for fake, library in fakes().items():
                with self.subTest(edition=edition, fake=fake):
                    code = run([program], env=library_env(library)).returncode
                    self.assertEqual(code, 0, f"consumer exit {code}")

    def test_an_unnamed_result_panics_naming_the_function_and_the_enum(self) -> None:
        # only fake_xy.cpp can answer outside the enum: an implementation behind the relay returns named entries
        main = """#[allow(dead_code)]
mod xy_api;

fn main() -> std::process::ExitCode {
    let port = xy_api::Port::create(3).expect("the C++ fake opens unit 3");
    if std::panic::catch_unwind(|| port.seek(12345)).is_ok() {
        return 19.into();
    }
    0.into()
}
"""
        with tempfile.TemporaryDirectory() as tmp:
            binding = Path(tmp) / "xy_api.rs"
            shutil.copyfile(self.binding(), binding)
            result = run_beside(binding, "unnamed", main, TMP)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("xy_seek returned a value xy_status does not name", result.stderr)


class RefsOverTheStub(unittest.TestCase):
    """Programs over support.REFS's binding against its Rust stub built as `libxy.so`."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(tempfile.mkdtemp(dir=TMP))
        cls.binding = stub_library(REFS, cls.root)

    def test_enum_by_reference_round_trips_and_a_cached_enum_out_converts(self) -> None:
        # the stub writes nothing: each enum reached through `in` or `inout` travels to C and
        # back unchanged, and each `out`, the cached one included, comes back as the relay's
        # default, the zero entry
        main = """#[allow(dead_code)]
mod xy_api;
use xy_api::{Mode, Port};

fn main() -> std::process::ExitCode {
    let port = Port::create(1).expect("the stub returns the zero entry");
    if port.generation() != Mode::Fine {
        return 1.into();
    }
    let (mut cur, mut seen, mut last) = (Mode::Slow, Mode::Slow, Mode::Slow);
    let steered = port.steer(&Mode::Slow, &mut cur, Some(&Mode::Slow), Some(&mut seen), Some(&mut last));
    if steered != Ok(()) || [cur, seen, last] != [Mode::Slow, Mode::Slow, Mode::Fine] {
        return 2.into();
    }
    if port.steer(&Mode::Fine, &mut cur, None, None, None) != Ok(()) || cur != Mode::Slow {
        return 3.into();
    }
    0.into()
}
"""
        result = run_beside(self.binding, "enums", main, self.root)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_slice_longer_than_its_count_type_can_count_panics(self) -> None:
        main = """#[allow(dead_code)]
mod xy_api;

fn main() -> std::process::ExitCode {
    let port = xy_api::Port::create(1).expect("the stub returns the zero entry");
    if port.send_short(&[0; 255]) != Ok(()) {
        return 1.into();
    }
    if std::panic::catch_unwind(|| port.send_short(&[0; 256])).is_ok() {
        return 2.into();
    }
    0.into()
}
"""
        result = run_beside(self.binding, "slice", main, self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("buf is longer than u8 can count", result.stderr)


class Wrapper(unittest.TestCase):
    def test_consumer_builds_and_runs_against_either_fake(self) -> None:
        for fake, library in fakes().items():
            with self.subTest(fake=fake):
                code = run([TMP / "consumer"], env=library_env(library)).returncode
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

    def test_module_runs_against_either_fake(self) -> None:
        module = TMP / "generated" / "binding" / "xy_api.lua"
        for fake, library in fakes().items():
            with self.subTest(fake=fake):
                result = run(["luajit", TESTS / "check_xy.lua", module], env=library_env(library))
                self.assertEqual(result.returncode, 0, result.stderr)
                found = {}
                for line in result.stdout.splitlines():
                    name, value = line.split("=", 1)
                    found[name] = int(value) if value.lstrip("-").isdigit() else value
                self.assertEqual(found, expected_constants(load(KITCHEN_SINK)))

    def test_finalizer_runs_after_module_is_unreachable(self) -> None:
        module = TMP / "generated" / "binding" / "xy_api.lua"
        env = library_env(TMP)

        result = run(["luajit", TESTS / "gc_xy.lua", module], env=env)
        self.assertEqual(result.returncode, 0, result.stderr)

        error_script = write(
            TMP / "gc_error_xy.lua",
            'local M = dofile(arg[1])\nlocal p = M.Port.new(1)\nerror("x")\n',
        )
        result = run(["luajit", error_script, module], env=env)
        self.assertEqual(result.returncode, 1, result.stderr)


class Gendeps(unittest.TestCase):
    DEFINITION = "a.adef.toml"  # unlike KITCHEN_SINK's _name, which names the outputs

    def make_n(self, *flags: str) -> str:
        """`make -n`, in the directory holding KITCHEN_SINK as `DEFINITION`, over the gendeps
        fragment for `flags`, printing each GENERATED target and then the recipe make would
        run; returns make's stdout."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / self.DEFINITION, KITCHEN_SINK)
            with contextlib.chdir(root):
                code, fragment, stderr = run_main(["gendeps", *flags, self.DEFINITION])
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
            "python3 -m api_gen a.adef.toml --generated OUTDIR --project xy --outputs=h,hpp,lua,stub_cpp,rs,abi_rs,stub_rs",
            out,
        )

    def test_subset_fragment_makes_only_its_outputs(self) -> None:
        out = self.make_n("--outputs=hpp,lua")
        self.assertIn("python3 -m api_gen a.adef.toml --generated OUTDIR --project xy --outputs=hpp,lua\n", out)
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
                api = model.load(definition)
                generated = Path(tmp) / "generated"
                code, _, stderr = run_main([str(definition), "--generated", str(generated), "--project", exercise])
                self.assertEqual(code, 0, stderr)
                include = generated / "include" / exercise

                stub = run([*CXX_SYNTAX, f"-I{include}", f"-I{EXERCISES}", generated / "stub" / f"{api.name}.cpp"])
                self.assertEqual(stub.returncode, 0, stub.stderr)
                tu = write(Path(tmp) / "tu.cpp", f'#include "{api.name}.hpp"\nint main() {{ return 0; }}\n')
                wrapper = run([*CXX_SYNTAX, f"-I{include}", tu])
                self.assertEqual(wrapper.returncode, 0, wrapper.stderr)
                lua = run(["luajit", "-bl", generated / "binding" / f"{api.name}.lua"])
                self.assertEqual(lua.returncode, 0, lua.stderr)

                # the relay and the stub over it, as the implementation's crate root, and the binding
                rust_stub, rust_binding = generated / "stub" / f"{api.name}.rs", generated / "rust" / f"{api.name}.rs"
                rustfmt = run([*RUSTFMT_CHECK, generated / "rust" / f"{api.name}_abi.rs", rust_stub, rust_binding])
                self.assertEqual(rustfmt.returncode, 0, rustfmt.stdout + rustfmt.stderr)
                env = crate_env(
                    rust_dir=generated / "rust",
                    header=None if api.wrapped_api is None else api_def.parents[1] / api.wrapped_api.header,
                    include=EXERCISES,
                )
                for edition in EDITIONS:
                    rust = run([*clippy_cdylib(edition), "-o", Path(tmp) / f"lib{api.name}_stub.so", rust_stub], env=env)
                    self.assertEqual(rust.returncode, 0, rust.stderr)
                    rust = run([*clippy_lib(edition), "-o", Path(tmp) / f"lib{api.name}.rlib", rust_binding])
                    self.assertEqual(rust.returncode, 0, rust.stderr)


if __name__ == "__main__":
    unittest.main()
