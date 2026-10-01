# Rust impl, varied consumers (tiny_compute has the C++ implementation of the same API)
# abi_rs defines rust impl C ABI exposure, stub_rs is safe rust lib impl stub (only used to get started)
# h - pure c header for definitions and prototypes, C/C++ will link against abi_rs shared lib
# hpp - header only lib wraps C ABI in h as with C implemented lib
# lua - FFI binding works with C ABI regardless of underlying impl
# rs - import module to allow calling C ABI from rust (the app_rs test program)
OUTPUTS := abi_rs,stub_rs,h,hpp,lua,rs

include ../../../gen.mk
