"""Load, validate and normalise an .adef.toml API definition.

Parameter and field order is document order. The loader relies on `tomllib`
building insertion-ordered dicts, so iterating a table yields its keys in the
order they appear in the file.
"""

import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from api_gen import naming

RESERVED_KEYS = frozenset({"docstring", "return"})
RESERVED_NAMES = frozenset(
    (
        # C
        "auto break case char const continue default do double else enum extern float for goto if "
        "inline int long register restrict return short signed sizeof static struct switch typedef "
        "union unsigned void volatile while "
        # C++
        "alignas alignof and_eq asm bitand bitor bool catch char8_t char16_t char32_t class compl "
        "concept consteval constexpr constinit const_cast co_await co_return co_yield decltype "
        "delete dynamic_cast explicit export false friend mutable namespace new noexcept not not_eq "
        "nullptr operator or_eq private protected public reinterpret_cast requires static_assert "
        "static_cast template this thread_local throw true try typeid typename using virtual "
        "wchar_t xor xor_eq "
        # Lua
        "and break do else elseif end false for function goto if in local nil not or repeat return "
        "then true until while"
    ).split()
)
# Names the generated Lua binds as locals beside a function's parameters. Other names
# never share a scope with them, so an enum may be called `result`.
GENERATED_LOCALS = frozenset({"self", "result", "lib", "M", "ffi", "indent"})
BUILTIN_TYPES = frozenset({"u32", "u64", "memory"})
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_INT32_MIN, _INT32_MAX = -(2**31), 2**31 - 1
FORMATS = ("dec", "hex")


class DefinitionError(Exception):
    """The definition cannot be turned into an API."""


@dataclass(frozen=True)
class BitConst:
    key: str
    bit: int | None  # set for a single bit
    parts: tuple[str, ...]  # set for a mask composed of earlier entries
    docstring: str | None
    format: str  # one of FORMATS: how a literal of the value is spelled


@dataclass(frozen=True)
class EnumEntry:
    key: str
    value: int
    docstring: str | None
    format: str  # one of FORMATS


@dataclass(frozen=True)
class StringConst:
    key: str
    value: str  # holds no '"', '\' or newline, so it is a valid C and Lua literal as-is
    docstring: str | None


@dataclass(frozen=True)
class TypedConst:
    name: str
    entries: tuple[EnumEntry, ...]
    docstring: str | None


@dataclass(frozen=True)
class OpaqueRef:
    name: str
    docstring: str | None
    ctor: str | None  # function with exactly one outref of this type
    dtor: str | None  # function taking only this type by value; set only with ctor
    class_name: str  # an identifier as the definition writes it; each binding applies its own idiom


@dataclass(frozen=True)
class Field:
    name: str
    type: str
    docstring: str | None


@dataclass(frozen=True)
class Struct:
    name: str
    fields: tuple[Field, ...]
    docstring: str | None


@dataclass(frozen=True)
class Param:
    name: str
    type: str
    outref: bool
    inref: bool
    nullsafe: bool
    size: str | None  # memory only: the sibling parameter holding the byte count
    docstring: str | None


@dataclass(frozen=True)
class Function:
    name: str
    returns: str
    params: tuple[Param, ...]
    docstring: str | None

    def docs(self) -> list[str]:
        """The function's docstring, if any, followed by each parameter's as `name: text`."""
        docs = [self.docstring] if self.docstring else []
        docs += [f"{p.name}: {p.docstring}" for p in self.params if p.docstring]
        return docs


@dataclass(frozen=True)
class DriverData:
    header: str  # relative to the exercises directory
    const_pins: tuple[tuple[str, str], ...]  # (untyped_bit_const key, driver macro)


@dataclass(frozen=True)
class Api:
    namespace: str
    version: tuple[int, int, int, int]
    library: str | None
    bit_consts: tuple[BitConst, ...]
    consts: tuple[EnumEntry, ...]  # [untyped_const]: an enum entry's shape, without the enum
    string_consts: tuple[StringConst, ...]
    typed_consts: tuple[TypedConst, ...]
    opaque_refs: tuple[OpaqueRef, ...]
    structs: tuple[Struct, ...]
    functions: tuple[Function, ...]
    driver_data: DriverData | None

    def kind(self, type_name: str) -> str:
        """One of "builtin", "enum", "opaque", "struct" for a validated type name."""
        if type_name in BUILTIN_TYPES:
            return "builtin"
        if any(t.name == type_name for t in self.typed_consts):
            return "enum"
        if any(o.name == type_name for o in self.opaque_refs):
            return "opaque"
        if any(s.name == type_name for s in self.structs):
            return "struct"
        raise KeyError(type_name)

    def version_value(self) -> int:
        """The version packed into one 32-bit value, most-significant byte first."""
        shifts = (24, 16, 8, 0)
        return sum(b << s for b, s in zip(self.version, shifts))


