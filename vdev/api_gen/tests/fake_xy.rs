// A fake implementation of support.KITCHEN_SINK's API behind the generated relay, built as
// libxy.so: fake_xy.cpp's behaviour for every consumer, with named entries only. Where the relay
// hands over `None` for what a consumer never sends, the fake answers with an entry of its own,
// for edge_xy.c:
//   ErrFloor        a null non-optional pointer (probe's pmode excepted: probe writes it where given)
//   ErrUnsupported  a non-optional buffer the relay refused: null, or a count above isize::MAX;
//                   also seek(12345), fake_xy.cpp's unnamed result
//   ErrAgain        configure's mode naming no Mode entry
//   ErrOther        a null port for destroy_port, as fake_xy.cpp; recv's buffer not arriving zeroed
// seek(u64::MAX) panics, so a caller can see the relay abort the process.

pub mod abi {
    include!(concat!(env!("API_GEN_RUST_DIR"), "/xy_api_abi.rs"));
}

use abi::{Mode, Offset, Stats, Status, Wrap, ffi};
use core::sync::atomic::{AtomicBool, Ordering};

// A port handle is the address of its slot; a slot is open while it holds true.
static SLOTS: [AtomicBool; 4] = [const { AtomicBool::new(false) }; 4];
static LINK: u8 = 0;

fn link() -> ffi::xy_link {
    core::ptr::from_ref(&LINK).cast_mut().cast()
}

pub fn open_port(
    unit: u32,
    pport: Option<&mut ffi::xy_port>,
    pstats: Option<&mut Stats>,
    generation: Option<&mut u32>,
    pwrap: Option<&mut Wrap>,
) -> Result<(), Status> {
    let (Some(pport), Some(generation), Some(pwrap)) = (pport, generation, pwrap) else {
        return Err(Status::ErrFloor);
    };
    if unit == 99 {
        return Err(Status::ErrBusy);
    }
    let Some(slot) = SLOTS
        .iter()
        .find(|slot| !slot.swap(true, Ordering::Relaxed))
    else {
        return Err(Status::ErrBusy);
    };
    *pport = core::ptr::from_ref(slot).cast_mut().cast();
    let stats = Stats {
        count: unit,
        bytes: 1 << 40,
    };
    if let Some(pstats) = pstats {
        *pstats = stats;
    }
    *generation = 7;
    *pwrap = Wrap {
        inner: stats,
        n: 11,
    };
    Ok(())
}

/// release the port
pub fn destroy_port(hport: ffi::xy_port) -> Result<(), Status> {
    let Some(slot) = SLOTS.iter().find(|slot| core::ptr::eq(*slot, hport.cast())) else {
        return Err(Status::ErrOther);
    };
    if !slot.swap(false, Ordering::Relaxed) {
        std::process::abort(); // released twice: a finalizer firing after an explicit release
    }
    Ok(())
}

/// buf: bytes to send
pub fn send(hport: ffi::xy_port, buf: Option<&[u8]>) -> Result<(), Status> {
    let _ = hport;
    match buf {
        None => Err(Status::ErrUnsupported),
        Some(buf) if buf.len() == 4 => Ok(()),
        Some(_) => Err(Status::ErrBusy),
    }
}

pub fn spend(htoken: ffi::xy_token) -> Result<(), Status> {
    let _ = htoken;
    Ok(())
}

pub fn recv(hport: ffi::xy_port, pdst: Option<&mut [u8]>) -> Result<(), Status> {
    let _ = hport;
    let Some(pdst) = pdst else {
        return Err(Status::ErrUnsupported);
    };
    if pdst.iter().any(|&b| b != 0) {
        return Err(Status::ErrOther);
    }
    pdst.fill(b'r');
    if let Some(third) = pdst.get_mut(2) {
        *third = 0;
    }
    Ok(())
}

pub fn configure(
    hport: ffi::xy_port,
    cfg: Option<&Stats>,
    limit: Option<&u32>,
    mode: ffi::xy_mode,
    who: ffi::xy_token,
) -> Result<(), Status> {
    let _ = hport;
    let (Some(cfg), Some(limit)) = (cfg, limit) else {
        return Err(Status::ErrFloor);
    };
    let Ok(mode) = Mode::try_from(mode) else {
        return Err(Status::ErrAgain);
    };
    if cfg.count == 5 && *limit == 6 && mode == Mode::Slow && who.is_null() {
        Ok(())
    } else {
        Err(Status::ErrBusy)
    }
}

