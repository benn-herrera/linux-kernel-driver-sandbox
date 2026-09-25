"""Target-language names derived from an API namespace and definition keys."""

BUILTIN_C_TYPES = {"u32": "uint32_t", "u64": "uint64_t"}
VERSION_KEY = "api_version"


def type_name(namespace: str, name: str) -> str:
    """C name of an enum, struct, opaque ref or typedef: `tcdl_result`."""
    return f"{namespace}_{name}"


def function_name(namespace: str, name: str) -> str:
    return f"{namespace}_{name}"


def const_name(namespace: str, key: str) -> str:
    """C name of a constant: `TCDL_ERR_NO_DEVICE`."""
    return f"{namespace.upper()}_{key.upper()}"


def lua_const_name(key: str) -> str:
    """Lua name of a constant, the module being the namespace: `ERR_NO_DEVICE`."""
    return key.upper()


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
