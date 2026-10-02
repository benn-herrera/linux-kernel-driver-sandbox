"""Rust language facts every Rust emitter shares: the keywords, rustc's snake_case rule,
the FFI spelling of a definition's types, the C-named constant, type and function
declarations a Rust file renders at the C header's ABI, the `ffi` module, enum and
re-export blocks the binding and the relay both carry with the checks that go with
them, and rustfmt, which lays out every Rust output."""

import re
import subprocess
from collections.abc import Iterable

from api_gen import naming
from api_gen.emitters import c
from api_gen.emitters.emitter import ToolError
from api_gen.model import (
    Api, BitConst, EnumEntry, Function, Group, LiteralTerm, Param, StringConst, Term, TypedConst, duplicate_objections,
    headed,
)

# Strict, reserved and weak keywords of editions 2021 and 2024 (`gen`, reserved from 2024):
# the generated text compiles under either.
RUST_KEYWORDS = frozenset(
    "as break const continue crate else enum extern false fn for if impl in let loop match mod "
    "move mut pub ref return self Self static struct super trait true type unsafe use where while "
    "async await dyn abstract become box do final macro override priv typeof unsized virtual yield "
    "try gen union macro_rules".split()
)

PRELUDE_NAMES = ("Default", "Drop", "Err", "Ok", "Option", "Result", "Some", "String", "ToString", "TryFrom")
"""The Rust prelude's names a hand-written crate root commonly spells unqualified, which an
item imported there would shadow: the stub's list. The binding and the relay each list
the ones their own text spells, since a prelude trait whose name an item takes stays in
scope for method calls."""

# clippy's default `too_many_arguments` threshold: a function with more parameters, the
# receiver counted, is refused under `-D warnings`
_MAX_ARGUMENTS = 7
_C_VOID = "core::ffi::c_void"
_INDENT = " " * 4
# rustc's `non_snake_case` test of a name once its leading and trailing `_` are trimmed
_NOT_SNAKE_CASE = re.compile(r"[A-Z]|__")


def rustfmt(text: str) -> str:
    """`text` as `rustfmt --edition 2024` lays it out under its default configuration;
    `--config-path /dev/null` keeps any `rustfmt.toml`, beside the cwd, above it or in the
    user's configuration directory, from reaching the output."""
    try:
        result = subprocess.run(
            ["rustfmt", "--edition", "2024", "--config-path", "/dev/null"],
            input=text, capture_output=True, encoding="utf-8",
        )
    except FileNotFoundError as e:
        raise ToolError("rustfmt is required for the Rust outputs and was not found on PATH") from e
    if result.returncode != 0:
        raise ToolError(f"rustfmt failed on a Rust output: {result.stderr.strip()}")
    return result.stdout


def rust_keyword_objections(api: Api) -> list[str]:
    """Every name that is a Rust keyword, unprefixed by an output."""
    return [f"{where}: '{name}' is a Rust keyword" for where, name in api.names() if name in RUST_KEYWORDS]


def snake_case_objections(names: Iterable[tuple[str, str]]) -> list[str]:
    """Every (where, rendered name) pair whose name rustc's `non_snake_case` lint refuses,
    a warning `-D warnings` makes an error. The caller passes only names the lint reaches:
    it skips `no_mangle` and `extern`-block function names."""
    return [
        f"{where}: '{name}' is not snake_case (an uppercase letter or '__'), which rustc requires of it"
        for where, name in names
        if _NOT_SNAKE_CASE.search(name.strip("_"))
    ]


def field_names(api: Api) -> list[tuple[str, str]]:
    """(where, name) of every struct field, which both Rust outputs render as a field."""
    return [(f"struct.{s.name}.{f.name}", f.name) for s in api.structs for f in s.fields]


def param_names(fn: Function, params: Iterable[Param]) -> list[tuple[str, str]]:
    """(where, name) of each of `params` of `fn` and of the count a `memory` one brings."""
    names = []
    for p in params:
        names.append((f"function.{fn.name}.{p.name}", p.name))
        if p.count_type is not None:
            names.append((f"function.{fn.name}.{p.name}", naming.count_param(p.name)))
    return names


def opaque_field_objections(api: Api) -> list[str]:
    """A struct field of opaque type: the structs derive `Default`, which a raw pointer
    has not."""
    return [
        f"struct.{s.name}.{f.name}: a field of opaque_ref type is not implemented for Rust"
        for s in api.structs
        for f in s.fields
        if api.kind(f.type) == "opaque"
    ]


def _doc_lines(lines: Iterable[str], *, indent: str = "") -> str:
    """Each of `lines` as a `///` line, an empty one as a bare `///`."""
    return "".join(f"{indent}///{' ' + line if line else ''}\n" for line in lines)


