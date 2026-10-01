// AI generated (Claude Opus 5.5 via Claude Code); fate TBD, likely removed and hand re-implemented.
//
// Points the linker at the directory holding libtiny_compute_rs.so; the binding's
// #[link(name = "tiny_compute_rs")] names the library itself.
use std::env;
use std::process::ExitCode;

const VAR: &str = "API_LIB_DIR";

fn main() -> ExitCode {
    println!("cargo:rerun-if-env-changed={VAR}");
    match env::var(VAR) {
        Ok(dir) => {
            println!("cargo:rustc-link-search=native={dir}");
            ExitCode::SUCCESS
        }
        Err(_) => {
            eprintln!("build.rs: {VAR} is not set; the userspace recipe supplies it");
            ExitCode::FAILURE
        }
    }
}
