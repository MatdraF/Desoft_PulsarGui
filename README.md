# 🌌 Desoft PulsarGUI

**Desoft PulsarGUI** is a Python-based graphical application for the initial loading, validation, processing, and visualization of astronomical data associated with pulsar studies.

The project uses **PyQt6** for the graphical interface, **Astropy** for astronomical data processing, and **Matplotlib** for data visualization. It also includes an initial integration with **PINT/fermiphase** for pulsar event phase calculations.

## Client

The project was developed under the guidance of **Cristóbal Espinoza Romo**, an astrophysicist specializing in pulsars.

He was assigned as the project's client and domain expert, providing guidance regarding the astronomical requirements and the pulsar data-processing workflow that the application is intended to support.

The development of PulsarGUI follows the requirements, objectives, and feedback provided throughout the Software Development course.


##  Sprint 2

During Sprint 2, a partial data-processing workflow was implemented, including file validation, event processing, spatial visualization, and initial integration with `fermiphase`.

### Implemented Features

*  Loading and validation of `.par` parameter files.
*  Loading and validation of photon FITS files.
*  Optional spacecraft FITS file loading.
*  Validation of HDU 1 columns.
*  Verification of required columns:

  * `TIME`
  * `RA`
  * `DEC`
  * `ENERGY`
*  Preliminary merging of events from multiple FITS files.
*  Generation of a 2D `RA–DEC` histogram.
*  Initial integration with `fermiphase`.
*  Execution of `fermiphase` using `QThread` to prevent the GUI from freezing.
*  Verification of the `PULSE_PHASE` column.
*  Initial unit tests using Pytest.
*  Initial GitHub Actions configuration.

---
## Problem

PulsarGUI addresses the need for a graphical interface that simplifies
the initial validation, processing, and visualization of astronomical
data used in pulsar studies.

The application reduces the need for users to interact directly with
command-line tools during the initial stages of the data-processing
workflow.
---

##  Technologies

* **Python 3.10+**
* **PyQt6** — graphical user interface.
* **Astropy** — FITS file reading and astronomical data processing.
* **Matplotlib** — data visualization.
* **Pytest** — unit testing.
* **PINT / fermiphase** — pulsar phase processing.
* **Git / GitHub** — version control and collaboration.
* **GitHub Actions** — automated testing.

---

##  Project Structure

```text
Desoft_PulsarGui/
│
├── .github/
│   └── workflows/
│       └── pruebas.yml
│
├── src/
│   └── PulsarGUI/
│       ├── __init__.py
│       └── Pulsargui.py
│
├── tests/
│   ├── test_basico.py
│   └── test_pytest.py
│
├── docs/
│   └── ...
│
├── DataTest/
│   ├── L2607262307084E8FDC4046_PH01.fits
│   └── L2607262307084E8FDC4046_SC00.fits
│   └── PSR_J1227.par
├── .gitignore
├── .gitattributes
├── README.md
└── pyproject.toml
```

---

#  Installation

## 1. Clone the repository

```bash
git clone https://github.com/MatdraF/Desoft_PulsarGui.git
```

Navigate to the project directory:

```bash
cd Desoft_PulsarGui
```

---

## 2. Create a virtual environment

It is recommended to use a Python virtual environment to keep the project dependencies isolated.

On Windows:

```powershell
python -m venv .venv
```

Activate the environment:

```powershell
.venv\Scripts\activate
```

If the environment was activated successfully, `(.venv)` will appear at the beginning of the terminal.

---

## 3. Install the project and dependencies

The project uses `pyproject.toml` to manage its dependencies.

To install the main dependencies:

```powershell
pip install -e .
```

To install the project together with the testing dependencies:

```powershell
pip install -e ".[test]"
```

---

#  Running the Application

With the virtual environment activated, run:

```powershell
python src/PulsarGUI/Pulsargui.py
```

This will launch the:

```text
PulsarGUI - Sprint 2
```

graphical interface.

The application allows users to load the required files and execute the processing features implemented during Sprint 2.

---

#  Testing

Unit tests are located in:

```text
tests/
```

To run the tests:

```powershell
pytest
```

Alternatively:

```powershell
python -m pytest
```

