---
sessionId: session-260603-135405-vz2v
---

# Scope & Sources

This plan documents the actual, current behavior of the Single Axis Functional Test as implemented in the codebase. It is based on the following modules and their current logic:

- Controller: gui/workspace/controllers/single_axis_functional_test_controller.py
- Builders (TX): data/binary_cmd_builders.py
- Parser (RX): data/binary_cmd_parser.py
- Live transport adapter: services/functional_transport_adapter.py
- Popup/UI wiring: gui/workspace/pages/single_axis_functional_popup.py
- Tests reviewed: tests/test_single_axis_functional_controller.py, tests/test_single_axis_transport_integration.py

No code changes are proposed here. This is a readback of the implemented flow for comparison against live logs.

# Current Process Flow

The table below summarizes the end‑to‑end flow from Run click to PASS/FAIL. Columns: Step/State, Purpose, Command (TX), Expected RX/Event, Stores/Updates, Success Transition, Failure/STOP behavior.

 Step / State | Purpose | Command sent (TX) | Expected response / event (RX) | Stores / updates | Success transition | Failure condition / STOP |
---|---|---|---|---|---|---|
 Run clicked (Popup) | Initiate run; choose transport | — | — | Disables Run/Node UI, logs “— New functional test session —” | Creates controller; starts controller | If backend disconnected and not safe-TX: abort; no run; show warning |
 start() → IDLE | Begin state machine | C4 3F (NODECONFIG query) | — | _wait_for = "nodeconfig"; log “Querying NODECONFIG: C4 3F” | Wait NODECONFIG response | on_timeout → STOP + fail “NODECONFIG query timeout” |
 Handle NODECONFIG | Determine home/opposite sensor from bit0 | — | C4 3A <nodeconfig> | cfg.reference_sensor = L if bit0=0 else R; cfg.opposite_sensor = other; log “NODECONFIG received: 0x.., home=..” | HUNTING | Invalid response → STOP + fail “Invalid NODECONFIG response” |
 HUNTING | Ask MCU to home automatically | C3 21 <timeout_hi> <timeout_lo> | C3 41 (accepted), C3 4E (rejected), or C3 54 (timeout) | State → S_HUNTING; _wait_for="hunting_ack"; log “Starting HUNTING” | If accepted → WAIT_FOR_HUNTING_COMPLETION with expected sensor (L or R) | Rejected/None → STOP + fail “HUNTING rejected/NACK”; Timeout → STOP + fail “HUNTING timeout” or “no ACK/NACK/timeout” on timer |
 WAIT_FOR_HUNTING_COMPLETION | Wait for reference/home sensor hit | — | 81 4C (L), 81 52 (R), or Z‑form 81 5A 4C/52 | left_flag_changed(True) or right_flag_changed(True) | On expected sensor → WAIT_FOR_ENCODER_INITIALIZATION | Wrong L/R during hunting → STOP + fail “Wrong sensor event during hunting (expected X, got Y)”; timeout → STOP + fail |
 WAIT_FOR_ENCODER_INITIALIZATION | Wait for encoder init after home | — | 81 49 (I) | position_changed(0) | VERIFY_HOME_POSITION_ZERO; send GETPOS | Timeout → STOP + fail “Encoder init timeout after Left sensor” (generic for both sides) |
 VERIFY_HOME_POSITION_ZERO | Verify zero position | 82 (GETPOS) | 82 3A <pos> or 82 <pos> | position_changed(pos) | If |pos| <= zero_tolerance → Flag safety gate | If outside tolerance → STOP + fail “Zero position outside tolerance”; GETPOS timeout → STOP + fail |
 Flag safety gate | Ensure opposite sensor won’t reset encoder | C9 3F (LFLAG) if unknown; CA 3F (RFLAG) if unknown | C9 3A <flags>, CA 3A <flags> | _lflag/_rflag cached; logs “SensorL/ SensorR flag received: 0x..” | If both known and opposite has stop+response and no reset (0x09 ok; 0x0B not ok) → start first RUN to opposite | If opposite flag has reset (bit1) or lacks stop/response → STOP + fail “Opposite sensor flags unsafe for range (need response+stop, no reset)” |
 MOVE_TO_OPPOSITE_SENSOR_(R|L) | Start first leg toward opposite | 88 <vel_hi> <vel_lo> (build_run with configured velocity; not NODECONFIG bit1) | 88 53 84 <vel> (RUN started ACK) | — | On ACK → WAIT_FOR_RIGHT_SENSOR or WAIT_FOR_LEFT_SENSOR | Missing/invalid ACK → STOP + fail “RUN-to-(left|right) ACK missing/invalid” |
 WAIT_FOR_RIGHT_SENSOR | Wait for right sensor hit | — | 81 52 or 81 5A 52 | right_flag_changed(True) | On expected sensor → READ_AND_STORE_RANGE_1 and send GETPOS | Wrong L event while waiting right → STOP + fail “Wrong sensor event during right move (got L)”; timeout → STOP + fail |
 WAIT_FOR_LEFT_SENSOR | Wait for left sensor hit | — | 81 4C or 81 5A 4C | left_flag_changed(True) | On expected sensor → READ_AND_STORE_RANGE_1 and send GETPOS | Wrong R event while waiting left → STOP + fail “Wrong sensor event during left move (got R)”; timeout → STOP + fail |
 READ_AND_STORE_RANGE_1 | Store opposite position as Range1 | 82 (GETPOS) | 82 ... <pos> | _signed_range_1 = pos; _opposite_pos = pos; range1 = abs(pos); range1_changed(range1) | Start RUN back to home: 88 with configured velocity toward reference; wait for ACK | GETPOS timeout → STOP + fail |
 RUN back to home (ACK) | Confirm return leg started | 88 <vel> (to home) | 88 53 84 <vel> | — | On ACK → WAIT_FOR_(home)_SENSOR | Missing/invalid ACK → STOP + fail |
 WAIT_FOR_(home)_SENSOR | Wait for home sensor hit | — | 81 4C/52 or Z‑form matching home | left/right_flag_changed(True) | On expected sensor → READ_AND_STORE_RANGE_2 and send GETPOS | Wrong sensor during return → STOP + fail; timeout → STOP + fail |
 READ_AND_STORE_RANGE_2 | Store returned home pos; compute Range2 | 82 (GETPOS) | 82 ... <pos> | _signed_range_2 = pos; _returned_home_pos = pos; range2 = abs(opposite_pos − pos); difference_changed(|range1−range2|) | If difference <= range_tolerance → compute middle_target = opposite_pos // 2; MOVE_TO_MIDDLE; send TPOS | If opposite_pos missing → STOP + fail; If difference > tol → STOP + fail “Range difference exceeds tolerance” |
 MOVE_TO_MIDDLE | Command move to midpoint | 81 <middle_target:4> (big‑endian) | 81 'S' 0x82 <pos> (started), or 81 'E' 0x82 <pos> (reached), or 81 'N' 0x82 <pos> (no move) | position_changed(pos); cache _middle_target | If started → WAIT_FOR_MIDDLE_COMPLETION; If reached/no_move and within middle_position_tolerance → STOP then PASS | If position outside tolerance on reached/no_move → STOP + fail; if target unknown → STOP + fail |
 WAIT_FOR_MIDDLE_COMPLETION | Await completion | — | 81 'E' 0x82 <pos> | position_changed(pos) | If within tolerance of middle_target → STOP then PASS | Timeout → STOP + fail; outside tolerance → STOP + fail |
 Global safety | Treat resets during RUN as failure | — | 81 49 (I) during RUN/WAIT phases | — | — | Immediately STOP + fail “Encoder reset during RUN invalidates measurement” |

