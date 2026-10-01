"""Target-language names derived from an API namespace and definition names."""

import re
from dataclasses import dataclass

# Every builtin scalar type and its C spelling: the one map the model and every emitter read.
BUILTIN_C_TYPES = {
    "i8": "int8_t", "u8": "uint8_t", "i16": "int16_t", "u16": "uint16_t",
    "i32": "int32_t", "u32": "uint32_t", "i64": "int64_t", "u64": "uint64_t",
    "f32": "float", "f64": "double",
}


@dataclass(frozen=True)
class BaseCType:
    c_type: str  # the fixed-width C type
    const_macro: str  # the <stdint.h> macro that gives an integer literal that type
    min_value: int  # the least value the type holds
    max_value: int  # the greatest value the type holds


# A constant group's or enum's `_base_type`, first the default, and its C spellings and range.
BASE_C_TYPES = {
    "i32": BaseCType("int32_t", "INT32_C", -(2**31), 2**31 - 1),
    "u32": BaseCType("uint32_t", "UINT32_C", 0, 2**32 - 1),
}
VERSION_KEY = "api_version"
_RUST_LINKABLE = re.compile(r"lib([^/\s]+)\.so")


def type_name(namespace: str, name: str) -> str:
    """C name of an enum, struct, opaque ref or typedef: `tcdl_result`."""
    return f"{namespace}_{name}"


def function_name(namespace: str, name: str) -> str:
    """C name of a function: `tcdl_create_device`."""
    return f"{namespace}_{name}"


def count_param(name: str) -> str:
    """The byte-count parameter a `memory` parameter expands to beside itself: `psrc_count`."""
    return f"{name}_count"


def const_name(namespace: str, name: str) -> str:
    """C name of a constant: `TCDL_ERR_NO_DEVICE`."""
    return f"{namespace.upper()}_{name.upper()}"


def unprefixed_const_name(name: str) -> str:
    """A constant's name with no namespace prefix, the rule the Lua module (whose module
    table is the namespace) and the C++ wrapper (whose C++ namespace already is) share:
    `ERR_NO_DEVICE`."""
    return name.upper()


def lua_to_string(name: str, *, typename: str | None) -> str:
    """The Lua module's name for a `_to_string` conversion: an enum's is prefixed with its
    type name, since Lua has no overloading (`result_to_string`); a nameless group's is
    `name` as-is. C++ uses `name` as-is for both, overloading an enum's on its type."""
    return name if typename is None else f"{typename}_{name}"


def lua_lookup_table(conversion: str) -> str:
    """The module-local table a Lua lookup conversion reads, from the conversion's Lua
    name: `status_to_string_names`."""
    return f"{conversion}_names"


def cpp_member(name: str) -> str:
    """The C++ wrapper's private data member holding the value `name`: `info_`."""
    return f"{name}_"


def rust_raw_local(name: str) -> str:
    """The Rust binding's local holding an enum parameter `name` as its base integer for
    the C call: `mode_raw`."""
    return f"{name}_raw"


def rust_local(name: str) -> str:
    """The Rust relay's local holding what a pointer parameter `name` reaches the
    implementation through: `pstats_local`."""
    return f"{name}_local"


def rust_link_name(library: str) -> str | None:
    """The name `#[link(name = ...)]` gives the Rust binding's library, `libxy.so` -> `xy`,
    since the linker searches for `lib<name>.so`; `None` for a file name not of that form,
    a `/` or whitespace in `<name>` included."""
    match = _RUST_LINKABLE.fullmatch(library)
    return None if match is None else match.group(1)


def unknown_value_name(typename: str | None) -> str:
    """What a conversion returns for a value no entry has: `UNKNOWN_RESULT` for an enum,
    `UNKNOWN` for a nameless group."""
    return "UNKNOWN" if typename is None else f"UNKNOWN_{typename.upper()}"


# What a bit group's conversion returns for zero.
NO_FLAGS = "NONE"


def version_const(namespace: str) -> str:
    """C name of the version constant: `TCDL_API_VERSION`."""
    return const_name(namespace, VERSION_KEY)


def opaque_struct(namespace: str, name: str) -> str:
    """The incomplete struct an opaque ref points to: `tcdl_handle_opaque`."""
    return f"{namespace}_{name}_opaque"


def c_api_macro(namespace: str) -> str:
    """The header's linkage macro, `extern "C"` under C++: `TCDL_C_API`."""
    return f"{namespace.upper()}_C_API"


def api_macro(namespace: str) -> str:
    """The macro before each function declaration, adding visibility for the implementation: `TCDL_API`."""
    return f"{namespace.upper()}_API"


def impl_macro(namespace: str) -> str:
    """The macro the implementation defines before including the header: `TCDL_IMPL`."""
    return f"{namespace.upper()}_IMPL"


def upper_camel(name: str) -> str:
    """`my_ns` -> `MyNs`."""
    return "".join(part.capitalize() for part in name.split("_"))
