#!/usr/bin/luajit

-- lib_lua/ ships beside this file under /usr/bin; the guest's LUA_PATH resolves it from any cwd
local util = require("lib_lua.util")
local printf = util.printf
local dev_info_to_string = util.dev_info_to_string

-- binding.tcdl_api is generated from api_def/tcdl_api.adef.toml by api_gen
--   see vdev/justfile recipe 'generate'
--   see out/userspace-build/<exercise>/generated/binding/
local tcdl = require("binding.tcdl_api")
local dev = tcdl.Device.new(0)

if not dev then
    print("Failed instantiating device!")
    os.exit(1)
end

local result = true
local err, success

local is_alive
print(dev_info_to_string(dev.info))
is_alive, err = dev:check_alive()
result = result and (err == nil) and is_alive
printf("check_alive(): %s err: %s(%s)", is_alive, tcdl.op_result_to_string(err), err)

local fact
fact, err = dev:compute_factorial(5)
result = result and (err == nil)
printf("compute_factorial(5): %s err: %s(%s)", fact, tcdl.op_result_to_string(err), err)
result = result and (fact == 5 * 4 * 3 * 2)

if dev.info.dma_buf_size ~= 0 and dev.info.dma_alignment ~= 0 then
    -- binary-safe binding: the string's own length is the transfer size, so it must be aligned
    local test_dma_vals = {}
    for i = 0, dev.info.dma_alignment * 2 - 1 do
        test_dma_vals[#test_dma_vals + 1] = string.format("%x", i % 16)
    end
    local test_dma_str = table.concat(test_dma_vals, "")
    local test_misaligned = "0"
    test_dma_vals = nil
    success, err = dev:dma_to_device(0x00, test_dma_str)
    printf("dma_to_device(0x00, \"%s\") -> %s(%s)", test_dma_str, tcdl.op_result_to_string(err), err)
    result = result and success and err == nil

    success, err = dev:dma_to_device(0x00, "0")
    printf("should fail with ERR_MISALIGNED: dma_to_device(0x00, \"%s\") -> %s(%s)", test_misaligned, tcdl.op_result_to_string(err), err)
    result = result and (not success) and err == tcdl.ERR_MISALIGNED

    success, err = dev:dma_to_device(0x01, test_dma_str)
    printf("should fail with ERR_MISALIGNED: dma_to_device(0x01, \"%s\") -> %s(%s)", test_dma_str, tcdl.op_result_to_string(err), err)
    result = result and (not success) and err == tcdl.ERR_MISALIGNED

    success, err = dev:dma_from_device(0x00, #test_dma_str)
    printf("dma_from_device(0x00, %d) -> %s %s(%s)", #test_dma_str, success, tcdl.op_result_to_string(err), err)
    result = result and success == test_dma_str and err == nil

    success, err = dev:dma_from_device(0x00, 1)
    printf("should fail with ERR_MISALIGNED: dma_from_device(0x00, %d) -> %s %s(%s)", #test_misaligned, success, tcdl.op_result_to_string(err), err)
    result = result and (not success) and err == tcdl.ERR_MISALIGNED

    success, err = dev:dma_from_device(0x01, #test_dma_str)
    printf("should fail with ERR_MISALIGNED: dma_from_device(0x01, %d) -> %s %s(%s)", #test_dma_str, success, tcdl.op_result_to_string(err), err)
    result = result and (not success) and err == tcdl.ERR_MISALIGNED
else
    printf("invalid dma_buf_size(%s) and/or dma_alignment(%s) - both must be non-zero.",
        dev.info.dma_buf_size, dev.info.dma_alignment)
    result = false
end

dev:destroy_device()

os.exit(result and 0 or 1)