def load(path: Path) -> Api:
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise DefinitionError(str(e)) from e
    return from_dict(data)


def from_dict(data: Mapping) -> Api:
    general = data.get("general")
    if not isinstance(general, dict):
        raise DefinitionError("missing [general] table")
    if "name" in general:
        raise DefinitionError("general: unknown key name (the definition's file name is the output stem)")
    _reject_unknown(general, {"namespace", "version", "library"}, "general")

    namespace = general.get("namespace")
    if not isinstance(namespace, str) or not _IDENTIFIER.match(namespace):
        raise DefinitionError("general.namespace must be an identifier string")
    _identifier(namespace, "general.namespace")
    version = general.get("version")
    if not (
        isinstance(version, list)
        and len(version) == 4
        and all(_is_int(v) and 0 <= v <= 255 for v in version)
    ):
        raise DefinitionError("general.version must be a list of 4 integers in 0..255")
    if version[0] > 127:
        raise DefinitionError("general.version: first byte must be 0..127 (enumerators must fit int)")
    library = general.get("library")
    if library is not None and not isinstance(library, str):
        raise DefinitionError("general.library must be a string")
    if library is not None:
        _quote_free(library, "general.library")

    bit_consts = _bit_consts(_table(data, "untyped_bit_const"))
    consts = tuple(
        _int_entry(key, entry, f"untyped_const.{key}") for key, entry in _table(data, "untyped_const").items()
    )
    string_consts = tuple(
        _string_const(key, entry) for key, entry in _table(data, "string_const").items()
    )
    typed_consts = tuple(
        _typed_const(name, body)
        for name, body in _named_tables(_table(data, "typed_const"), "typed_const")
    )
    opaque_refs = [
        _opaque_ref(name, body) for name, body in _named_tables(_table(data, "opaque_ref"), "opaque_ref")
    ]
    struct_tables = _named_tables(_table(data, "struct"), "struct")

    type_names: dict[str, str] = {}
    for category, names in (
        ("typed_const", [t.name for t in typed_consts]),
        ("opaque_ref", [o.name for o in opaque_refs]),
        ("struct", [name for name, _ in struct_tables]),
    ):
        for name in names:
            if name in BUILTIN_TYPES:
                raise DefinitionError(f"{category}.{name}: shadows builtin type {name}")
            if name in type_names:
                raise DefinitionError(
                    f"{category}.{name}: type name already defined in {type_names[name]}"
                )
            type_names[name] = category

    structs: list[Struct] = []
    for name, body in struct_tables:
        structs.append(_struct(name, body, type_names, defined_structs={s.name for s in structs}))

    enums = {t.name: t for t in typed_consts}
    functions = tuple(
        _function(name, body, type_names, enums)
        for name, body in _named_tables(_table(data, "function"), "function")
    )
    _check_lifecycles(opaque_refs, {f.name: f for f in functions})

    api = Api(
        namespace=namespace,
        version=tuple(version),
        library=library,
        bit_consts=bit_consts,
        consts=consts,
        string_consts=string_consts,
        typed_consts=typed_consts,
        opaque_refs=tuple(opaque_refs),
        structs=tuple(structs),
        functions=functions,
        driver_data=_driver_data(data.get("driver_data"), {c.key for c in bit_consts}),
    )
    _check_unique_identifiers(api)
    return api


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _identifier(name: str, where: str, *, reserved: frozenset[str] = RESERVED_NAMES) -> str:
    if name in RESERVED_KEYS:
        raise DefinitionError(f"{where}: '{name}' is a reserved key, not a member name")
    if not _IDENTIFIER.match(name):
        raise DefinitionError(f"{where}: '{name}' is not an identifier")
    if name in reserved:
        raise DefinitionError(f"{where}: '{name}' is a C, C++ or Lua keyword or a name the generated code binds")
    return name


def _quote_free(value: str, where: str) -> None:
    """For a string emitted inside a C or Lua string literal."""
    if '"' in value or "\\" in value:
        raise DefinitionError(f"{where} must not contain '\"' or '\\'")


