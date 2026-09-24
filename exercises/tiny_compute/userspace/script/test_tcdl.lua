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

local TcdlDevice = {
    TCDL_OK = ffi.C.TCDL_OK,
    TCDL_ERR_NO_DEVICE = ffi.C.TCDL_ERR_NO_DEVICE,
    TCDL_ERR_INVALID_HANDLE = ffi.C.TCDL_ERR_INVALID_HANDLE,
    TCDL_ERR_INVALID_ADDRESS = ffi.C.TCDL_ERR_INVALID_ADDRESS,
    TCDL_ERR_TIMEDOUT = ffi.C.TCDL_ERR_TIMEDOUT,
    TCDL_ERR_DEVICE_DEAD = ffi.C.TCDL_ERR_DEVICE_DEAD,
    TCDL_ERR_COMM_FAILED = ffi.C.TCDL_ERR_COMM_FAILED,
    TCDL_ERR_UNKNOWN = ffi.C.TCDL_ERR_UNKNOWN,
    TCDL_CAP_COMPUTE = ffi.C.TCDL_CAP_COMPUTE,
    TCDL_CAP_DMA_READ = ffi.C.TCDL_CAP_DMA_READ,
    TCDL_CAP_DMA_WRITE = ffi.C.TCDL_CAP_DMA_WRITE,
    TCDL_CAP_DMA_READ_WRITE = ffi.C.TCDL_CAP_DMA_READ_WRITE,
}
local error_strings = {}
for k, v in pairs(TcdlDevice) do
    error_strings[v] = k
end
TcdlDevice.TCDL_API_VERSION = ffi.C.TCDL_API_VERSION
TcdlDevice.__index = TcdlDevice

function TcdlDevice.error_to_str(ecode)
  return error_strings[ecode]
end

function TcdlDevice.new(device_idx)
    if device_idx == nil then
      device_idx = 0
    end
    local pinfo = ffi.new("tcdl_info")
    local phandle = ffi.new("tcdl_handle[1]")
    local result = lib_tcd.tcdl_create_device(device_idx, phandle, pinfo)
    if result ~= TcdlDevice.TCDL_OK then
        return nil, TcdlDevice.error_to_str(result)
    end
    self = setmetatable({}, TcdlDevice)
    self.info = {
        api_version = pinfo.api_version,
        device_idx = pinfo.device_idx,
        dma_buf_size = pinfo.dma_buf_size,
        dma_alignment = pinfo.dma_alignment,
        device_caps = pinfo.device_caps,
    }
    local handle = phandle[0]
    self._handle = ffi.gc(handle, lib_tcd.tcdl_destroy_device)
    return self, nil
end

function TcdlDevice.compute_factorial(self, arg)
    local pfact = ffi.new("uint32_t[1]")
    local result = lib_tcd.tcdl_compute_factorial(self._handle, arg, pfact)
    if result ~= TcdlDevice.TCDL_OK then
        return nil, TcdlDevice.error_to_str(result)
    end
    return tonumber(pfact[0]), nil
end

tcdl_dev = TcdlDevice.new(0)

print(tcdl_dev.info)
print("factorial 5", tcdl_dev:compute_factorial(5))

tcdl_dev = nil
collectgarbage("collect")
