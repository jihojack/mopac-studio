# Changelog

## 3.3.1 — 2026-10-25

- Expand both 3D-editor element selectors to all 118 elements with Korean names and atomic numbers from shared element data.
- Separate the 70 standard PM7 elements from display/edit-only entries and reject unsupported calculation symbols instead of invoking special sparkle/dummy meanings.
- Avoid implicit hydrogen addition to newly exposed elements; retain explicit hydrogens when reopening metal-containing structures.
- Keep isolated atoms visible after Apply and extend XYZ element-number/formula handling through Og.
- Preserve existing organic valence validation and recoverable force-field failures.

## 3.3.0 — 2026-10-25

- Add multi-file drag-and-drop and file selection with separate MOPAC batch options.
- Calculate files sequentially, expand all SDF records, isolate duplicate names and continue after file/calculation failures.
- Preserve the current viewer, editor draft, coordinates, undo history and result cards.
- Report progress, preserve completed results on cancellation and automatically export a summary plus original inputs and full calculation outputs as ZIP.
- Keep jobs active through parsing/export to prevent native-window or idle shutdown; restore saved job status on page reload.
- Ignore staging files and tolerate concurrent file renames during workspace refresh.

## 3.2.0 — 2026-10-25

- Add ZIP/XYZ/MOL/SDF/JSON/CSV/PNG export without embedding, hydrogen addition or coordinate optimization.
- Include displayed result tables, current 3D-view image and optional raw calculation files in ZIP bundles.
- Preserve full-precision graph/coordinates and draft state in JSON; reopen it from the file list.
- Allow quick-saving drafts while editing; keep selection, undo history and the editor open.
- Add workspace, result-folder and saved-export folder buttons.
- Add optional Windows/WebView2 app-window launchers using pywebview, without browser tabs or a persistent console.
- Stop the app-owned server when its window exits and prevent closure during active calculations.
- Add exporter, download/restore, folder-opening, app lifecycle and browser regressions.

## 3.1.0 — 2026-10-25

- Automatically download official MOPAC 23.2.5 during Install/Start on Windows and Linux x86-64; preserve upstream licenses, citations and runtime layout.
- Pin release URLs and official SHA-256 digests, verify downloads before extraction and reuse intact local installations without network access.
- Detect corrupted engine files, reinstall safely and retain the old copy separately.
- Honor explicit `MOPAC_EXE` configuration; add `--no-engine` for editor-only/offline use. Keep existing MOPAC2016 installations untouched.
- Prefer the managed official engine over implicit legacy portable locations.
- Run modern command-line MOPAC without the legacy Windows GUI desktop/window-hiding helpers.
- Add offline installer/repair tests and real-engine API integration tests for geometry, energy, charges, dipole, vibrations and disconnected-system HOMO/LUMO generation.
- Run official-engine installation and integration tests in Windows/Linux CI.

## 3.0.1 — 2026-10-25

### Installation and distribution

- Add a project-local `.venv` installer and foreground/background launchers.
- Pin application dependencies and document Python 3.11~3.13 on Windows.
- Configure the external MOPAC executable with `MOPAC_EXE`; retain the existing sibling `mopac2016` layout and add PATH discovery.
- Allow optional `AVOGADRO_EXE` configuration.
- Add installation, usage, troubleshooting and multiple-molecule orbital explanations.
- Include upstream viewer notices, regression tests and GitHub Actions.
- Exclude user calculations, logs, backups, virtual environments and machine-specific validation records from Git.

### Molecular editing and orbital fixes

- Preserve atom/bond graphs, coordinates, selection, undo history and camera when closing and reopening the 3D editor.
- Run MMFF/UFF on independent copies; reject partial, failed, non-converged or non-finite optimization results.
- Preserve user-supplied atom coordinates during hydrogen addition and explicitly warn when optional hydrogen refinement fails.
- Ignore stale asynchronous results after closing/reopening or changing the draft.
- Retain coordinate input precision.
- Use matching Angstrom coordinates for Cube grids and orbital models.
- Fix accidental shadowing of atomic number by spatial Z in the Cube API, including the negative-value conversion failure and incorrect element symbols at zero/positive Z.

Actual engine calculations were validated in the original Windows/MOPAC2016 environment. Automated tests cover geometry processing, recovery, Cube units/coordinates and API behavior without requiring a MOPAC executable. Full scientific accuracy and compatibility with every modern MOPAC output are not established by these tests.
