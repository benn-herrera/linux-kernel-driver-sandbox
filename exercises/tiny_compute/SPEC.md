# SPEC – tiny_compute

A driver for a small PCI compute device: probe and teardown, a
character-device ABI, interrupt-driven compute, DMA, concurrent callers,
and multiple device instances. The device is QEMU's `edu`, whose
register map follows. The Roadmap section of ARCHITECTURE.md beside this
file lists what remains.

## Device: QEMU `edu`

The driver binds to QEMU's `edu` device, which `just run-vtarget` attaches
by default (`VTARGET_DEVICES`). This section transcribes `docs/specs/edu.rst`
from the QEMU v11.1.1 tree (the installed version), copyright 2014-2015 Jiri
Slaby, GPLv2 or later. The register map below is the whole hardware
interface.

### PCI identification

| Item | Value |
|---|---|
| Vendor:Device | `1234:11e8` |
| BAR 0 | memory, 1 MB; all communication goes through it |
| DMA addressing | 28 bits (256 MiB) by default; the driver must set the DMA mask to match, or use `-device edu,dma_mask=<mask>` |
| Interrupts | INTx by default; MSI supported |

### MMIO register map (BAR 0)

Accesses below `0x80` must be 4 bytes wide. At `0x80` and above, 4 or 8 bytes.

| Offset | Access | Register | Semantics |
|---|---|---|---|
| `0x00` | RO | identification | `0xRRrr00ed` form: `RR` major version, `rr` minor version, low byte `0xed`. The original spec writes `0xRRrr00edu`; the `u` is C's unsigned suffix on the literal in QEMU's source, not a digit. Expect `0x010000ed` for version 1.0 |
| `0x04` | RW | liveness check | reads back the bitwise inversion (`~`) of the value written |
| `0x08` | RW | factorial | write n; the device replaces it with n! once the factorial bit in the status register clears |
| `0x20` | RW | status | bit `0x01` (RO): computing factorial; bit `0x80`: raise an interrupt when the factorial finishes |
| `0x24` | RO | interrupt status | the values that raised the interrupt (see `0x60`) |
| `0x60` | WO | interrupt raise | value is ORed into interrupt status and an interrupt is raised |
| `0x64` | WO | interrupt acknowledge | value is cleared from interrupt status; must be written from the handler to stop the interrupt |
| `0x80` | RW | DMA source address | where the transfer reads from |
| `0x88` | RW | DMA destination address | where the transfer writes to |
| `0x90` | RW | DMA transfer count | size of the transfer in bytes |
| `0x98` | RW | DMA command | bit `0x01`: start; bit `0x02`: direction, 0 = RAM to device, 1 = device to RAM; bit `0x04`: raise interrupt `0x100` on completion |

### Interrupt controller

A write to the interrupt raise register generates an interrupt. The written
value appears in the interrupt status register and stays there, with the
interrupt asserted, until the same value is written to the interrupt
acknowledge register. This holds for MSI as well as INTx: even a driver that
disables INTx and uses only MSI must write the acknowledge register at the end
of its handler.

### DMA controller

The device owns one 4096-byte buffer at device address `0x40000`. A transfer
is programmed by writing source, destination and count, then the command
register with the start bit; the start bit reads as set until the transfer
completes. The source or destination on the device side is an address inside
that buffer; on the host side it is a DMA address the driver obtained by
mapping a buffer, within the device's DMA mask.

Example from the spec, moving 100 bytes to the device and back, with `addr`
a DMA address of a host buffer:

```
addr     -> DMA source address
0x40000  -> DMA destination address
100      -> DMA transfer count
1        -> DMA command register        (start, RAM to device)
while (DMA command register & 1)
    ;

0x40000  -> DMA source address
addr+100 -> DMA destination address
100      -> DMA transfer count
3        -> DMA command register        (start, device to RAM)
while (DMA command register & 1)
    ;
```

Setting bit `0x04` in the command register instead of polling raises
interrupt `0x100` on completion, which the handler acknowledges like any
other.

**ARM64 virt trap.** The default 28-bit mask covers 256 MiB, and on QEMU's
`virt` machine guest RAM starts at 1 GiB, so no host buffer is reachable
with the default. The device model clamps a DMA address to its mask rather
than rejecting it, so the transfer silently goes elsewhere. Before the DMA
exercise, the device needs `edu,dma_mask=0xffffffff` in `VTARGET_DEVICES`
and the driver a matching `dma_set_mask_and_coherent(dev, DMA_BIT_MASK(32))`.
The clamping behaviour is from memory of the device model, not verified
against the installed QEMU's source; the RAM base is a property of the
`virt` machine and is not in doubt.
