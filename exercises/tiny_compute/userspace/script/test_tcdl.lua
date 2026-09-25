#!/usr/bin/luajit

local printf
function printf(f, ...)
    print(string.format(f, ...))
end

local tcdl = require("binding.tcd_lib")
local tcdl_dev = tcdl.TcdlDevice.new(0)

if not tcdl_dev then
    print("Failed instantiating device!")
    os.exit(1)
end

local result = true
local err, success

local is_alive
print(tcdl_dev:get_info_string("  "))
is_alive, err = tcdl_dev:check_alive()
result = result and (err == nil) and is_alive
printf("check_alive(): %s err: %s %s", is_alive, err, tcdl.error_to_str(err))

local fact
fact, err = tcdl_dev:compute_factorial(5)
result = result and (err == nil)
printf("compute_factorial(5): %s err: %s %s", fact, err, tcdl.error_to_str(err))
result = result and (fact == 5 * 4 * 3 * 2)

if tcdl_dev.info.dma_buf_size ~= 0 and tcdl_dev.info.dma_alignment ~= 0 then
    local test_dma_str = "Daisy, Daisy, give me your answer, do.012345678"
    local dma_size = (#test_dma_str + 1)
    local text
    assert(dma_size % tcdl_dev.info.dma_alignment == 0)
    assert(dma_size <= tcdl_dev.info.dma_buf_size)
    success, err = tcdl_dev:dma_to_device(test_dma_str, 0)
    result = result and (err == nil)
    printf("dma_to_device(%s)(%d bytes): %s err: %s %s", test_dma_str, dma_size, success, err, tcdl.error_to_str(err))
    text, err = tcdl_dev:dma_from_device(0, dma_size)
    result = result and (err == nil)
    printf("dma_from_device(0, %d): %s err: %s %s", dma_size, text, err, tcdl.error_to_str(err))
    result = result and (text == test_dma_str)
else
  printf("invalid dma_buf_size(%s) and/or dma_alignment(%s) - both must be non-zero.",
    tcdl_dev.info.dma_buf_size, tcdl_dev.info.dma_alignment)
    result = false
end

tcdl_dev = nil
collectgarbage("collect")

os.exit(result and 0 or 1)