def _table(data: Mapping, key: str) -> dict:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise DefinitionError(f"[{key}] must be a table")
    return value


def _named_tables(table: dict, category: str) -> list[tuple[str, dict]]:
    result = []
    for name, body in table.items():
        where = f"{category}.{name}"
        _identifier(name, where)
        if not isinstance(body, dict):
            raise DefinitionError(f"{where} must be a table")
        result.append((name, body))
    return result


def _docstring(body: Mapping, where: str) -> str | None:
    doc = body.get("docstring")
    if doc is None:
        return None
    if not isinstance(doc, str):
        raise DefinitionError(f"{where}.docstring must be a string")
    if "*/" in doc or "]]" in doc:
        raise DefinitionError(f"{where}.docstring must not contain '*/' or ']]'")
    return doc


def _reject_unknown(body: Mapping, allowed: set[str], where: str) -> None:
    unknown = sorted(set(body) - allowed)
    if unknown:
        raise DefinitionError(f"{where}: unknown key(s) {', '.join(unknown)}")


def _format(attrs: Mapping, where: str) -> str:
    value = attrs.get("format", "dec")
    if value not in FORMATS:
        raise DefinitionError(f"{where}.format must be one of {', '.join(FORMATS)}")
    return value


def _unwrap_value(entry: object, where: str) -> tuple[object, str | None, str]:
    """Split a bare value or a { value, docstring, format } table into (value, docstring, format)."""
    if not isinstance(entry, dict):
        return entry, None, "dec"
    _reject_unknown(entry, {"value", "docstring", "format"}, where)
    return entry.get("value"), _docstring(entry, where), _format(entry, where)


def _bit_consts(table: dict) -> tuple[BitConst, ...]:
    consts: list[BitConst] = []
    for key, entry in table.items():
        where = f"untyped_bit_const.{key}"
        _identifier(key, where)
        entry, doc, fmt = _unwrap_value(entry, where)
        if _is_int(entry):
            if not 0 <= entry <= 30:
                raise DefinitionError(f"{where}: bit index must be 0..30 (enumerators must fit int)")
            consts.append(BitConst(key, entry, (), doc, fmt))
        elif isinstance(entry, list) and entry and all(isinstance(p, str) for p in entry):
            defined = {c.key for c in consts}
            for part in entry:
                if part not in defined:
                    raise DefinitionError(
                        f"{where}: composes unknown constant '{part}' "
                        "(only earlier untyped_bit_const entries)"
                    )
            consts.append(BitConst(key, None, tuple(entry), doc, fmt))
        else:
            raise DefinitionError(
                f"{where}: must be a bit index, a non-empty list of constant names, "
                "or {value=..., docstring=...}"
            )
    return tuple(consts)


def _int_entry(key: str, entry: object, where: str) -> EnumEntry:
    _identifier(key, where)
    value, doc, fmt = _unwrap_value(entry, where)
    if not _is_int(value) or not _INT32_MIN <= value <= _INT32_MAX:
        raise DefinitionError(f"{where}: value must be an integer in the int32 range")
    return EnumEntry(key, value, doc, fmt)


def _string_const(key: str, entry: object) -> StringConst:
    where = f"string_const.{key}"
    _identifier(key, where)
    doc = None
    if isinstance(entry, dict):
        _reject_unknown(entry, {"value", "docstring"}, where)
        entry, doc = entry.get("value"), _docstring(entry, where)
    if not isinstance(entry, str):
        raise DefinitionError(f"{where}: must be a string or {{value=..., docstring=...}}")
    if any(c in entry for c in '"\\\n'):
        raise DefinitionError(f"{where}: value must not contain '\"', '\\' or a newline")
    return StringConst(key, entry, doc)


def _typed_const(name: str, body: dict) -> TypedConst:
    entries = [
        _int_entry(key, entry, f"typed_const.{name}.{key}")
        for key, entry in body.items()
        if key != "docstring"
    ]
    if not entries:
        raise DefinitionError(f"typed_const.{name}: has no entries")
    return TypedConst(name, tuple(entries), _docstring(body, f"typed_const.{name}"))


