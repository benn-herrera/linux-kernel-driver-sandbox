// A consumer of support.KITCHEN_SINK's Rust binding, run against each fake's libxy.so; the
// binding is xy_api.rs beside this file. consumer_xy.cpp's steps, in its order and with its codes.
// Exit codes: 0 all steps passed; 1 create(99) failure result; 2 create(3) and its cached
// out parameters; 3 send; 4 recv; 5 configure; 6 stats_of; 7 move; 8 move assignment;
// 9 release; 10 drops freed the slots; 11 PRODUCT; 12 DataLink::create; 13 bump; 14 seek and tune;
// 15 annotate (an _optional struct in parameter); 16 the _to_string conversions; 17 probe (an enum out
// parameter as the enum, _optional memory in, scalar in, inout and out parameters); 18 echo_offset (a
// boxed scalar by value and out); 20 an empty optional slice reaches the library as a present,
// zero-length payload. Code 19 belongs to test_compiled.py's unnamed-result program.
#[allow(dead_code)]
mod xy_api;

use std::process::ExitCode;
use xy_api::{DataLink, Mode, Offset, Port, Stats, Status};

// `<T as NotClone<_>>::check` names one function only when T is not Clone; for a Clone T the
// two impls make it ambiguous and the build fails. NotFromU64 is the same test for From<u64>.
// run() names both, so the checks are compile-time steps.
trait NotClone<A> {
    fn check() {}
}
impl<T> NotClone<()> for T {}
impl<T: Clone> NotClone<u8> for T {}

trait NotFromU64<A> {
    fn check() {}
}
impl<T> NotFromU64<()> for T {}
impl<T: From<u64>> NotFromU64<u8> for T {}

const _: fn(Stats) -> xy_api::ffi::xy_stats = |value| value;
const _: fn(xy_api::Wrap) -> xy_api::ffi::xy_wrap = |value| value;
const _: fn(Offset) -> xy_api::ffi::xy_offset = |value| value;
const _: fn(i32) -> Result<Status, i32> = Status::try_from;
const _: fn(u32) -> Result<Mode, u32> = Mode::try_from;
const _: () = assert!(size_of::<Status>() == size_of::<i32>());
const _: () = assert!(size_of::<Mode>() == size_of::<u32>());
const _: u32 = xy_api::API_VERSION;
const _: i32 = xy_api::FEAT_A;
const _: u32 = xy_api::FEAT_ALL;
const _: i32 = xy_api::NEG;
const _: u32 = xy_api::MAGIC;
const _: () = assert!(Status::ErrBusy as i32 == 9);
const _: () = assert!(Mode::Slow as u32 == 1);
const _: () = assert!(xy_api::FEAT_ALL == 9);
const _: () = assert!(xy_api::API_VERSION == 0x01020304);
const _: () = assert!(xy_api::NEG == -5);
const _: i32 = xy_api::FLOOR;
const _: () = assert!(xy_api::FLOOR == i32::MIN);
const _: () = assert!(Status::ErrFloor as i32 == i32::MIN);