Notes:
- No EA manual‑zero command is sent anywhere (tests assert this).
- No NODECONFIG set (C4 3D) is ever sent; only C4 3F queries.
- Parser accepts both direct and Z‑form sensor events and normalizes Z to L/R in the controller.
- Live logs additionally show: “TX Node N: …” for every command, and “RX Node N: … - <label>” for key events (Left/Right/I; Position N).

# When L/R flags are queried and when RUN is allowed

- LFLAG/RFLAG (C9 3F / CA 3F) are sent only after encoder init and zero verification passes (|GETPOS| <= zero_tolerance) and before the first RUN.
- First RUN (0x88) is issued only after both flags have been received and the opposite sensor flag passes the safety gate (must have response+stop and must NOT have reset bit). On pass, the controller logs “Sensor flag safety check passed” and “Starting RUN to opposite,” then emits RUN.
- If the opposite flag includes reset (e.g., 0x0B), the controller logs failure and stops before any RUN is sent.

# Expected Example: Node 6 with NODECONFIG 0x00

Given NODECONFIG 0x00 (bit0 = 0 → home=L):

- Home/reference = L; opposite = R.
- Early sequence on a fresh run:
  1) TX Node 6: C4 3F
  2) RX Node 6: C4 3A 00
  3) Controller logs: “NODECONFIG received: 0x00, home=L”; state → HUNTING
  4) TX Node 6: C3 21 27 10 (10,000 ms)
  5) RX Node 6: C3 41 (accepted)
  6) Wait for L sensor: RX Node 6: 81 4C (or Z‑form 81 5A 4C)
  7) Wait for encoder init: RX Node 6: 81 49
  8) TX Node 6: 82 (GETPOS)
  9) RX Node 6: 82 … 00 00 00 00 (within tolerance)
  10) TX Node 6: C9 3F; then CA 3F
  11) RX Node 6: C9 3A <sensorL>; RX Node 6: CA 3A <sensorR>
  12) If opposite (R) flag is safe (e.g., 0x09): controller logs safety check passed.
  13) TX Node 6: 88 00 BE (example velocity +190 big‑endian) to move L→R; expect RX 88 53 84 00 BE (ACK)
  14) Wait for opposite sensor: RX Node 6: 81 52 (or 81 5A 52)
  15) TX Node 6: 82 (GETPOS) → RX position P_opposite; store Range1 = |P_opposite|
  16) TX Node 6: 88 FF 42 (example −190) to go back to L; expect RX 88 53 84 FF 42 (ACK)
  17) RX Node 6: 81 4C (or 81 5A 4C)
  18) TX Node 6: 82 → RX position P_return; store Range2 = |P_opposite − P_return|; compute diff
  19) If diff <= tolerance: TX Node 6: 81 <target= P_opposite // 2>
  20) RX Node 6: 81 'S' 0x82 <pos> then 81 'E' 0x82 <pos> (or immediate 'E' / 'N')
  21) If within middle tolerance: TX Node 6: DD (STOPMOTOR); PASS

