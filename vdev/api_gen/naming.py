"""Target-language names derived from an API namespace and definition names."""

# Every builtin scalar type and its C spelling, which the C++ wrapper and the Lua FFI share.
BUILTIN_C_TYPES = {
    "i8": "int8_t", "u8": "uint8_t", "i16": "int16_t", "u16": "uint16_t",
    "i32": "int32_t", "u32": "uint32_t", "i64": "int64_t", "u64": "uint64_t",
    "f32": "float", "f64": "double",
}
# A constant group's or enum's `_base_type`, first the default, and its fixed-width C spelling.
BASE_C_TYPES = {"i32": "int32_t", "u32": "uint32_t"}
VERSION_KEY = "api_version"


def type_name(namespace: str, name: str) -> str:
    """C name of an enum, struct, opaque ref or typedef: `tcdl_result`."""
    return f"{namespace}_{name}"


def function_name(namespace: str, name: str) -> str:
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


def version_const(namespace: str) -> str:
    return const_name(namespace, VERSION_KEY)


def opaque_struct(namespace: str, name: str) -> str:
    """The incomplete struct an opaque ref points to: `tcdl_handle_opaque`."""
    return f"{namespace}_{name}_opaque"


def c_api_macro(namespace: str) -> str:
    return f"{namespace.upper()}_C_API"


def api_macro(namespace: str) -> str:
    return f"{namespace.upper()}_API"


def impl_macro(namespace: str) -> str:
    return f"{namespace.upper()}_IMPL"


def upper_camel(name: str) -> str:
    """`my_ns` -> `MyNs`."""
    return "".join(part.capitalize() for part in name.split("_"))
