// AI generated (Claude Fable 5.1 via Claude Code); fate TBD, likely removed and hand re-implemented.
//
// Renders the driver's UAPI header with the bindgen CLI into OUT_DIR/wrapped_api.rs, with
// <errno.h> and <fcntl.h> so the errno values and open flags the library uses come from the
// system headers.
// The TCD_IOC_* requests are function-like macro expansions bindgen cannot evaluate, so the
// wrapper restates each as an enumerator (`<macro>_REQ`) whose initialiser clang evaluates.
use std::env;
use std::fs;
use std::path::PathBuf;
use std::process::{Command, ExitCode};

const HEADER: &str = "tiny_compute_rs/driver/tcd_ioctl.h";
const IOCTLS: [&str; 5] = [
    "TCD_IOC_INFO",
    "TCD_IOC_LIVENESS",
    "TCD_IOC_COMPUTE",
    "TCD_IOC_DMA_FROM_DEVICE",
    "TCD_IOC_DMA_TO_DEVICE",
];

fn var(name: &str) -> Result<String, String> {
    println!("cargo:rerun-if-env-changed={name}");
    env::var(name).map_err(|_| format!("{name} is not set; the userspace recipe supplies it"))
}

fn run() -> Result<(), String> {
    let out_dir = PathBuf::from(var("OUT_DIR")?);
    let driver_include = var("DRIVER_INCLUDE")?;
    let api_gen_rust_dir = var("API_GEN_RUST_DIR")?;

    println!("cargo:rerun-if-changed={driver_include}/{HEADER}");
    println!("cargo:rerun-if-changed={api_gen_rust_dir}/tcdl_api_abi.rs");
    println!("cargo:rustc-cdylib-link-arg=-Wl,-soname,libtiny_compute_rs.so");

    let mut source = format!(
        "#include <errno.h>\n#include <fcntl.h>\n#include \"{HEADER}\"\n\nenum tcd_ioc_req {{\n"
    );
    for m in IOCTLS {
        source += &format!("\t{m}_REQ = {m},\n");
    }
    source += "};\n";
    let wrapper = out_dir.join("wrapper.h");
    fs::write(&wrapper, source).map_err(|e| format!("writing {}: {e}", wrapper.display()))?;

    let wrapped_api_rs = out_dir.join("wrapped_api.rs");
    let status = Command::new("bindgen")
        .arg(&wrapper)
        .args(["--no-prepend-enum-name", "-o"])
        .arg(&wrapped_api_rs)
        .arg("--")
        .arg(format!("-I{driver_include}"))
        .status()
        .map_err(|e| format!("running bindgen: {e}"))?;
    if !status.success() {
        return Err(format!(
            "bindgen failed ({status}) on {}",
            wrapper.display()
        ));
    }
    Ok(())
}

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("build.rs: {e}");
            ExitCode::FAILURE
        }
    }
}
