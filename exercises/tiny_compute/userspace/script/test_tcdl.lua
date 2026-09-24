#!/usr/bin/luajit
local ffi = require("ffi")

local fhdr, err = io.open("/usr/include/tiny_compute/tcdl_api.h")
if not fhdr then
    error("failed opening tcdl api header file: " .. tostring(err))
end
local api_text = fhdr:read("*a")
fhdr:close()

-- strip preprocessor lines and the API
api_text = api_text:gsub("#[^\n]*\n", ""):gsub("%f[%w_]TCDL_API%f[^%w_]", "")
ffi.cdef(api_text)

-- print(api_text)

local lib_tcd = ffi.load("libtiny_compute.so")

function printf(f, ...)
  print(string.format(f, ...))
end

local TcdlDevice = {
    TCDL_OK = tonumber(ffi.C.TCDL_OK),
    TCDL_ERR_NO_DEVICE = tonumber(ffi.C.TCDL_ERR_NO_DEVICE),
    TCDL_ERR_INVALID_HANDLE = tonumber(ffi.C.TCDL_ERR_INVALID_HANDLE),
    TCDL_ERR_INVALID_ADDRESS = tonumber(ffi.C.TCDL_ERR_INVALID_ADDRESS),
    TCDL_ERR_TIMEDOUT = tonumber(ffi.C.TCDL_ERR_TIMEDOUT),
    TCDL_ERR_DEVICE_DEAD = tonumber(ffi.C.TCDL_ERR_DEVICE_DEAD),
    TCDL_ERR_COMM_FAILED = tonumber(ffi.C.TCDL_ERR_COMM_FAILED),
    TCDL_ERR_UNKNOWN = tonumber(ffi.C.TCDL_ERR_UNKNOWN),
    TCDL_CAP_COMPUTE = tonumber(ffi.C.TCDL_CAP_COMPUTE),
    TCDL_CAP_DMA_READ = tonumber(ffi.C.TCDL_CAP_DMA_READ),
    TCDL_CAP_DMA_WRITE = tonumber(ffi.C.TCDL_CAP_DMA_WRITE),
    TCDL_CAP_DMA_READ_WRITE = tonumber(ffi.C.TCDL_CAP_DMA_READ_WRITE),
}
local error_strings = {}
for k, v in pairs(TcdlDevice) do
    error_strings[v] = k
end
TcdlDevice.TCDL_API_VERSION = tonumber(ffi.C.TCDL_API_VERSION)
TcdlDevice.__index = TcdlDevice

function TcdlDevice.error_to_str(ecode)
  return error_strings[ecode]
end

function TcdlDevice.new(device_idx)
    if device_idx == nil then
        device_idx = 0
    end
    assert(type(device_idx) == "number")
    local pinfo = ffi.new("tcdl_info")
    local phandle = ffi.new("tcdl_handle[1]")
    local result = lib_tcd.tcdl_create_device(device_idx, phandle, pinfo)
    if result ~= TcdlDevice.TCDL_OK then
        return nil, tonumber(result)
    end
    self = setmetatable({}, TcdlDevice)
    self.info = {
        api_version = tonumber(pinfo.api_version),
        device_idx = tonumber(pinfo.device_idx),
        dma_buf_size = pinfo.dma_buf_size,
        dma_alignment = tonumber(pinfo.dma_alignment),
        device_caps = pinfo.device_caps,
    }
    local handle = phandle[0]
    self._handle = ffi.gc(handle, lib_tcd.tcdl_destroy_device)
    return self, nil
end

function TcdlDevice.compute_factorial(self, arg)
    assert(type(arg) == "number")
    local pfact = ffi.new("uint32_t[1]")
    local result = lib_tcd.tcdl_compute_factorial(self._handle, arg, pfact)
    if result ~= TcdlDevice.TCDL_OK then
        return nil, tonumber(result)
    end
    return tonumber(pfact[0]), nil
end

function TcdlDevice.dma_from_device(self, device_offset, count)
    assert(type(device_offset) == "number")
    assert(type(count) == "number")
    local buffer = ffi.new("char[?]", count)
    local result = lib_tcd.tcdl_dma_from_device(self._handle, buffer, device_offset, count)
    if result ~= TcdlDevice.TCDL_OK then
        return nil, tonumber(result)
    end
    return ffi.string(buffer), nil
end

function TcdlDevice.dma_to_device(self, text, device_offset)
    assert(type(text) == "string")
    assert(type(device_offset) == "number")
    local buffer = ffi.new("char[?]", #text + 1, text)
    local result = lib_tcd.tcdl_dma_to_device(self._handle, buffer, device_offset, ffi.sizeof(buffer))
    if result ~= TcdlDevice.TCDL_OK then
        return nil, tonumber(result)
    end
    return true, nil
end

result = true
tcdl_dev = TcdlDevice.new(0)
result = result and (tcdl_dev ~= nil)

for k, v in pairs(tcdl_dev.info) do
  printf("%s: %s", k, tostring(v))
end
fact, err = tcdl_dev:compute_factorial(5)
result = result and (err == nil)
printf("compute_factorial(5): %s err: %s %s", tostring(fact), err, TcdlDevice.error_to_str(err))
result = result and (fact == 5 * 4 * 3 * 2)

test_dma_str = "Daisy, Daisy, give me your answer, do.012345678"
assert((#test_dma_str + 1) % 16 == 0)
success, err = tcdl_dev:dma_to_device(test_dma_str, 0)
result = result and (err == nil)
printf("dma_to_device(%s)(%d bytes): %s err: %s %s", test_dma_str, #test_dma_str + 1, tostring(success), tostring(err), TcdlDevice.error_to_str(err))
text, err = tcdl_dev:dma_from_device(0, #test_dma_str + 1)
result = result and (err == nil)
printf("dma_from_device(0, %d): %s err: %s %s", #test_dma_str + 1, tostring(text), tostring(err), TcdlDevice.error_to_str(err))
result = result and (text == test_dma_str)

tcdl_dev = nil
collectgarbage("collect")

os.exit(result and 0 or 1)