def doc_comment(doc: str | None, *, indent: str = "") -> str:
    """An item's docstring as a `///` line above it."""
    return _doc_lines([doc] if doc else [], indent=indent)


def function_docs(fn: Function, *, extra: Iterable[str] = (), safety: Iterable[str] = (), indent: str = "") -> str:
    """A function's `///` lines: its docstring, then each parameter's and `extra`, then,
    where `safety` has lines, a `# Safety` section holding them; a bare `///` ends the
    docstring before whatever follows it, so rustdoc keeps it a paragraph of its own and
    clippy reads no list or quote marker it opens with as running into the next line."""
    docstring = [fn.docstring] if fn.docstring else []
    rest = [*fn.docs()[len(docstring):], *extra]
    safety = list(safety)
    lines = [*docstring, *([""] if docstring and rest else []), *rest]
    if safety:
        lines += [*([""] if lines else []), "# Safety", "", *safety]
    return _doc_lines(lines, indent=indent)


def many_arguments_allow(count: int, *, indent: str = "") -> str:
    """The `too_many_arguments` allow above a function of `count` parameters, the receiver
    counted, where clippy's default threshold refuses it; else nothing."""
    return f"{indent}#[allow(clippy::too_many_arguments)]\n" if count > _MAX_ARGUMENTS else ""


def group_comment(doc: str | None, *, indent: str = "") -> str:
    """A group's docstring as a `//` line: a group is no item to document."""
    return f"{indent}// {doc}\n" if doc else ""


def rust_type(api: Api, type_name: str, *, path: str = "") -> str:
    """FFI spelling of a definition type used by value: a builtin is its own Rust name, any
    other type its C name, an enum's and an opaque's being their aliases, after `path`
    (`ffi::`) where the C names live in another module."""
    if type_name in naming.BUILTIN_C_TYPES:
        return type_name
    return path + naming.type_name(api.namespace, type_name)


def _param_type(api: Api, param: Param, *, path: str = "") -> str:
    """FFI spelling of a parameter: `rust_type()` by value, a raw pointer to it through
    `_ref`, a `c_void` pointer for `memory`."""
    if param.type == "memory":
        return f"*const {_C_VOID}" if param.ref == "in" else f"*mut {_C_VOID}"
    base = rust_type(api, param.type, path=path)
    if param.ref == "in":
        return f"*const {base}"
    if param.ref is not None:
        return f"*mut {base}"
    return base


def _params(api: Api, param: Param, *, path: str = "") -> list[tuple[str, str]]:
    """(Rust type, name) of each FFI parameter a definition parameter becomes: a `memory`
    parameter is the pointer and its byte count, every other parameter itself."""
    pairs = [(_param_type(api, param, path=path), param.name)]
    if param.count_type is not None:
        pairs.append((param.count_type, naming.count_param(param.name)))
    return pairs


def value_type(api: Api, type_name: str) -> str:
    """A non-memory type as a file spells it where `reexports()` and `ffi` are in scope: a
    boxed scalar or struct by its re-export, every other type `rust_type()` under `ffi::`."""
    if api.kind(type_name) in ("boxed", "struct"):
        return naming.upper_camel(type_name)
    return rust_type(api, type_name, path="ffi::")


def out_default(api: Api, type_name: str) -> str:
    """The function an `out` local of a non-memory type starts from: a null handle, else
    `value_type()`'s `default`."""
    if api.kind(type_name) == "opaque":
        return "core::ptr::null_mut"
    return f"{value_type(api, type_name)}::default"


def implementation_type(api: Api, param: Param) -> str:
    """The type the relay hands the implementation `param` as: a buffer one slice, `None`
    for null; a pointer an `Option` of a reference to `value_type()`, `None` for null; by
    value `value_type()` itself."""
    if param.type == "memory":
        return "Option<&[u8]>" if param.ref == "in" else "Option<&mut [u8]>"
    base = value_type(api, param.type)
    if param.ref == "in":
        return f"Option<&{base}>"
    if param.ref is not None:
        return f"Option<&mut {base}>"
    return base


def signature(api: Api, fn: Function, *, prefix: str, path: str = "") -> str:
    """`fn`'s FFI signature from `prefix` (`pub unsafe extern "C" fn `) to its return type,
    every C-named type after `path`."""
    parts = ", ".join(f"{n}: {t}" for p in fn.params for t, n in _params(api, p, path=path))
    return f"{prefix}{naming.function_name(api.namespace, fn.name)}({parts}) -> {rust_type(api, fn.returns, path=path)}"


def abi_file_name(name: str) -> str:
    """The relay's file name, which the relay is written as and the stub includes."""
    return f"{name}_abi.rs"


