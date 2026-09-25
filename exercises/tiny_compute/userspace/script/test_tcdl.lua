#!/usr/bin/luajit

local printf
function printf(f, ...)
    print(string.format(f, ...))
end

-- binding.tcdl_api is generated from api_dev/tcld_api.adef.toml by api_gen
--   see vdev/justfile recipe 'generate'
--   see out/userspace-build/tiny_compute/generated/binding/
local tcdl = require("binding.tcdl_api")
local dev = tcdl.Device.new(0)

if not dev then
    print("Failed instantiating device!")
    os.exit(1)
end

local dev_caps_to_string
function dev_caps_to_string(caps)
    local caps_list = {}
    if bit.band(caps, tcdl.CAP_COMPUTE) ~= 0 then
        caps_list[#caps_list + 1] = "COMPUTE"
        caps = bit.bxor(caps, tcdl.CAP_COMPUTE)
    end
    if bit.band(caps, tcdl.CAP_DMA_READ) ~= 0 then
        caps_list[#caps_list + 1] = "DMA_READ"
        caps = bit.bxor(caps, tcdl.CAP_DMA_READ)
    end
    if bit.band(caps, tcdl.CAP_DMA_WRITE) ~= 0 then
        caps_list[#caps_list + 1] = "DMA_WRITE"
        caps = bit.bxor(caps, tcdl.CAP_DMA_WRITE)
    end
    if caps ~= 0 then
      caps_list[#caps_list + 1] = string.format("0x%x", caps)
    end
    return (#caps_list > 0) and table.concat(caps_list, "|") or "NONE"
end

local dev_info_to_string
function dev_info_to_string(info, indent)
    indent = indent or ""
    return table.concat({
        indent .. "api_version: " .. tostring(info.api_version),
        indent .. "device_idx: " .. tostring(info.device_idx),
        indent .. "dma_buf_size: " .. tostring(info.dma_buf_size),
        indent .. "dma_alignment: " .. tostring(info.dma_alignment),
        indent .. "device_caps: " .. dev_caps_to_string(info.device_caps),
    }, "\n")
end


local result = true
local err, success

local is_alive
print(dev_info_to_string(dev.info))
is_alive, err = dev:check_alive()
result = result and (err == nil) and is_alive
printf("check_alive(): %s err: %s(%s)", is_alive, tcdl.error_to_str(err), err)

local fact
fact, err = dev:compute_factorial(5)
result = result and (err == nil)
printf("compute_factorial(5): %s err: %s(%s)", fact, tcdl.error_to_str(err), err)
result = result and (fact == 5 * 4 * 3 * 2)

if dev.info.dma_buf_size ~= 0 and dev.info.dma_alignment ~= 0 then
    -- binary-safe binding: the string's own length is the transfer size, so it must be aligned
    local test_dma_vals = {}
    for i = 0, dev.info.dma_alignment * 2 - 1 do
        test_dma_vals[#test_dma_vals + 1] = string.format("%x", i % 16)
    end
    local test_dma_str = table.concat(test_dma_vals, "")
    test_dma_vals = nil
    success, err = dev:dma_to_device(0x00, test_dma_str)
    printf("dma_to_device(0x00, \"%s\") -> %s(%s)", test_dma_str, tcdl.error_to_str(err), err)
    result = result and success and err == nil

    success, err = dev:dma_to_device(0x00, "0")
    printf("should fail with ERR_MISALIGNED: dma_to_device(0x00, \"0\") -> %s(%s)", tcdl.error_to_str(err), err)
    result = result and (not success) and err == tcdl.ERR_MISALIGNED

    success, err = dev:dma_to_device(0x01, test_dma_str)
    printf("should fail with ERR_MISALIGNED: dma_to_device(0x01, \"%s\") -> %s(%s)", test_dma_str, tcdl.error_to_str(err), err)
    result = result and (not success) and err == tcdl.ERR_MISALIGNED

    success, err = dev:dma_from_device(0x00, #test_dma_str)
    printf("dma_from_device(0x00, %d) -> %s %s(%s)", #test_dma_str, success, tcdl.error_to_str(err), err)
    result = result and success == test_dma_str and err == nil

    success, err = dev:dma_from_device(0x00, 1)
    printf("should fail with ERR_MISALIGNED: dma_from_device(0x00, 1) -> %s(%s)", tcdl.error_to_str(err), err)
    result = result and (not success) and err == tcdl.ERR_MISALIGNED

    success, err = dev:dma_from_device(0x01, #test_dma_str)
    printf("should fail with ERR_MISALIGNED: dma_from_device(0x01, %d) -> %s(%s)", #test_dma_str, tcdl.error_to_str(err), err)
    result = result and (not success) and err == tcdl.ERR_MISALIGNED
else
    printf("invalid dma_buf_size(%s) and/or dma_alignment(%s) - both must be non-zero.",
        dev.info.dma_buf_size, dev.info.dma_alignment)
    result = false
end

dev:destroy_device()

os.exit(result and 0 or 1)
