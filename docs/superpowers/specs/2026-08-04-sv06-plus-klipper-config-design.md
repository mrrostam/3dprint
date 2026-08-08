# SV06 Plus Klipper Configuration Remediation — Design

- **Date:** 2026-08-04
- **Printer:** Sovol SV06 Plus, Klipper `v0.13.0-708-g7046bd00`, host `rpi4.local` (Raspberry Pi 4B)
- **Config repo:** `mrrostam/3dprint`, path `sovol_sv06_plus/klipper`
- **Status:** Approved for planning

## 1. Problem

The print `Standee Tray v4` (started 2026-08-03 21:20) failed at 23:45:32 and the resulting
part was unusable. Investigation found **four independent faults**, only one of which was
the error the user saw.

### 1.1 Y stepper driver overheating (the visible warning)

```
TMC 'stepper_y' reports DRV_STATUS: 00140101 otpw=1(OvertempWarning!) t120=1 cs_actual=20
```

`t120=1` means the TMC2209 exceeded 120 °C (hard shutdown is 150 °C). Frequency is rising
sharply: **16 events on Aug 1, 45 on Aug 2, 86 on Aug 3.** Only ever `stepper_y`.

Root cause is confirmed by correlating fan state against the warning window:

| Fact | Value |
|---|---|
| Slicer setting | `close_fan_the_first_x_layers = 2` |
| First `M106 S255` in the gcode | byte offset **247,057** (layer 3) |
| `sd_pos` range over which all 86 warnings occurred | **102,461 → 163,051** |

Every warning fell strictly before the fan switched on, and they stopped the moment it did.
On the SV06 the **mainboard fan is wired to the part-cooling fan circuit** — part fan at 0 %
means no board airflow at all. The config exposes exactly one controllable fan,
`[fan] pin: PA0`. So for the first two layers the Y driver ran with zero cooling while
dragging a 300×300 heated bed across a 240×195 mm first layer at 3000 mm/s².

### 1.2 MCU USB dropouts (what actually killed the print)

The print died on `Lost communication with MCU 'mcu'`, not on an overtemp shutdown:

```
Aug 03 23:45:32 usb 1-1.1: USB disconnect, device number 13
Aug 03 23:45:33 usb 1-1.1: new full-speed USB device number 14
```

The CH340 serial bridge dropped off the bus and re-enumerated one second later. Recurring:
**6 events on Aug 3, 1 on Jul 31, 2 on Jul 26.** The CH340 reports no serial number, so its
`/dev/serial/by-id/` name is not guaranteed unique.

### 1.3 Acceleration exceeds the measured input-shaper limit

`modules/functions/input_shaper.cfg` records the measured ceiling:

```ini
shaper_type_y: 2hump_ei
shaper_freq_y: 49.0
# max acceleration = 1700
```

The active profile sets `max_accel: 3000`. Klipper has no per-axis acceleration limit, so Y
runs at 3000 — about **1.8× its measured safe limit**. The slicer profile requests 8000 and
declares `machine_max_acceleration_y = 1700,960`, which Klipper does not honour. This is the
most likely cause of the poor surface quality.

### 1.4 Raspberry Pi undervoltage

`vcgencmd get_throttled` returns `0x50000` (under-voltage occurred + throttling occurred).
Eight kernel undervoltage events on Aug 3 between 21:58 and 22:20. These did **not**
coincide with the 23:45 USB disconnect, so they are not established as its cause, but the
supply is demonstrably marginal.

## 2. Constraints

- **The part-cooling fan must remain off for the first two layers.** User requirement, for
  PLA bed adhesion. This rules out the common workaround of forcing a minimum fan speed
  during early layers. Config changes must therefore reduce heat *generation* enough to
  survive two fanless layers.
- Changes must be revertible; the printer is in active use.
- Sensorless homing (`tmc2209_stepper_*:virtual_endstop`) must keep working.

## 3. Non-goals

- Not adopting `klipper_tmc_autotune` in this pass. It is a reasonable future option, but it
  adds a dependency and its own README warns that drivers "can also run hotter" — the wrong
  risk to take while actively debugging a thermal fault.
- Not restructuring the macro library. `PRINT_START` / KAMP / `SMART_PARK` / `LINE_PURGE`
  are sound and out of scope.
- Not changing slicer profiles, beyond noting the accel mismatch.

## 4. Design

### 4.1 Driver thermal budget

All changes go in `modules/printing-profiles/drivers/TMC_2209_basic.cfg`, which already
includes the shared base and currently has every override commented out. That is exactly the
file's purpose, and it leaves the shared `TMC_2209.cfg` base untouched for the other profiles.