def ffi_module(blocks: Iterable[str], *, tail: str = "") -> str:
    """`pub mod ffi`, where the C names live: each of `blocks` indented under a blank line,
    then `tail`, already indented."""
    body = "".join("\n" + _indented(b, _INDENT) for b in blocks)
    return f"pub mod ffi {{\n    #![allow(non_camel_case_types)]\n{body}{tail}}}\n"


def reexports(api: Api) -> str:
    """Each boxed scalar, then each struct, re-exported from `ffi` under its UpperCamel name,
    the first of a documented group's under its `group_comment()`; empty where there is none."""
    return "".join(
        f"{group_comment(h)}pub use ffi::{naming.type_name(api.namespace, t.name)} as {naming.upper_camel(t.name)};\n"
        for h, t in (*headed(api.boxed_scalar_groups), *headed(api.struct_groups))
    )


def enum_blocks(api: Api) -> list[str]:
    """`enum_block()` for each enum in document order, the first of a documented group's
    under its `group_comment()`."""
    return [group_comment(h) + enum_block(t) for h, t in headed(api.typed_const_groups)]


def enum_block(typed: TypedConst) -> str:
    """The enum over its C values, its `TryFrom` from the base type, and with a conversion
    that conversion and a `Display` through it."""
    cls, base = naming.upper_camel(typed.name), typed.base_type
    entries = [(naming.upper_camel(e.name), c.int_literal(e.value, e.format), e) for e in typed.entries]
    variants = "".join(f"{doc_comment(e.docstring, indent=_INDENT)}    {v} = {lit},\n" for v, lit, e in entries)
    arms = "".join(f"            {lit} => Ok({cls}::{v}),\n" for v, lit, _ in entries)
    text = (
        f"{doc_comment(typed.docstring)}#[repr({base})]\n#[derive(Clone, Copy, Debug, PartialEq, Eq)]\n"
        f"pub enum {cls} {{\n{variants}}}\n"
        f"\nimpl core::convert::TryFrom<{base}> for {cls} {{\n    type Error = {base};\n\n"
        f"    fn try_from(raw: {base}) -> core::result::Result<{cls}, {base}> {{\n"
        f"        match raw {{\n{arms}            _ => Err(raw),\n        }}\n    }}\n}}\n"
    )
    if typed.to_string is not None:
        names = "".join(
            f'            {cls}::{v} => "{naming.unprefixed_const_name(e.name)}",\n' for v, _, e in entries
        )
        text += (
            f"\nimpl {cls} {{\n    pub fn {typed.to_string}(self) -> &'static str {{\n"
            f"        match self {{\n{names}        }}\n    }}\n}}\n"
            f"\nimpl core::fmt::Display for {cls} {{\n"
            "    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {\n"
            f"        f.write_str({cls}::{typed.to_string}(*self))\n    }}\n}}\n"
        )
    return text


def type_names(api: Api) -> list[tuple[str, str]]:
    """(where, name) of every enum, boxed scalar and struct, the types `enum_block()` and
    `reexports()` name in UpperCamel at module scope."""
    names = [(f"typed_const.{t.name}", t.name) for t in api.typed_consts]
    names += [(f"boxed_scalar.{b.name}", b.name) for b in api.boxed_scalars]
    names += [(f"struct.{s.name}", s.name) for s in api.structs]
    return names


def camel_names(api: Api) -> list[tuple[str, str]]:
    """(where, name) of every name `enum_block()` and `reexports()` render in UpperCamel:
    `type_names()` and each enum entry."""
    entries = [(f"typed_const.{t.name}.{e.name}", e.name) for t in api.typed_consts for e in t.entries]
    return type_names(api) + entries


def camel_keyword_objections(names: Iterable[tuple[str, str]]) -> list[str]:
    """Each of `names`' (where, name) whose UpperCamel rendering is a Rust keyword the name
    itself is not."""
    return [
        f"{where}: '{name}' renders as '{naming.upper_camel(name)}', a Rust keyword"
        for where, name in names
        if naming.upper_camel(name) in RUST_KEYWORDS and name not in RUST_KEYWORDS
    ]


def enum_conversion_names(api: Api) -> list[tuple[str, str]]:
    """(where, name) of each enum's `_to_string` conversion, a method `enum_block()`
    renders where rustc's `non_snake_case` reaches it."""
    return [(f"typed_const.{t.name}._to_string", t.to_string) for t in api.typed_consts if t.to_string is not None]


def prelude_names(names: Iterable[str] = PRELUDE_NAMES) -> list[tuple[str, str]]:
    """(definer, name) of each of the prelude's `names`, for a module-scope duplicate check."""
    return [("the Rust prelude", name) for name in names]


def module_names(api: Api) -> list[tuple[str, str]]:
    """(where, name) of what `enum_block()` and `reexports()` define at module scope."""
    return [(where, naming.upper_camel(name)) for where, name in type_names(api)]