The project also includes an initial **GitHub Actions** workflow that automatically runs the tests when changes are pushed to the repository.

---

#  Processing Workflow

The main workflow implemented during Sprint 2 is:

```text
             ┌──────────────┐
             │  .par File   │
             └──────┬───────┘
                    │
                    ▼
              PAR Validation
                    │
                    │
┌───────────────────▼──────────────────┐
│         Photon FITS Files            │
└───────────────────┬──────────────────┘
                    │
                    ▼
               FITS Validation
                    │
                    ▼
             Event Merging
                    │
                    ▼
          Processing FITS File
                    │
          ┌─────────┴─────────┐
          │                   │
          ▼                   ▼
     RA–DEC Histogram     fermiphase
                              │
                              ▼
                       PULSE_PHASE
```

The spacecraft FITS file is optional in the current version.

---

#  Main Features

## File Validation

The application performs basic checks to ensure that selected files are valid and suitable for processing.

Photon FITS files must contain the following columns:

```text
TIME
RA
DEC
ENERGY
```

The application also checks that the required data are located in HDU 1.

## Event Merging

The application can preliminarily merge event tables from multiple FITS files.

The current implementation:

* Preserves the primary HDU from the first file.
* Preserves the event table header.
* Preserves additional extensions from the first FITS file.
* Does not merge GTI extensions from additional files.

## Data Visualization

A 2D spatial histogram is generated using:

```text
RA
DEC
```

This provides a visual representation of the spatial distribution of the detected events.

## Phase Calculation

The application builds and executes the `fermiphase` command using the selected FITS and `.par` files.

The process runs inside a `QThread` so that the graphical interface remains responsive while the calculation is running.

---

#  Sprint 2 Limitations

The current implementation is partial.

* GTI extensions from additional FITS files are not merged.
* The spacecraft FITS file is not yet used for automatic barycentric correction.
* The `fermiphase` integration is still in an initial stage.
* A complete phaseogram is not yet implemented.
* The pulse profile is not yet implemented.
* Full processing optimization is planned for future Sprints.

---

#  Git and Collaboration

The project uses Git and GitHub for version control and collaborative development.

The main branch is:

```text
main
```

New features should preferably be developed in separate branches:

```powershell
git switch -c feature/feature-name
```

After making changes:

```powershell
git add .
git commit -m "Description of the change"
git push
```

Completed features can be integrated into `main` through a **Pull Request**.

### Development Workflow

```text
main
 │
 ├──── feature/file-validation
 │
 ├──── feature/event-processing
 │
 └──── feature/gui
             │
             ▼
       Pull Request
             │
             ▼
            main
```

---

# Changes from Sprint 1

The following improvements were introduced during Sprint 2:

* `.par` file validation.
* FITS file validation.
* Event column validation.
* Preliminary FITS event merging.
* `RA–DEC` spatial histogram.
* Initial PINT/fermiphase integration.
* Background processing using `QThread`.
* `PULSE_PHASE` verification.
* Additional unit tests.
* Initial GitHub Actions configuration.
* Expanded graphical interface.

---

#  Sprint 2 Status

| Feature                          | Status        |
| -------------------------------- | ------------- |
| PAR file validation              |  Implemented |
| Photon FITS validation           |  Implemented |
| Spacecraft FITS validation       |  Implemented |
| Preliminary event merging        |  Implemented |
| RA–DEC histogram                 |  Implemented |
| fermiphase integration           |  Partial    |
| PULSE_PHASE                      |  Partial    |
| Automatic barycentric correction |  Pending     |
| Complete phaseogram              |  Pending     |
| Pulse profile                    |  Pending     |
| Processing optimization          |  Pending     |

---

#  Collaboration

The project uses:

* Git
* GitHub
* Branches
* Commits
* Pull Requests
* GitHub Actions

This workflow provides version control, traceability of changes, and organized collaboration between team members.

---
## Team

This project was developed collaboratively by:

* **Matias Fernandez**
* **Ivan Paredes**
* **Adolfo Ceballos**
* **Jhoon Ladera**

The team uses Git and GitHub for version control, collaborative development, branch management, commits, Pull Requests, and continuous integration through GitHub Actions.

---

# 📄 License

This project was developed for academic purposes as part of the Software Development course.