| Setting | Current | Proposed | Rationale |
|---|---|---|---|
| `run_current` (Y) | 0.880 | 0.750 | Conduction loss scales with I² → ~27 % reduction. This is the dominant lever |
| `hold_current` (all) | unset → equals run | 0.500 | Prevents holding full current at standstill |
| `stealthchop_threshold` (X/Y/Z) | 0 (spreadCycle) | 999999 | stealthChop's voltage-mode PWM runs cooler at the low/mid speeds where first layers live, and is far quieter |
| `interpolate` (X/Y/Z) | False | True | Driver interpolates internally to 256 µsteps |
| `microsteps` (X/Y/Z/E) | 128 | 32 | Cuts step rate 4× (640 → 160 steps/mm). Motion smoothness preserved by interpolation |

**Honest scoping of the microstep change:** the TMC2209's power-stage switching frequency is
set by its internal chopper (`toff`, `tbl`), not by the step-pulse rate. Dropping microsteps
therefore has only a modest direct effect on *driver* temperature. It is included because it
cuts host→MCU step load fourfold, which bears on §4.3, not because it is a thermal fix.

**Risks:**
- stealthChop yields less torque at high speed. At the reduced accel of §4.2 and a 200 mm/s
  ceiling this is acceptable on a bed slinger, but skipped steps are the failure mode to
  watch for.
- Klipper switches driver mode automatically during sensorless homing, so `virtual_endstop`
  keeps working. `driver_SGTHRS` (Y=110, X=86) was tuned under spreadCycle and must be
  re-verified after the change.
- Lowering `run_current` risks skipped Y steps. Mitigated by the simultaneous accel
  reduction: torque demand falls roughly in proportion, so 0.750 A at 1700 mm/s² has more
  headroom than 0.880 A at 3000 mm/s².

### 4.2 Motion limits

In `modules/printing-profiles/basic.cfg`:

| Setting | Current | Proposed |
|---|---|---|
| `max_accel` | 3000 | 1700 |
| `square_corner_velocity` | 8.0 | 5.0 |

1700 is the Y figure recorded in `input_shaper.cfg`; Klipper's single global `max_accel`
must take the lower of the two axes (X measures 5900). A comment will cross-reference
`input_shaper.cfg` so the two cannot silently drift apart again.

`square_corner_velocity: 8.0` is currently *higher* than the `performance.cfg` profile's 5.0,
which is backwards; 5.0 is appropriate for a bed slinger.

Expected cost: roughly 15–25 % longer prints.

### 4.3 Host ↔ MCU link reliability

- Change `[mcu] serial:` in `modules/options.cfg` from `by-id` to the corresponding
  `/dev/serial/by-path/` node. The CH340 has no serial number, so `by-id` is not a stable
  unique identifier. The node currently resolving to the board is:

  ```
  /dev/serial/by-path/platform-fd500000.pcie-pci-0000:01:00.0-usb-0:1.1:1.0-port0
  ```

  **Ordering constraint:** `by-path` encodes the physical USB port, so it must be set
  *after* the cable's final port is chosen. Do the physical work below first, then read the
  node and write it into the config. Getting this backwards produces a printer that will not
  start.
- Add a udev rule disabling USB autosuspend for that port. This is a **system file**
  (`/etc/udev/rules.d/`), outside the repo — it must be recorded in the repo README so it is
  not lost on a host rebuild.
- Physical: shorter shielded USB cable with ferrite; try a different Pi USB port.

### 4.4 Filament runout detection

The sensor is already enabled in Klipper (`enabled: true`, `pause_on_runout: True`) but has
never functioned. Current live state is `filament_detected: false` with no filament loaded,
which confirms the **uncommitted `switch_pin: !PA4` polarity change is correct** — it just
needs committing. No genuine runout or insert event appears anywhere in the logs.

Four defects to close:

1. **Dead control variable.** `variable_filament_sensor_enabled: 0` in `_globals`
   (`macros.cfg:6`) is referenced nowhere in the config tree. It reads like an on/off switch
   and is not one. Remove it; `SET_FILAMENT_SENSOR` plus the sensor's own `enabled` state is
   the real control.

2. **Commit the polarity fix.** `switch_pin: PA4` → `!PA4`, currently uncommitted.