pub fn stats_of(
    hport: ffi::xy_port,
    out: Option<&mut Stats>,
    pcount: Option<&mut u32>,
    plink: Option<&mut ffi::xy_link>,
) -> Result<(), Status> {
    let _ = hport;
    let (Some(out), Some(pcount), Some(plink)) = (out, pcount, plink) else {
        return Err(Status::ErrFloor);
    };
    out.count = 42;
    *pcount = 43;
    *plink = link();
    Ok(())
}

/// level + 1, tally.count * 2, each byte of data + 1
pub fn bump(
    hport: ffi::xy_port,
    level: Option<&mut u32>,
    tally: Option<&mut Stats>,
    data: Option<&mut [u8]>,
) -> Result<(), Status> {
    let _ = hport;
    let (Some(level), Some(tally)) = (level, tally) else {
        return Err(Status::ErrFloor);
    };
    let Some(data) = data else {
        return Err(Status::ErrUnsupported);
    };
    *level = level.wrapping_add(1);
    tally.count = tally.count.wrapping_mul(2);
    for b in data {
        *b = b.wrapping_add(1);
    }
    Ok(())
}

pub fn open_link(plink: Option<&mut ffi::xy_link>) -> Result<(), Status> {
    let Some(plink) = plink else {
        return Err(Status::ErrFloor);
    };
    *plink = link();
    Ok(())
}

/// ok iff note is absent or note.count == 7
pub fn annotate(hport: ffi::xy_port, note: Option<&Stats>) -> Result<(), Status> {
    let _ = hport;
    if note.is_none_or(|note| note.count == 7) {
        Ok(())
    } else {
        Err(Status::ErrBusy)
    }
}

pub fn reset() -> Result<(), Status> {
    Ok(())
}

pub fn seek(hport: ffi::xy_port, offset: u64) -> Result<(), Status> {
    let _ = hport;
    match offset {
        u64::MAX => panic!("fake seek: offset u64::MAX"),
        12345 => Err(Status::ErrUnsupported),
        0x100_0000_0000 => Ok(()),
        _ => Err(Status::ErrBusy),
    }
}

/// pnext = big - 1, pdelta = delta - 1; ok iff delta == -3, big == -(1 << 40), small == 200, scale == 0.5
pub fn tune(
    hport: ffi::xy_port,
    delta: i32,
    big: i64,
    small: u8,
    scale: f64,
    pnext: Option<&mut i64>,
    pdelta: Option<&mut i32>,
) -> Result<(), Status> {
    let _ = hport;
    let (Some(pnext), Some(pdelta)) = (pnext, pdelta) else {
        return Err(Status::ErrFloor);
    };
    *pnext = big.wrapping_sub(1);
    *pdelta = delta.wrapping_sub(1);
    if delta == -3 && big == -(1 << 40) && small == 200 && scale == 0.5 {
        Ok(())
    } else {
        Err(Status::ErrBusy)
    }
}

/// pmode = slow, level + 1 and ppeek = 9 where given; ok iff payload is absent or 2 bytes and limit is absent or 3
pub fn probe(
    hport: ffi::xy_port,
    pmode: Option<&mut ffi::xy_mode>,
    payload: Option<&[u8]>,
    limit: Option<&u32>,
    level: Option<&mut u32>,
    ppeek: Option<&mut u32>,
) -> Result<(), Status> {
    let _ = hport;
    if let Some(pmode) = pmode {
        *pmode = ffi::XY_SLOW;
    }
    if let Some(level) = level {
        *level = level.wrapping_add(1);
    }
    if let Some(ppeek) = ppeek {
        *ppeek = 9;
    }
    if payload.is_none_or(|payload| payload.len() == 2) && limit.is_none_or(|&limit| limit == 3) {
        Ok(())
    } else {
        Err(Status::ErrBusy)
    }
}

/// ppos = pos
pub fn echo_offset(
    hport: ffi::xy_port,
    pos: Offset,
    ppos: Option<&mut Offset>,
) -> Result<(), Status> {
    let _ = hport;
    let Some(ppos) = ppos else {
        return Err(Status::ErrFloor);
    };
    *ppos = pos;
    Ok(())
}
