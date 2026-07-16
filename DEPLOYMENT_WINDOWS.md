# IPQC Windows Deployment

## Build computer prerequisites

- Windows 64-bit.
- Python 3.14.x used for the current build.
- No PyCharm required.
- Build from the repository root.

Exact build command:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
```

The build script creates an isolated `.build-venv`, installs runtime and build dependencies, and packages the app with PyInstaller `--onedir`.

## Build output

Expected release folder:

```text
dist/IPQC/
```

Expected contents include:

- `IPQC.exe`
- `_internal/`
- `config/node_motion_calibration.xml`
- `data/logs/`
- `data/exports/`
- `data/config/`
- `data/config/project_configs/`
- `RELEASE_INFO.txt`
- `SHA256SUMS.txt`

The release manifest records:

- application version
- build timestamp
- Python version used to build
- PyInstaller version
- build architecture
- target architecture when available
- Git commit when available from the environment

## Robot PC deployment

Copy the entire folder:

```text
dist/IPQC/
```

Do not copy only `IPQC.exe`; the `_internal/` folder and bundled resources are required.

Recommended target location:

```text
C:\IPQC\
```

Preserve the whole folder when updating so `data/` can be migrated or backed up safely.

## Runtime folders

Runtime data is created beside the executable inside `data/`:

```text
data/logs/
data/exports/
data/config/
data/config/project_configs/
```

These folders are created automatically on first launch when missing.

- Communication logs and runtime log files go under `data/logs/`.
- Workbook exports and other operator-facing exports go under `data/exports/`.
- Writable configuration and copied defaults go under `data/config/`.

The app does not write editable runtime data into PyInstaller `_internal/`.

The bundled node motion calibration file is loaded automatically from:

```text
config/node_motion_calibration.xml
```

Negative `CountsPerUnit` values are valid and record encoder polarity metadata. Expected full-range counts use `SoftwareRange * abs(CountsPerUnit)`. Restart the application after editing the XML. Sampling consumption remains future CAL-0B work and UI/error plotting remains future CAL-0C work.

## Launch

Launch:

```text
IPQC.exe
```

No Python, pip, or PyCharm is required on the robot PC.

The application does not auto-connect to a COM port or send robot commands on startup.

## Update and rollback

Safe update flow:

1. Close the running application.
2. Back up the existing `data/` folder if you want to preserve logs, exports, or operator config.
3. Replace the release folder with the new `dist/IPQC/` contents.
4. Restore `data/` if needed.

Rollback:

1. Keep the previous release folder unchanged.
2. Restore the prior `dist/IPQC/` copy if the new release must be reverted.

Do not overwrite `data/` unless you intentionally want to reset logs, exports, or config.

## External robot-PC dependencies

Not bundled:

- USB-to-UART / CAN adapter driver, if the adapter requires one.
- Any vendor-specific device driver for the adapter.
- Windows COM-port access.
- Microsoft Visual C++ runtime only if the built executable reports it as missing on the target machine.

Operational notes:

- COM port numbers are not assumed fixed.
- The operator must select and verify the correct COM port.
- Missing or disconnected COM ports should be handled without crashing the app.

## Acceptance checklist

- [ ] App starts without Python/PyCharm installed
- [ ] App does not auto-connect or send commands on launch
- [ ] COM ports enumerate correctly
- [ ] Connect/disconnect works
- [ ] Missing/disconnected COM port does not crash the app
- [ ] Node discovery works
- [ ] Firmware/version reads work
- [ ] Workbook load works
- [ ] Operator/Assembler metadata entry works
- [ ] Parameter verify works
- [ ] Parameter write and EEPROM-save behavior works
- [ ] Single Axis starts and stops safely
- [ ] Sampling starts and stops safely
- [ ] Stop/Abort sends existing stop behavior correctly
- [ ] Communication log viewer works
- [ ] Logs and exports are written successfully
- [ ] App restarts cleanly after failed connection/device reconnect
- [ ] Completed workbook can be saved/downloaded

## Notes

- The build is intended for copying one complete `dist/IPQC/` folder to the robot PC.
- Hardware behavior was not validated here; validate serial/CAN-over-UART operation only on the target robot PC with the actual device connected.