3. **Cold-nozzle trap on runout.** `PAUSE` deliberately issues `M104 S0` so filament isn't
   cooked during a long pause — correct in itself. But it means that when you return to a
   runout pause, the hotend is cold, and `LOAD_FILAMENT` extrudes immediately with no
   temperature check. Klipper refuses extrusion below `min_extrude_temp` (default 170 °C),
   so the macro errors out at exactly the moment the user needs it.
   Fix in `LOAD_FILAMENT` / `UNLOAD_FILAMENT`: if the hotend is below the extrude minimum,
   heat to the saved `etemp` (falling back to a sane default) and wait, before extruding.
   This preserves `PAUSE`'s cooling behaviour rather than undoing it.

4. **No guard against starting a print with no filament.** A switch sensor only fires on the
   *transition* to not-detected during a print. Starting with an empty path produces no
   trigger and therefore no protection. Add a check at the top of `PRINT_START` that aborts
   the print if `filament_detected` is false.

**Risk:** enabling a sensor that genuinely works introduces a new failure mode — false
runout triggers mid-print from a marginal switch or noisy wiring. Validation below requires
confirming *both* states before this is trusted on a long print.

### 4.5 Bed mesh density

Change `[bed_mesh] probe_count` in `options.cfg` from `15, 15` to `9, 9`.

**How this propagates.** `probe_count` is not a fixed point count — the KAMP
`BED_MESH_CALIBRATE` override treats it as a *density reference and upper cap*:

```
max_probe_point_distance_x = (mesh_max[0] - mesh_min[0]) / (probe_count[0] - 1)
```

At `15,15` that is 19.4 mm spacing; at `9,9` it becomes 34.0 mm. KAMP then sizes the mesh to
the print area at that spacing and clamps to `probe_count`.

Worked against the failed print's area (`AREA_START=28.7552,50.4902 AREA_END=271.245,249.509`,
`mesh_margin: 5`):

| `probe_count` | Spacing | KAMP-computed grid | Points | Probes at `samples: 3` | Algorithm |
|---|---|---|---|---|---|
| `15, 15` (current) | 19.4 mm | 14 × 12 | 168 | 504 | bicubic |
| `9, 9` (proposed) | 34.0 mm | 9 × 8 | 72 | 216 | bicubic |

The 14 × 12 figure is corroborated by the saved `[bed_mesh default]` profile in `printer.cfg`,
which is exactly `x_count = 14, y_count = 12` — confirming the model above reproduces what
KAMP actually does.

**`9,9` keeps bicubic.** KAMP selects the interpolation algorithm from the point count:
bicubic above 6 points per axis, lagrange at or below. The computed grid is 9 × 8, so the
maximum is 9 and bicubic is retained. The `algorithm: bicubic` line in `[bed_mesh]` continues
to describe what actually runs. (At `4,4` it would have silently become lagrange.)

**Assessment.** 34 mm spacing resolves the local structure visible in the existing 15 × 15
probe data — rows swing ~0.16 mm across X over roughly 40–60 mm features — while cutting
probe work to about 43 % of current. This is a reasonable trade rather than a compromise, and
supersedes the density concern that applied at `4,4`.

**Note on where the time actually goes.** Probe *count* is only one factor. `[probe]` is set
to `samples: 3` with `samples_tolerance: 0.01` and `samples_tolerance_retries: 5`. A 0.01 mm
agreement requirement across three samples triggers frequent retries, so real probe time
exceeds the table above. Relaxing to `samples: 2` and `samples_tolerance: 0.025` would cut
time substantially *without* sacrificing mesh density. Left out of scope — flagged so the
choice is deliberate.

### 4.6 First layer quality

**Observed symptom: the defect is uniform across the entire bed**, not localised to one side
or to the edges (user report).

**Axis twist is ruled out and deliberately deferred.** `[axis_twist_compensation]` is included
and active but has never been calibrated — live state is `{}` and `printer.cfg` holds no saved
block, so the module is inert. It was initially suspected because every row of `SV06_mesh`
slopes the same way across X (`+0.033` at X=27 to `−0.127` at X=299, repeated across all 15
rows), which is the signature of probe-vs-nozzle disagreement.

That hypothesis is **refuted by the symptom being uniform**. Gantry twist is asymmetric by
construction: it raises the nozzle at one X extreme and lowers it at the other, so it produces
gaps on one side and over-squish on the other — never a uniform defect. Running
`AXIS_TWIST_COMPENSATION_CALIBRATE` is therefore **omitted from this work at user direction**,
and the 0.16 mm slope in the mesh is taken to be genuine bed shape, which the mesh already
compensates.

**Actual causes, consistent with a uniform defect:**

1. **Z-offset.** Currently `2.571`. A uniform first-layer defect across a bed whose mesh is
   already compensating for shape points at the global nozzle-to-bed distance.
