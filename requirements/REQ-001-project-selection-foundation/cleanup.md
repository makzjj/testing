# REQ-001 Code Cleanup Report

> Status: Code Cleaned
> Requirement: requirement.md
> Technical Design: technical.md
> Cleaned: 2026-04-01

## 1. Applied Changes

| # | Category | Location | Action | Detail |
|:---|:---|:---|:---|:---|
| C-01 | Unused parameter | `gui/program_selector_window.py` | Renamed | `paintEvent(..., event)` changed to `paintEvent(..., _event)` |
| C-02 | Over-wrapping | `gui/program_selector_window.py` | Inlined | Removed one single-use tooltip helper and kept the same tooltip behavior inside `_reload_projects()` |
| C-03 | Duplicate test setup | `tests/test_project_loader.py` | Extracted | Moved repeated temporary config loading logic into `_load_projects_from_dir()` |
| C-04 | Duplicate script coupling | `scripts/build.bat`, `scripts/run.bat`, `scripts/test.bat` | Normalized | Replaced repeated absolute interpreter path usage with a shared per-script relative `%PYTHON_EXE%` |

## 2. Statistics

- Unused code removed: 1 item
- Duplicate code merged: 2 items
- Module restructured: 0 items
- Net lines reduced: small cleanup with no behavior change

## 3. Cohesion & Coupling Assessment

- Module cohesion: improved slightly
  - selector state update remains UI-focused
  - test helper setup is more localized
  - batch scripts are less tied to one absolute machine path
- Module coupling: improved slightly
  - REQ-001 Windows helper scripts now rely on repository-relative `.venv` lookup
- Circular dependencies: none detected in REQ-001 scope

## 4. Behavior Impact

- Public API changes: **None**
- Business logic changes: **None**
- All changes are purely structural