Failures at any point trigger TX Node 6: DD and an explanatory reason.

# Fail‑fast cases (current code)

- NODECONFIG: timeout or invalid response → STOP + fail.
- HUNTING: rejected/NACK or timeout without ACK → STOP + fail.
- Hunting sensor: wrong L/R for expected home sensor → STOP + fail.
- Encoder init: missing 'I' event → STOP + fail.
- Zero verify: GETPOS outside tolerance → STOP + fail.
- Flags: opposite L/R flag has reset bit (0x02) or lacks stop/response → STOP + fail.
- RUN acks: missing/invalid ACK after RUN → STOP + fail.
- Wrong sensor during first or return move → STOP + fail.
- During RUN/WAIT: 'I' (encoder reset) received → STOP + fail.
- Range compare: |range1 − range2| > range_tolerance → STOP + fail.
- Middle move: ACK missing, completion timeout, or out of tolerance on 'reached'/'no_move' → STOP + fail.

# Test Coverage & Gaps

Covered by tests/test_single_axis_functional_controller.py:
- Full pass path including NODECONFIG gating, zero verify, flag queries, RUN legs, range store/compare, TPOS, STOP+PASS: test_full_pass_path
- Hunting rejection/timeout and no sensor → STOP: test_hunting_nack_fails_and_stops, test_hunting_no_reference_sensor_timeout_fails
- Missing encoder init after reference → STOP: test_missing_encoder_init_after_reference_sensor_fails
- Zero outside tolerance → STOP: test_zero_outside_tolerance_fails
- First RUN ack missing → STOP: test_first_run_ack_missing_fails
- Wrong sensor events during first/return moves → STOP: test_wrong_sensor_during_first_move_fails, test_wrong_sensor_during_return_move_fails
- Range1/Range2 store and compare, mismatch fail: test_range1_getpos_and_abs_store_then_run_right, test_range2_delta_and_mismatch_fails
- TPOS no_move within/outside tolerance: test_tpos_no_move_within_tolerance_passes, test_tpos_no_move_outside_tolerance_fails
- Big‑endian middle target bytes: test_big_endian_middle_byte_order
- Configurable left‑as‑reference sequence: test_configurable_left_as_reference_sequence_still_works
- Accept Z‑form sensor events and fail on 'I' during RUN: test_accept_z_sensor_events_and_fail_on_reset_during_run
- Any failure does STOP and does not continue: test_any_failure_stops_and_does_not_continue

