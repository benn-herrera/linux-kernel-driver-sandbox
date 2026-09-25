"""Target-language names derived from an API namespace and definition keys."""

BUILTIN_C_TYPES = {"u32": "uint32_t", "u64": "uint64_t"}


def type_name(namespace: str, name: str) -> str:
    """C name of an enum, struct, opaque ref or typedef: `tcdl_result`."""
    return f"{namespace}_{name}"


def function_name(namespace: str, name: str) -> str:
    return f"{namespace}_{name}"


def const_name(namespace: str, key: str) -> str:
    """C name of a constant: `TCDL_ERR_NO_DEVICE`."""
    return f"{namespace.upper()}_{key.upper()}"


def version_const(namespace: str) -> str:
    return const_name(namespace, "api_version")


def opaque_struct(namespace: str, name: str) -> str:
    """The incomplete struct an opaque ref points to: `tcdl_handle_opaque`."""
    return f"{namespace}_{name}_opaque"


def c_api_macro(namespace: str) -> str:
    return f"{namespace.upper()}_C_API"


def api_macro(namespace: str) -> str:
    return f"{namespace.upper()}_API"


def impl_macro(namespace: str) -> str:
    return f"{namespace.upper()}_IMPL"


def device_class(namespace: str) -> str:
    """Lua class wrapping the opaque ref: `TcdlDevice`."""
    return "".join(part.capitalize() for part in namespace.split("_")) + "Device"