2. **Under-extrusion.** `filament_flow_ratio = 0.92` is ~8 % below nominal.
3. **First layer lines narrower than the rest.** `initial_layer_line_width = 0.42` against
   `line_width = 0.44`. Convention is the reverse — a wider first layer aids adhesion and
   closes inter-line gaps.

(2) and (3) compound: reduced flow through narrower lines leaves adjacent first-layer
extrusions short of touching. Both are slicer-side, and §3 places slicer profiles out of
scope, so they are recorded as findings for the user to apply rather than as config work.

**Ruled out:** `initial_layer_speed = 40` mm/s is conservative and is not a contributor.

**Resolution method.** Z-offset direction is not determined from the data — gaps and
over-squish are opposite faults requiring opposite corrections — so it is tuned live rather
than guessed. During a first-layer test print, apply `SET_GCODE_OFFSET Z_ADJUST=±0.02 MOVE=1`
until the lines just merge, then fold the net adjustment into `probe z_offset` as
`new = 2.571 − (net Z_ADJUST)`. Sign relationship: a positive `Z_ADJUST` raises the nozzle
and is equivalent to *decreasing* `z_offset`.

### 4.7 Hardware items (tracked, not implemented here)

1. **Rewire the mainboard fan to constant 24 V.** Given the fan-off-for-two-layers
   constraint, this is the only complete fix for §1.1; everything in §4.1 buys margin.
2. **Replace the Pi power supply** with an official 5 V/3 A unit (§1.4).

### 4.8 Repo hygiene

- Remove committed `.DS_Store` files (repo root, `klipper/`, `klipper/modules/`) and add to
  `.gitignore`.
- Add a header comment to each profile stating its real measured limits.
- Tighten `[verify_heater extruder]` in `options.cfg` — `max_error: 200` with
  `hysteresis: 5` is loose enough to mask genuine heater faults.

**Deviation from the approved outline, flagged for review:** the outline said to *rename*
the profiles so the default is the conservative one. This spec instead fixes `basic.cfg`'s
contents so it is genuinely conservative, and documents each profile's limits in a header.
Renaming churns the include lines in `options.cfg` for cosmetic benefit. If the rename is
still wanted, say so and it will be added.

## 5. Validation

Changes are only accepted if all of the following hold:

1. **Thermal:** run a print with `close_fan_the_first_x_layers = 2` and a first layer of
   comparable area. `grep -c "otpw=1" klippy.log` returns **0**.
2. **No regression in homing:** ten consecutive `G28` cycles succeed with no false triggers
   and no crashes into the endstop.
3. **No skipped steps:** print a tall square-tower test; measure X/Y dimensions at base and
   top. Deviation under 0.3 mm.
4. **Quality:** ringing test print shows visibly reduced Y ghosting versus the current part.
5. **Link stability:** no `Lost communication with MCU` across at least three prints
   totalling 10+ hours.
6. **Power:** `vcgencmd get_throttled` reads `0x0` after a fresh boot plus one full print.
7. **Filament sensor, both states proven:** with filament loaded through the sensor,
   `filament_detected` reads `true`; with it removed, `false`. Confirming only one state is
   insufficient — that is how the current broken configuration went unnoticed.
8. **Runout recovery works end to end:** mid-print, pull the filament. The print pauses and
   parks; `LOAD_FILAMENT` succeeds from the cold paused state without a manual `M109`;
   `RESUME` reheats and continues with no visible layer defect.
9. **Empty-start guard:** starting a print with no filament loaded aborts in `PRINT_START`
   rather than air-printing.
10. **Bed mesh:** a full-bed print produces a 9 × 8 **bicubic** mesh — confirm in the KAMP
    verbose output that the algorithm is bicubic, not lagrange. A silent fall to lagrange
    means the computed grid came out at 6 or fewer points per axis and the density is lower
    than intended. First layer inspected against a known-good reference.

## 6. Rollback

Every change is either a Klipper include-file edit or a single line in `options.cfg`. Revert
the branch and `FIRMWARE_RESTART`. Profile selection is one include line, so reverting to the
current behaviour is a one-line change even without git.

## 7. Follow-ups

- Re-run `TEST_RESONANCES` with the ADXL345 to confirm whether 1700 mm/s² is still accurate;
  belts may have shifted since the recorded measurement. Raise the limit only on evidence.
- Re-tune `driver_SGTHRS` under stealthChop.
- Reconsider `klipper_tmc_autotune` once the thermal fault is closed out.