def _opaque_ref(name: str, body: dict) -> OpaqueRef:
    where = f"opaque_ref.{name}"
    _reject_unknown(body, {"docstring", "ctor", "dtor", "class"}, where)
    for key in ("ctor", "dtor"):
        if not isinstance(body.get(key, ""), str):
            raise DefinitionError(f"{where}.{key} must be a function name")
    class_name = body.get("class", name)
    if not isinstance(class_name, str) or not _IDENTIFIER.match(class_name):
        raise DefinitionError(f"{where}.class must be an identifier")
    _identifier(class_name, f"{where}.class")
    return OpaqueRef(name, _docstring(body, where), body.get("ctor"), body.get("dtor"), class_name)


def _check_lifecycles(opaque_refs: list[OpaqueRef], functions: Mapping[str, Function]) -> None:
    classes: dict[str, str] = {}
    for o in opaque_refs:
        where = f"opaque_ref.{o.name}"
        if o.dtor is not None and o.ctor is None:
            raise DefinitionError(f"{where}.dtor: requires ctor")
        if o.ctor is None:
            continue
        ctor = functions.get(o.ctor)
        if ctor is None or sum(p.type == o.name and p.outref for p in ctor.params) != 1:
            raise DefinitionError(
                f"{where}.ctor: '{o.ctor}' must name a function with exactly one {o.name} outref"
            )
        memory = next((p for p in ctor.params if p.outref and p.type == "memory"), None)
        if memory is not None:
            raise DefinitionError(
                f"{where}.ctor: function.{ctor.name}.{memory.name}: a constructor cannot cache a memory outref"
            )
        if o.dtor is not None:
            dtor = functions.get(o.dtor)
            if dtor is None or [(p.type, p.outref, p.inref) for p in dtor.params] != [(o.name, False, False)]:
                raise DefinitionError(
                    f"{where}.dtor: '{o.dtor}' must name a function whose only parameter is a {o.name} by value"
                )
        class_name = naming.upper_camel(o.class_name)
        if class_name in classes:
            raise DefinitionError(f"{where}.class: {class_name} is already the class of opaque_ref.{classes[class_name]}")
        classes[class_name] = o.name


def _member_type(entry: object, where: str) -> tuple[str, dict]:
    """Split a bare type string or an inline table into (type, attributes)."""
    if isinstance(entry, str):
        return entry, {}
    if isinstance(entry, dict) and isinstance(entry.get("type"), str):
        return entry["type"], entry
    raise DefinitionError(f"{where}: must be a type name or {{type=..., ...}}")


def _check_type(type_name: str, type_names: dict[str, str], where: str) -> None:
    if type_name not in BUILTIN_TYPES and type_name not in type_names:
        raise DefinitionError(f"{where}: unknown type '{type_name}'")


def _struct(name: str, body: dict, type_names: dict[str, str], *, defined_structs: set[str]) -> Struct:
    fields = []
    for key, entry in body.items():
        if key == "docstring":
            continue
        where = f"struct.{name}.{key}"
        _identifier(key, where)
        type_name, attrs = _member_type(entry, where)
        _reject_unknown(attrs, {"type", "docstring"}, where)
        _check_type(type_name, type_names, where)
        if type_name == "memory":
            raise DefinitionError(f"{where}: 'memory' is not a field type")
        if type_names.get(type_name) == "struct" and type_name not in defined_structs:
            raise DefinitionError(f"{where}: struct '{type_name}' must be defined before it is used")
        fields.append(Field(key, type_name, _docstring(attrs, where)))
    if not fields:
        raise DefinitionError(f"struct.{name}: has no fields")
    return Struct(name, tuple(fields), _docstring(body, f"struct.{name}"))


def _flag(attrs: Mapping, key: str, where: str) -> bool:
    value = attrs.get(key, False)
    if not isinstance(value, bool):
        raise DefinitionError(f"{where}.{key} must be true or false")
    return value