Integration/logging with live adapter (tests/test_single_axis_transport_integration.py):
- Disconnected backend aborts run, warns, and enables UI: test_disconnected_backend_aborts_run
- Connected backend uses live adapter and logs TX/RX with node labels: test_connected_backend_sends_and_receives

Gaps before hardware testing:
- No explicit test asserts the exact status log sequence around NODECONFIG→HUNTING in live mode; however logs were added in the controller to make it visible.
- No explicit unit test for unsafe opposite flag value 0x0B (reset). Behavior is covered by the safety gate, but a focused assertion on the failure message could be added if desired.
- Real device timing/latency around HUNTING acceptance and sensor events is not simulated; CI relies on controller’s state machine and parser normalizations.

# RUN Velocity Logic — Verification & Findings

- Mapping required by the rig: L sensor is below, R is on top; negative RUN moves toward L; positive RUN moves toward R. Target velocities: velocity_toward_L = −190, velocity_toward_R = +190.
- Current implementation matches this mapping and does not derive RUN velocity from NODECONFIG bit1:
  - data/binary_cmd_parser.decode_nodeconfig_home_sensor: uses only bit0 to derive home sensor ('L' when bit0=0, 'R' when bit0=1).
  - gui/workspace/controllers/single_axis_functional_test_controller.py:
    - _maybe_start_first_run(): chooses velocity by sensor direction only:
      - opposite == 'R' → build_run(cfg.velocity_left_to_right) → +190 → bytes 88 00 BE
      - opposite == 'L' → build_run(cfg.velocity_right_to_left) → −190 → bytes 88 FF 42
    - READ_AND_STORE_RANGE_1 return leg: picks velocity toward reference sensor only (no use of NODECONFIG bit1):
      - reference == 'R' → to_home uses cfg.velocity_left_to_right (+190)
      - reference == 'L' → to_home uses cfg.velocity_right_to_left (−190)
  - data/binary_cmd_builders.build_run: emits 0x88 <hi> <lo> with two’s‑complement big‑endian; +190 → 00 BE; −190 → FF 42.
- Example (Node 6, NODECONFIG 0x00 → home=L, opposite=R):
  - First RUN to opposite/R uses +190 → 88 00 BE.
  - Return RUN to home/L uses −190 → 88 FF 42.
- Tests already covering both directions:
  - home=R path: tests/test_single_axis_functional_controller.py::test_full_pass_path asserts first leg uses −190 and return uses +190.
  - home=L path: tests/test_single_axis_functional_controller.py::test_configurable_left_as_reference_sequence_still_works asserts first leg uses +190 and return uses −190.
- Recommended extra assertion: add a focused unit test to prove NODECONFIG bit1 has no effect (0x01 vs 0x03 yield identical RUN velocities).

# Delivery Steps

###   Step 1: Confirm RUN velocity mapping against code
The controller’s RUN velocities are derived only from explicit config and sensor direction, not NODECONFIG bit1.

- Inspect decode_nodeconfig_home_sensor (data/binary_cmd_parser.py) to confirm only bit0 is used.
- Inspect _maybe_start_first_run and the return‑leg path in SingleAxisFunctionalTestController to verify:
  - opposite 'R' → build_run(+190) → 88 00 BE
  - opposite 'L' → build_run(−190) → 88 FF 42
  - to_home uses +190 when home='R' and −190 when home='L'.
- Verify builders encode velocities correctly (two’s‑complement, big‑endian) in data/binary_cmd_builders.build_run.
- No source changes expected at this step.

###   Step 2: Add explicit unit test for NODECONFIG bit1 independence and validate both home directions
A new focused test ensures RUN velocity ignores NODECONFIG bit1 and that both home directions still produce the expected bytes.

- File: tests/test_single_axis_functional_controller.py
- Add test `test_run_velocity_ignores_nodeconfig_bit1`:
  - Start controller; respond with NODECONFIG 0x01 (home=R, bit1=0); proceed to flags and assert first RUN is −190 (88 FF 42) and return is +190 (88 00 BE).
  - Restart; respond with NODECONFIG 0x03 (home=R, bit1=1); repeat assertions; velocities must be identical.
  - Mirror the check for home=L with NODECONFIG 0x00 vs 0x02; both must produce +190 to opposite and −190 back.
- Run: python -m pytest -q tests/test_single_axis_functional_controller.py tests/test_single_axis_functional_popup.py tests/test_single_axis_transport_integration.py
- Ensure no EA or C4 3D is ever sent; velocities come only from config; existing tests remain green.