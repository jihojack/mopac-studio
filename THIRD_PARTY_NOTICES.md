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

## External programs

MOPAC and Avogadro executables, runtime libraries, activation information, and license files are not distributed with this project. Obtain them from their respective official distributions and follow the applicable terms.
