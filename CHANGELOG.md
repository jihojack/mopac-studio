# Changelog

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