def _function(
    name: str, body: dict, type_names: dict[str, str], enums: Mapping[str, TypedConst]
) -> Function:
    where = f"function.{name}"
    returns = body.get("return")
    if not isinstance(returns, str):
        raise DefinitionError(f"{where}: missing 'return' naming a typed_const")
    if returns not in enums:
        raise DefinitionError(f"{where}.return: unknown typed_const '{returns}'")
    if not any(e.value == 0 for e in enums[returns].entries):
        raise DefinitionError(f"{where}.return: typed_const '{returns}' has no zero-valued entry for success")
    params = []
    for key, entry in body.items():
        if key in RESERVED_KEYS:
            continue
        pwhere = f"{where}.{key}"
        _identifier(key, pwhere, reserved=RESERVED_NAMES | GENERATED_LOCALS)
        type_name, attrs = _member_type(entry, pwhere)
        _reject_unknown(attrs, {"type", "outref", "inref", "nullsafe", "size", "docstring"}, pwhere)
        _check_type(type_name, type_names, pwhere)
        outref, inref = _flag(attrs, "outref", pwhere), _flag(attrs, "inref", pwhere)
        if outref and inref:
            raise DefinitionError(f"{pwhere}: outref and inref are exclusive")
        if type_name == "memory" and not (outref or inref):
            raise DefinitionError(f"{pwhere}: a 'memory' parameter must be inref or outref")
        size = attrs.get("size")
        if size is not None and (type_name != "memory" or not isinstance(size, str)):
            raise DefinitionError(f"{pwhere}.size: only a 'memory' parameter names a size parameter")
        if type_name == "memory" and size is None:
            raise DefinitionError(f"{pwhere}: a 'memory' parameter names its 'size' parameter")
        params.append(
            Param(
                key,
                type_name,
                outref,
                inref,
                _flag(attrs, "nullsafe", pwhere),
                size,
                _docstring(attrs, pwhere),
            )
        )
    by_name = {p.name: p for p in params}
    buffer_of: dict[str, str] = {}  # size parameter -> the memory parameter it measures
    for p in params:
        if p.size is None:
            continue
        target = by_name.get(p.size)
        if target is None or target.type not in ("u32", "u64") or target.outref or target.inref:
            raise DefinitionError(
                f"{where}.{p.name}.size: '{p.size}' must name a u32 or u64 parameter "
                "of the same function passed by value"
            )
        if p.size in buffer_of:
            raise DefinitionError(f"{where}.{p.name}.size: '{p.size}' is already the size of '{buffer_of[p.size]}'")
        buffer_of[p.size] = p.name
    return Function(name, returns, tuple(params), _docstring(body, where))


def _driver_data(body: object, bit_keys: set[str]) -> DriverData | None:
    if body is None:
        return None
    if not isinstance(body, dict):
        raise DefinitionError("[driver_data] must be a table")
    _reject_unknown(body, {"header", "const_pins"}, "driver_data")
    header = body.get("header")
    if not isinstance(header, str):
        raise DefinitionError("driver_data.header must be a string")
    _quote_free(header, "driver_data.header")
    pins_table = body.get("const_pins", {})
    if not isinstance(pins_table, dict):
        raise DefinitionError("driver_data.const_pins must be a table")
    pins = []
    for key, macro in pins_table.items():
        where = f"driver_data.const_pins.{key}"
        if key not in bit_keys:
            raise DefinitionError(f"{where}: pins undefined untyped_bit_const '{key}'")
        if not isinstance(macro, str) or not _IDENTIFIER.match(macro):
            raise DefinitionError(f"{where}: must be a driver macro name")
        pins.append((key, macro))
    return DriverData(header, tuple(pins))


def _check_unique_identifiers(api: Api) -> None:
    """Every generated C identifier, constants and declarations alike, is defined once."""
    ns = api.namespace
    seen = {naming.version_const(ns): "the API version constant"}
    keys = [(c.key, f"untyped_bit_const.{c.key}") for c in api.bit_consts]
    keys += [(c.key, f"untyped_const.{c.key}") for c in api.consts]
    keys += [(c.key, f"string_const.{c.key}") for c in api.string_consts]
    keys += [(e.key, f"typed_const.{t.name}.{e.key}") for t in api.typed_consts for e in t.entries]
    for key, where in keys:
        c_name = naming.const_name(ns, key)
        if c_name in seen:
            raise DefinitionError(f"{where}: constant {c_name} already defined by {seen[c_name]}")
        seen[c_name] = where

    idents = [(naming.type_name(ns, t.name), f"typed_const.{t.name}") for t in api.typed_consts]
    for o in api.opaque_refs:
        where = f"opaque_ref.{o.name}"
        idents += [(naming.type_name(ns, o.name), where), (naming.opaque_struct(ns, o.name), where)]
    idents += [(naming.type_name(ns, s.name), f"struct.{s.name}") for s in api.structs]
    idents += [(naming.function_name(ns, f.name), f"function.{f.name}") for f in api.functions]
    for ident, where in idents:
        if ident in seen:
            raise DefinitionError(f"{where}: C identifier {ident} already defined by {seen[ident]}")
        seen[ident] = where