def enum_member_objections(api: Api) -> list[str]:
    """A name `enum_block()` would define twice in one enum: an entry, `try_from`, its
    conversion."""
    objections = []
    for t in api.typed_consts:
        members = [(f"typed_const.{t.name}.{e.name}", naming.upper_camel(e.name)) for e in t.entries]
        members.append(("the generated TryFrom conversion", "try_from"))
        if t.to_string is not None:
            members.append((f"typed_const.{t.name}._to_string", t.to_string))
        objections += duplicate_objections(members, f"enum {naming.upper_camel(t.name)}")
    return objections


def enum_alias(api: Api, typed: TypedConst) -> str:
    """An enum's C name aliasing its base type, under its docstring: the FFI's enum type."""
    return f"{doc_comment(typed.docstring)}pub type {naming.type_name(api.namespace, typed.name)} = {typed.base_type};\n"


def version_constant(api: Api, *, prefixed: bool) -> str:
    """The version as a `u32` constant, its four bytes as eight hex digits."""
    return f"pub const {_const_name(api, naming.VERSION_KEY, prefixed=prefixed)}: u32 = 0x{api.version_value():08x};\n"


def constant_group(api: Api, group: Group[BitConst] | Group[EnumEntry], *, prefixed: bool) -> str:
    """A bit or plain group as one `pub const` per entry under its docstring, typed by the
    group's base type, C-named or with `prefixed` false unprefixed: a single bit as 1
    shifted, a composed entry as its terms joined by `|` in a bit group and `+` in a plain
    one, a literal spelled per its format with the sign in front."""
    lines = []
    for e in group.entries:
        if e.parts:
            operator = "|" if isinstance(e, BitConst) else "+"
            value = _sum(api, e.parts, operator=operator, prefixed=prefixed)
        elif isinstance(e, BitConst):
            value = f"1 << {e.bit}"
        else:
            value = c.int_literal(e.value, e.format)
        name = _const_name(api, e.name, prefixed=prefixed)
        lines.append(f"{doc_comment(e.docstring)}pub const {name}: {group.base_type} = {value};\n")
    return group_comment(group.docstring) + "".join(lines)


def string_group(api: Api, group: Group[StringConst], *, prefixed: bool) -> str:
    """A string group as one `pub const ...: &str` per entry under its docstring."""
    return group_comment(group.docstring) + "".join(
        f'{doc_comment(s.docstring)}pub const {_const_name(api, s.name, prefixed=prefixed)}: &str = "{s.value}";\n'
        for s in group.entries
    )


def type_definitions(api: Api) -> list[str]:
    """One block per opaque ref (its pointer alias and the struct it points to), boxed
    scalar (a transparent newtype) and struct, at the C header's ABI, in that order, the first
    of a documented group's under its `group_comment()`."""
    ns = api.namespace
    boxed_derive = "#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]\n"
    struct_derive = "#[derive(Clone, Copy, Debug, Default, PartialEq)]\n"
    blocks = [
        f"{group_comment(h)}{doc_comment(o.docstring)}"
        f"pub type {naming.type_name(ns, o.name)} = *mut {naming.opaque_struct(ns, o.name)};\n"
        f"#[repr(C)]\npub struct {naming.opaque_struct(ns, o.name)} {{\n    _private: [u8; 0],\n}}\n"
        for h, o in headed(api.opaque_ref_groups)
    ]
    blocks += [
        f"{group_comment(h)}{doc_comment(b.docstring)}#[repr(transparent)]\n{boxed_derive}"
        f"pub struct {naming.type_name(ns, b.name)}(pub {b.base_type});\n"
        for h, b in headed(api.boxed_scalar_groups)
    ]
    blocks += [
        f"{group_comment(h)}{doc_comment(s.docstring)}#[repr(C)]\n{struct_derive}"
        f"pub struct {naming.type_name(ns, s.name)} {{\n"
        + "".join(
            f"{doc_comment(f.docstring, indent='    ')}    pub {f.name}: {rust_type(api, f.type)},\n"
            for f in s.fields
        )
        + "}\n"
        for h, s in headed(api.struct_groups)
    ]
    return blocks


def _indented(text: str, indent: str) -> str:
    return "".join(indent + line if line.strip() else line for line in text.splitlines(keepends=True))


def _const_name(api: Api, key: str, *, prefixed: bool) -> str:
    return naming.const_name(api.namespace, key) if prefixed else naming.unprefixed_const_name(key)


def _sum(api: Api, parts: tuple[Term, ...], *, operator: str, prefixed: bool) -> str:
    """A composed entry's value, symbolic and unparenthesised: Rust's unary minus binds
    tighter than `+` and `|`, so a negative literal term needs none."""
    return f" {operator} ".join(
        c.int_literal(p.value, p.format) if isinstance(p, LiteralTerm) else _const_name(api, p, prefixed=prefixed)
        for p in parts
    )
