// AI generated (Claude Opus 5.5 via Claude Code); fate TBD, likely removed and hand re-implemented.
//
// Userspace test of the Tiny Compute Device Library API through its generated Rust binding;
// the same steps as app_cpp/tests.cpp.

// The binding is the whole API; this program uses part of it.
#[allow(dead_code)]
mod tcdl_api {
    include!(concat!(env!("API_GEN_RUST_DIR"), "/tcdl_api.rs"));
}

use std::process::ExitCode;
use tcdl_api::{CAP_COMPUTE, CAP_DMA_READ_WRITE, Device, DmaOffset, OpResult};

type TestResult = Result<(), String>;

fn describe(r: OpResult) -> String {
    format!("{r}({})", r as i32)
}

fn test_info(d: &Device) -> TestResult {
    let info = d.info();
    println!("API version: 0x{:08x}", info.api_version);
    println!("device index: {}", info.device_idx);
    println!("dma buf size: {}", info.dma_buf_size);
    println!("dma alignment: {}", info.dma_alignment);
    println!("capabilitiy flags: 0x{:08x}", info.device_caps);

    if info.api_version == 0
        || info.dma_buf_size == 0
        || info.dma_alignment == 0
        || info.device_caps == 0
    {
        return Err(
            "invalid tcdl_info values. all values besides index expected to be non-zero.".into(),
        );
    }
    Ok(())
}

fn test_compute(d: &Device) -> TestResult {
    const FACT_ARG: u32 = 6;
    const FACT_VAL: u32 = 6 * 5 * 4 * 3 * 2;

    if d.info().device_caps & CAP_COMPUTE == 0 {
        return Err(format!(
            "device cap TCDL_CAP_COMPUTE({CAP_COMPUTE:#x}) expected, but missing."
        ));
    }

    let fact = d
        .compute_factorial(FACT_ARG)
        .map_err(|r| format!("compute_factorial returned error {}", describe(r)))?;

    let success = fact == FACT_VAL;
    println!("factorial({FACT_ARG}): {fact} success: {success}");
    if !success {
        return Err(format!(
            "expected compute factorial({FACT_ARG}) to produce {FACT_VAL}"
        ));
    }
    Ok(())
}

fn test_dma_round_trip(d: &Device) -> TestResult {
    // Either the device's whole buffer or 16 KiB is aligned for this device.
    const MAX_BYTES: usize = 1 << 14;

    let info = d.info();
    if info.device_caps & CAP_DMA_READ_WRITE != CAP_DMA_READ_WRITE {
        return Err("DMA read/write capabilities expected but one or both missing.".into());
    }
    if info.dma_buf_size == 0 || info.dma_alignment == 0 {
        return Err("DMA buf size and alignment both expected to be non-zero.".into());
    }

    let count = usize::try_from(info.dma_buf_size).map_or(MAX_BYTES, |n| n.min(MAX_BYTES))
        / size_of::<u16>();
    // count descending u16 values, ending at 0, in the device's byte order
    let pattern: Vec<u8> = (0..=u16::MAX)
        .take(count)
        .rev()
        .flat_map(u16::to_ne_bytes)
        .collect();

    d.dma_to_device(DmaOffset(0), &pattern)
        .map_err(|r| format!("DMA to device failed with error {}.", describe(r)))?;

    let mut readback = vec![0xff; pattern.len()];
    d.dma_from_device(DmaOffset(0), &mut readback)
        .map_err(|r| format!("DMA from device failed with error {}.", describe(r)))?;

    if readback != pattern {
        return Err("DMA round trip failed - read pattern did not match written.".into());
    }
    println!("DMA round trip succeeded.");
    Ok(())
}

fn create_dev(idx: u32) -> Option<Device> {
    Device::create(idx)
        .inspect_err(|&r| eprintln!("failed creating device: {}.", describe(r)))
        .ok()
}

// A test on a device that failed to open fails; its reason was reported at creation.
fn run(d: Option<&Device>, test: fn(&Device) -> TestResult) -> bool {
    let Some(d) = d else {
        return false;
    };
    match test(d) {
        Ok(()) => true,
        Err(msg) => {
            eprintln!("{msg}");
            false
        }
    }
}

// Expected usage patterns, to see if it works at all. Every test runs whatever failed before it.
fn test_functionality() -> bool {
    let mut result = true;

    println!("*** single continuous session check ***");
    {
        let d = create_dev(0);
        result &= run(d.as_ref(), test_info);
        result &= run(d.as_ref(), test_compute);
        result &= run(d.as_ref(), test_dma_round_trip);
    }
    println!();

    println!("*** separate transactions session check ***");
    for test in [test_info, test_compute, test_dma_round_trip] {
        let d = create_dev(0);
        result &= run(d.as_ref(), test);
    }

    // the second device works at all
    {
        let d = create_dev(1);
        result &= run(d.as_ref(), test_info);
    }

    result
}

fn main() -> ExitCode {
    if test_functionality() {
        ExitCode::SUCCESS
    } else {
        ExitCode::FAILURE
    }
}
