# Third-party notices

## 3Dmol.js

The locally bundled `static/lib/3Dmol-min.js` is from [3Dmol.js](https://3dmol.org/), developed by the University of Pittsburgh and contributors. It is distributed under the BSD 3-Clause license and incorporates other third-party components.

- [Upstream repository](https://github.com/3dmol/3Dmol.js)
- [Upstream license and incorporated-code notices](static/lib/3Dmol.LICENSE)
- [Bundled-code license notices](static/lib/3Dmol-min.js.LICENSE.txt)
- [pako compression library license](static/lib/pako.LICENSE), from [nodeca/pako](https://github.com/nodeca/pako)

The license and bundled-code notices were retrieved from the official upstream sources. The viewer JavaScript itself is preserved from the existing MOPAC Studio project.

## Python dependencies

Flask, Flask-Cors, RDKit, PubChemPy, requests, NumPy and their transitive dependencies are installed separately by pip from `requirements.txt`. Each retains its own upstream license; these packages are not vendored into this repository.

## Automatically downloaded MOPAC

The installer downloads the unmodified official [MOPAC 23.2.5 release](https://github.com/openmopac/mopac/releases/tag/v23.2.5) for Windows/Linux x86-64. MOPAC is distributed under [Apache 2.0](licenses/MOPAC-23.2.5.LICENSE). The downloaded distribution's LICENSE, CITATION.cff, runtime libraries and folder structure are preserved in `_engines/`. Archive URLs and SHA-256 values are pinned in `engine_setup.py`.

The repository itself does not redistribute MOPAC executable/DLL files or license activation information. Downloads come directly from the official upstream release. The bundled Intel/OpenMP runtime remains part of the upstream distribution under its applicable terms.

Legacy MOPAC2016 and optional Avogadro installations are not modified or redistributed by the automatic installer. Explicit `MOPAC_EXE` configuration takes priority over automatic installation.
