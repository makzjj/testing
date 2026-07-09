# IPQC Software

IPQC is a Windows desktop application for In-Process Quality Control of ML2.0 robotic controller nodes. It is used to configure, validate, program, test, and diagnose robot nodes over a proprietary CAN-over-UART link.

## Project Overview

The system context is:

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

The application is the PC-side operator and engineering surface for:

- communication with the master MCU and robot nodes
- workbook-driven parameter verification and programming
- Single Axis functional testing
- sampling and workbook result export
- mechanical diagnostics and motion utilities
- firmware/protocol utilities
- runtime monitoring and communication logging
- live Motor Current diagnostic plotting

## Major Capabilities

### Production

- load IPQC workbook templates
- verify workbook parameters against live node values
- perform selective parameter writes
- save persistent values to EEPROM when required
- generate completed workbook outputs

### Single Axis

- hunting workflow
- encoder range measurement
- sensor validation
- timeout and abort handling

### Sampling

- travel timing capture
- encoder-based measurement statistics
- workbook export through the shared Excel adapter

### Mechanical, Firmware, and Runtime

- manual diagnostics and motion utilities
- firmware/protocol tools
- runtime monitoring and communication log viewing
- live Motor Current plotting

## High-Level Architecture

The codebase follows a layered ownership model:

```text
Protocol
  ->
Runtime
  ->
Request / Operation Adapters
  ->
Workflow Controllers
  ->
UI
```

- **Protocol** owns packet builders, frame parsing, and semantic decoding.
- **Runtime** owns shared per-node and system state.
- **Adapters** filter shared packet traffic down to workflow-relevant packets.
- **Controllers** own workflow sequencing, timeouts, and pass/fail logic.
- **UI** starts workflows and renders runtime-backed state.

The detailed architecture, ownership rules, and current status are documented in [ARCHITECTURE.md](ARCHITECTURE.md). Exact canonical owners are tracked in [CANONICAL_PIPELINE_REGISTRY.md](CANONICAL_PIPELINE_REGISTRY.md).

## Repository Layout

- `gui/`: PyQt6 application UI, workspace shell, pages, dialogs, and legacy runtime window
- `services/`: shared runtime handlers, workflow adapters, workbook services, and cross-workflow utilities
- `serial_conn/`: low-level serial transport, framing, and packet parsing
- `data/`: canonical binary command builders, semantic parsers, and packaged runtime data folders
- `myconfig/`: YAML-backed project configuration models, validation, editor, and save flow
- `project_configs/`: selectable project definitions loaded by the project selector
- `resources/`: bundled application icons and images
- `tests/`: pytest regression suite
- `scripts/`: local helper scripts for running tests and building releases

The desktop entry point is `main.py`.

## Feature Summary

The current repository state includes:

- runtime-owned node and system state
- narrow workflow ingress adapters for Sampling, Single Axis, Production Test, and Production Parameters
- a shared Production parameter pipeline
- runtime-backed interrupt and motor-current data
- workbook serialization for Production and Sampling flows
- a PyQt6 workspace shell that coexists with the legacy runtime surface during the layered refactor

Remaining work is primarily additive:

- additional diagnostic plots
- UI polish
- documentation hardening
- future product features

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md): system design, layer responsibilities, and ownership model
- [CANONICAL_PIPELINE_REGISTRY.md](CANONICAL_PIPELINE_REGISTRY.md): detailed technical registry of canonical owners
- [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md): setup, testing, workflow, and contribution guidance
- [DEPLOYMENT_WINDOWS.md](DEPLOYMENT_WINDOWS.md): Windows build and robot-PC deployment instructions
