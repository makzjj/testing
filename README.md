# IPQC Software

PC application for In-Process Quality Control (IPQC). This repository contains a PyQt6 desktop application used to configure, validate, and test ML2.0 robotic controller nodes over a proprietary CAN-over-UART communication path.

---

## Project Overview

The deployed system is:

```text
Robot
  ->
Master MCU
  ->
CAN Bus
  ->
Robot Nodes
  ->
IPQC Desktop Application
```

The desktop application is the engineer and operator entry point on the PC side. It communicates with the robot through the master MCU, verifies node parameters against project configuration and workbook data, performs production programming, runs functional tests, executes sampling workflows, exposes mechanical and firmware diagnostics, and generates completed workbook outputs for traceability.

Its current responsibilities include:

- communication
- parameter verification
- production programming
- functional testing
- sampling
- diagnostics
- workbook generation

---

## Major Features

### Production

- Load IPQC workbook templates
- Verify node parameters against workbook/project expectations
- Perform selective parameter writes
- Save persistent values to EEPROM when required
- Generate completed workbook output

### Single Axis

- Hunting workflow
- Encoder range measurement
- Sensor validation
- Timeout and abort handling

### Sampling

- Travel timing capture
- Encoder-derived measurement statistics
- Workbook export through the IPQC Excel adapter

### Mechanical

- Manual diagnostics
- Parameter utilities
- Motion commands and position utilities

### Plots

- Live Motor Current plotting
- Placeholder launchers for future diagnostic plots

### Project Config

- Project configuration editor for YAML-based workspace definitions

### Firmware

- Firmware and protocol utilities

### Runtime

- Runtime monitoring through the embedded legacy runtime surface

---

## High-Level Architecture

This codebase is in an incremental layered refactor. The current architecture is organized as:

```text
Protocol Layer
  ->
Runtime State
  ->
Request / Operation Adapters
  ->
Workflow Controllers
  ->
UI
```

- **Protocol Layer**: owns packet parsing/building and semantic command decode only.
- **Runtime State**: owns shared per-node and system state, unsolicited events, and runtime-backed diagnostic data. Runtime is the single source of truth.
- **Request / Operation Adapters**: narrow transport adapters that filter shared packet traffic down to workflow-relevant packets.
- **Workflow Controllers**: own workflow sequencing, timeouts, pass/fail decisions, and operation-local state.
- **UI**: starts workflows and renders runtime-backed state. UI renders runtime and does not own protocol state.

In practice, controllers own workflows, adapters filter workflow packets, and the protocol layer owns packet parsing/building. The repository still contains active legacy shell code while this layered structure is completed, but the remaining work is additive rather than a ground-up architectural rewrite.

---

## Repository Structure

- `data/`: shared command builders/parsers plus runtime data folders for logs, exports, and writable config.
- `gui/`: PyQt6 UI code, including the workspace shell, pages, dialogs, and the still-active legacy runtime window.
- `services/`: runtime state handling, narrow workflow adapters, workbook services, backend helpers, and shared motion/runtime utilities.
- `serial_conn/`: low-level serial transport, framing, command handling, and packet parsing for the CAN-over-UART link.
- `myconfig/`: project configuration models, YAML loading, validation, editing, and save/version services.
- `resources/`: bundled application images and icons.
- `project_configs/`: selectable project YAML definitions loaded by the project selector window.
- `tests/`: pytest-based regression coverage for protocol helpers, runtime services, controllers, pages, config flows, and workbook handling.
- `docs/`: architecture migration notes and the canonical pipeline registry.
- `scripts/`: local build and test entry points, including the Windows packaging script.

The desktop entry point is `main.py`, which prepares runtime directories and launches the project selector window.

---

## Testing

The repository uses `pytest`.

Run the full suite with `python -m pytest`.

Important test groups include:

- protocol helpers and parsing: `tests/test_binary_command_helpers.py`, `tests/test_serial_packet_parser.py`, `tests/test_tpos_decoder.py`
- runtime and bridge behavior: `tests/test_backend_runtime_services.py`, `tests/test_workspace_runtime_bridge.py`, `tests/test_workspace_session_panel.py`
- workflow controllers and adapters: `tests/test_sampling_controller.py`, `tests/test_single_axis_functional_controller.py`, `tests/test_single_axis_transport_integration.py`, `tests/test_functional_transport_adapter_integration.py`, `tests/test_production_test_controller.py`
- UI, workbook, and config flows: `tests/test_mechanical_page.py`, `tests/test_motor_current_plot_dialog.py`, `tests/test_ipqc_excel_adapter.py`, `tests/test_config_services.py`, `tests/test_config_end_to_end.py`, `tests/test_project_loader.py`

All new features should include regression tests.

One known intentional Production test exclusion appears in the architecture doc's broader regression commands:

- `tests/test_production_test_controller.py::test_production_page_robot_power_button_order_and_connection_state`

---

## Deployment

Windows build and deployment details are documented in [DEPLOYMENT_WINDOWS.md](DEPLOYMENT_WINDOWS.md).

---

## Current Architecture Status

- Runtime ownership completed
- Narrow workflow adapters completed
- Production parameter adapter completed
- Mechanical cleanup completed
- Motor Current plotting implemented
- Remaining work focuses on feature additions rather than architectural restructuring

---

## Development Guidelines

- One responsibility, one owner.
- Runtime owns shared state.
- UI never owns protocol state.
- Avoid duplicate implementations.
- New commands go through canonical builders/parsers.
- Always update tests.