fn run() -> u8 {
    let _: fn() = <Port as NotClone<_>>::check;
    let _: fn() = <Offset as NotFromU64<_>>::check;

    let Err(r) = Port::create(99) else {
        return 1;
    };
    if r != Status::ErrBusy || r.to_string() != "ERR_BUSY" {
        return 1;
    }

    let Ok(port) = Port::create(3) else {
        return 2;
    };
    if port.pstats().count != 3 || port.generation() != 7 || port.pwrap().n != 11 {
        return 2;
    }

    let buf = *b"abcd";
    if port.send(&buf) != Ok(()) || port.send(&buf[..3]) != Err(Status::ErrBusy) {
        return 3;
    }

    let mut out = [0u8; 5];
    if port.recv(&mut out) != Ok(()) || out[2] != 0 {
        return 4;
    }

    let cfg = Stats {
        count: 5,
        ..Stats::default()
    };
    let limit = 6;
    // SAFETY: the fake accepts a null token.
    if unsafe { port.configure(&cfg, &limit, Mode::Slow, std::ptr::null_mut()) } != Ok(()) {
        return 5;
    }

    let Ok((st, c, l)) = port.stats_of() else {
        return 6;
    };
    if st.count != 42 || c != 43 || l.is_null() {
        return 6;
    }

    let mut level = 4;
    let mut tally = Stats {
        count: 5,
        ..Stats::default()
    };
    let mut data = *b"abc";
    if port.bump(&mut level, &mut tally, &mut data) != Ok(())
        || level != 5
        || tally.count != 10
        || &data != b"bcd"
    {
        return 13;
    }

    if port.seek(1 << 40) != Ok(())
        || port.tune(-3, -(1 << 40), 200, 0.5) != Ok((-(1 << 40) - 1, -4))
    {
        return 14;
    }

    let note = Stats {
        count: 7,
        ..Stats::default()
    };
    if port.annotate(Some(&note)) != Ok(()) || port.annotate(None) != Ok(()) {
        return 15;
    }

    let probe_limit = 3;
    let mut probe_level = 4;
    let mut peek = 0;
    if port.probe(None, None, None, None) != Ok(Mode::Slow)
        || port.probe(
            Some(b"ab".as_slice()),
            Some(&probe_limit),
            Some(&mut probe_level),
            Some(&mut peek),
        ) != Ok(Mode::Slow)
        || probe_level != 5
        || peek != 9
        || port.probe(Some(b"abc".as_slice()), None, None, None) != Err(Status::ErrBusy)
    {
        return 17;
    }

    if port.echo_offset(Offset(1 << 40)) != Ok(Offset(1 << 40)) {
        return 18;
    }

    // Some(&[]) is a non-null pointer with a count of 0, which the fake refuses as a payload
    // that is present but not 2 bytes; None, a null pointer, it accepts.
    if port.probe(Some(&[]), None, None, None) != Err(Status::ErrBusy) {
        return 20;
    }

    // Reading `port` after the move does not compile, so only the destination is checked.
    let moved = port;
    if moved.handle().is_null() {
        return 7;
    }

    let Ok(mut other) = Port::create(4) else {
        return 8;
    };
    if other.handle() == moved.handle() {
        return 8;
    }
    other = moved;
    if other.handle().is_null() || other.generation() != 7 {
        return 8;
    }

    // release consumes the port, so a second release does not compile; the fake aborts if the
    // drop that follows a release destroys the port again.
    if other.release() != Ok(()) {
        return 9;
    }

    {
        let ports = [1, 2, 3, 4].map(Port::create);
        if ports.iter().any(Result::is_err) {
            return 10;
        }
    }
    if Port::create(1).is_err() {
        return 10;
    }

    if xy_api::PRODUCT != "xy widget" {
        return 11;
    }

    if DataLink::create().is_err() {
        return 12;
    }

    if Mode::Slow.to_string() != "SLOW"
        || format!("{}", Status::ErrBusy) != "ERR_BUSY"
        || Status::try_from(12345) != Err(12345)
        || xy_api::access_to_string(3) != "ACC_A|ACC_B"
        || xy_api::access_to_string(1) != "ACC_A"
        || xy_api::access_to_string(0) != "NONE"
        || xy_api::access_to_string(9) != "ACC_A|0x8"
        || xy_api::access_to_string(-1) != "ACC_A|ACC_B|0xfffffffc"
        || xy_api::limit_to_string(16) != "MAX_UNITS"
        || xy_api::limit_to_string(xy_api::NEG) != "NEG"
        || xy_api::limit_to_string(xy_api::FLOOR) != "FLOOR"
        || xy_api::limit_to_string(99) != "UNKNOWN"
    {
        return 16;
    }
    0
}

fn main() -> ExitCode {
    ExitCode::from(run())
}
