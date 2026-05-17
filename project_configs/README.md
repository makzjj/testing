# Project Config Folder

Put project YAML files here.

Supported file extensions:

- `.yaml`
- `.yml`

The selector scans this folder and treats each YAML file as one project.

Current behavior:

- number of projects shown in the selector = number of YAML files in this folder
- selector labels come from YAML metadata
- the existing runtime still opens the current `MainWindow`

Phase 1 currently consumes only the minimal selector-facing metadata:

- `project`
- `system.axes`
- `features`
- `ui`

Richer sections are still allowed so project YAML files can gradually move closer to real system configs.

`ACCuESS.yaml` is seeded from the legacy `OFC-04-00.xml` structure as a migration reference.
