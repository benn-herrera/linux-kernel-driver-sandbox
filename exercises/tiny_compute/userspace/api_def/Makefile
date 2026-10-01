# enable one of the two setups

# C++ lib impl, varied consumers
# h - pure c header defines ABI stub_cpp stubs (stub only used on initial setup)
# hpp - header only wrapse pure C api
# rs - import module to allow calling C ABI from rust (the app_rs test program)
# lua - FFI binding of C ABI
OUTPUTS := h,stub_cpp,hpp,rs,lua

# Rust impl, varied consumers (the tiny_compute_rs exercise)
# abi_rs defines rust impl C ABI exposure, stub_rs is safe rust lib impl stub (only used to get started)
# h - pure c header for definitions and prototypes, C/C++ will link against abi_rs shared lib
# hpp - header only lib wraps C ABI in h as with C implemented lib
# lua - FFI binding works with C ABI regardless of underlying impl
# rs - import module to allow calling C ABI from rust (the app_rs test program)
#OUTPUTS := abi_rs,stub_rs,h,hpp,lua,rs

include ../../../gen.mk
