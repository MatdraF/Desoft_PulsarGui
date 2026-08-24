# 🌌 Desoft PulsarGUI

A Python-based graphical application for the initial loading, validation, processing, analysis, and visualization of astronomical data associated with pulsar studies.

---

## Description

**Desoft PulsarGUI** is a desktop application developed in Python that provides a graphical interface for processing and analyzing astronomical data used in pulsar studies.

The application uses:

* **PyQt6** for the graphical user interface.
* **Astropy** for astronomical data processing and FITS file handling.
* **NumPy** for numerical processing and array operations.
* **Matplotlib** for data visualization.
* **Pytest** for automated testing.
* **PINT / fermiphase** for pulsar phase calculation.
* **Git and GitHub** for version control and collaboration.
* **GitHub Actions** for automated testing.

The current version corresponds to the implementation of **Sprint 3**.

---

# Problem

The analysis of pulsar data requires working with different astronomical files, such as `.par` parameter files, photon FITS files, and spacecraft FT2 files.

These tasks may require command-line tools and specific knowledge about the structure, temporal reference, and compatibility of astronomical data files.

**PulsarGUI aims to simplify this process through a graphical interface**, allowing users to:

* Select astronomical data files.
* Validate `.par` parameter files.
* Validate photon FITS files.
* Validate spacecraft FT2 files.
* Check required event and GTI columns.
* Verify temporal metadata compatibility.
* Verify the temporal coverage between PAR, photon FITS, and FT2 files.
* Merge events from multiple FITS files.
* Merge and normalize overlapping or contiguous GTI intervals.
* Visualize the spatial distribution of events using RA–DEC.
* Calculate pulsar phases using `fermiphase`.
* Use the FT2 spacecraft file when required for raw Fermi events.
* Verify the generation of the `PULSE_PHASE` column.
* Generate a phaseogram and pulse profile over two consecutive cycles.

The application therefore provides a graphical layer over the initial stages of the pulsar data-processing workflow.

---

# Installation

## Requirements

The following software is required:

* Python **3.10 or higher**
* Git
* Pip

The Python dependencies are managed through `pyproject.toml` and include:

* `astropy`
* `matplotlib`
* `numpy`
* `PyQt6`
* `pint-pulsar`

Testing dependencies include:

* `pytest`

## Clone the repository

```bash
git clone https://github.com/MatdraF/Desoft_PulsarGui.git
```

Navigate to the project directory:

```bash
cd Desoft_PulsarGui
```

## Create a virtual environment

On Windows:

```powershell
python -m venv .venv
```

Activate the virtual environment:

```powershell
.venv\Scripts\activate
```

If the environment was activated successfully, `(.venv)` will appear at the beginning of the terminal.

## Install the project

The project uses `pyproject.toml` to manage its dependencies.

To install the project and its main dependencies:

```powershell
pip install -e .
```

To install the project together with the testing dependencies:

```powershell
pip install -e ".[test]"
```

---

# Running the Application

With the virtual environment activated, run:

```powershell
python src/PulsarGUI/Pulsargui.py
```

This will launch the **PulsarGUI** graphical application.

The Sprint 3 interface is organized into three main stages:

1. **Input files**
2. **Data preparation**
3. **Analysis**

The application allows users to load PAR, FT2, and photon FITS files, prepare the event dataset, calculate pulsar phases, and generate visualizations.

---

# Running Tests

Automated tests are located in:

```text
tests/
```

To run all tests:

```powershell
pytest
```

Alternatively:

```powershell
python -m pytest
```

The project also includes a **GitHub Actions** workflow for automatically running tests when changes are pushed to the repository.

---

# Examples of Use

## File Validation

The user can load:

* A `.par` parameter file.
* One or more photon FITS files.
* An FT2 spacecraft FITS file.

### PAR validation

The application verifies that:

* The file exists.
* The file is a regular file.
* The extension is `.par`.
* The file is not empty.

### Photon FITS validation

Photon event FITS files must contain the following columns in **HDU 1**:

```text
TIME
RA
DEC
ENERGY
```

The application also verifies that the FITS contains a valid **GTI** extension with:

```text
START
STOP
```

### Spacecraft FT2 validation

The FT2 file must contain:

```text
START
STOP
SC_POSITION
```

`SC_VELOCITY` is also checked and a warning is displayed if it is not present.

---

# FITS Event and GTI Merging

The application can merge events from multiple photon FITS files.

During this process:

* Events from all input files are combined.
* Events are sorted according to `TIME`.
* GTI intervals from the input files are combined.
* Overlapping or contiguous GTI intervals are normalized.
* The Primary HDU from the first file is preserved.
* Relevant FITS headers are preserved.
* Additional extensions from the first FITS file are preserved.
* `TSTART` and `TSTOP` are updated according to the resulting GTI coverage.

The resulting dataset is stored as a temporary FITS file and is used as the input for subsequent analysis.

---

# Temporal Validation

Sprint 3 introduces additional validation of the temporal information contained in the astronomical files.

## Time metadata

The application checks compatibility between the temporal metadata of the input FITS files, including:

```text
TIMESYS
TIMEREF
TIMEUNIT
```

Incompatible temporal metadata between input files prevents the merging process.

## PAR coverage

When `START` and `FINISH` values are available in the `.par` file, the application compares them with the temporal coverage of the photon FITS file.

The result can indicate:

* **OK** — the PAR covers the complete event interval.
* **Partial** — only part of the event interval is covered.
* **None** — the PAR does not cover the events.
* **Unknown** — the available information is insufficient for verification.

---

# FT2 Temporal Coverage

For raw Fermi event data, the application verifies that the spacecraft FT2 file covers the complete temporal interval of the photon FITS file.

The FT2 must cover both:

```text
Minimum event TIME
Maximum event TIME
```

If the FT2 does not cover the complete interval, the phase calculation is not started.

---

# RA–DEC Visualization

The application generates a two-dimensional spatial histogram of the detected events using:

```text
RA
DEC
```

The visualization represents the spatial distribution of the detected photon events.

The histogram uses 200 × 200 bins and displays the number of events in each spatial region.

---

# Pulsar Phase Calculation

When a processed FITS file and a `.par` file are available, the application can calculate pulsar phases using `fermiphase`.

The calculation is executed through a **QThread**, preventing the graphical interface from freezing while the external process is running.

The application determines the temporal reference of the FITS data.

For raw Fermi events with:

```text
TIMESYS = TT
TIMEREF = LOCAL
```

the FT2 spacecraft file is provided to `fermiphase` so that the spacecraft orbit information can be used.

For geocentric or previously barycentric data, the FT2 file is not passed unnecessarily.

After the calculation, the application verifies that the resulting FITS file contains:

```text
PULSE_PHASE
```

The original `TIME` values are preserved.

---

# Phaseogram and Pulse Profile

Sprint 3 adds visualization of the pulsar phase information.

Once a FITS file containing `PULSE_PHASE` is available, the application generates:

* A **phaseogram** showing event phase as a function of time.
* A **pulse profile** showing the number of events as a function of pulse phase.

The phaseogram and profile are displayed over **two consecutive cycles**, from:

```text
0 to 2
```

The second cycle is a visual repetition of the first and does not represent additional physical data.

For visualization, event times are converted to MJD without modifying the original FITS `TIME` column.

---

# Team Members

The project was developed collaboratively by:

- **Matias Fernandez**
- **Ivan Paredes**
- **Adolfo Ceballos**
- **Jhoon Ladera**

## Scrum Team Roles

The responsibilities within the Scrum team are distributed as follows:

- **Product Owner — Ivan Paredes:** responsible for prioritizing the Product Backlog and representing the needs identified with the client.

- **Scrum Master — Matias Fernandez:** responsible for facilitating team organization, Sprint follow-up, and the resolution of impediments.

- **Development Team — Adolfo Ceballos and Jhoon Ladera:** responsible for implementing, integrating, and testing the system's functionalities.

The team uses Git and GitHub for version control, branch management, commits, Pull Requests, and continuous integration through GitHub Actions.
---

# Client

The project was developed under the guidance of:

**Cristóbal Espinoza Romo**

Astrophysicist specializing in **pulsars**, who acts as the project's **client and domain expert**.

The client provides scientific guidance regarding the pulsar data-processing workflow, including the use of `.par` files, photon FITS files, spacecraft FT2 information, and pulsar phase calculations.

His feedback is used to guide functional and scientific decisions and to evaluate the usefulness of the implemented features.

---

# Current Development Status

**PulsarGUI is currently in Sprint 3**, with an expanded implementation of the pulsar data-processing and analysis workflow.

| Feature                                        | Status                 |
| ---------------------------------------------- | ---------------------- |
| `.par` file validation                         | Implemented            |
| Photon FITS validation                         | Implemented            |
| Spacecraft FT2 validation                      | Implemented            |
| HDU 1 column validation                        | Implemented            |
| `TIME`, `RA`, `DEC`, and `ENERGY` verification | Implemented            |
| GTI validation                                 | Implemented            |
| Temporal metadata compatibility                | Implemented            |
| PAR/FITS temporal coverage validation          | Implemented            |
| FT2 temporal coverage validation               | Implemented            |
| EVENTS merging                                 | Implemented            |
| GTI merging and normalization                  | Implemented            |
| RA–DEC 2D histogram                            | Implemented            |
| `fermiphase` integration                       | Implemented            |
| FT2 integration for raw Fermi events           | Implemented            |
| `PULSE_PHASE` verification                     | Implemented            |
| Phaseogram                                     | Implemented            |
| Pulse profile                                  | Implemented            |
| Two-cycle visualization                        | Implemented            |
| External process cancellation                  | Implemented            |
| Temporary file management                      | Implemented            |
| Pytest unit tests                              | Implemented            |
| GitHub Actions                                 | Implemented            |
| Further processing optimization                | Implemented            |

---

# Processing Workflow

The current Sprint 3 workflow can be summarized as follows:

```text
                 ┌──────────────┐
                 │  .par File   │
                 └──────┬───────┘
                        │
                        ▼
                  PAR Validation
                        │
                        │
        ┌───────────────┴────────────────┐
        │                                │
        ▼                                ▼
┌───────────────────┐          ┌───────────────────┐
│ Photon FITS Files │          │ Spacecraft FT2    │
└─────────┬─────────┘          └─────────┬─────────┘
          │                              │
          ▼                              │
    FITS Validation                      │
          │                              │
          ▼                              │
   EVENTS + GTI                         │
      Merging                            │
          │                              │
          ▼                              │
   Processing FITS                      │
          │                              │
          ├───────────────┐              │
          │               │              │
          ▼               ▼              │
     RA–DEC           Temporal           │
    Histogram         Validation         │
                          │              │
                          ▼              │
                     fermiphase ◄────────┘
                          │
                          ▼
                     PULSE_PHASE
                          │
                          ▼
                ┌───────────────────┐
                │   Phaseogram +    │
                │   Pulse Profile   │
                └───────────────────┘
```

The FT2 spacecraft file is required when the input event data uses the raw Fermi temporal reference (`TT/LOCAL`) and is validated to ensure that it covers the event interval.

---

# Project Structure

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
├── DataTest/
│   ├── L2607262307084E8FDC4046_PH01.fits
│   ├── L2607262307084E8FDC4046_SC00.fits
│   └── PSR_J1227.par
│
├── .gitignore
├── .gitattributes
├── README.md
└── pyproject.toml
```

---

# Technologies

| Technology        | Purpose                                        |
| ----------------- | ---------------------------------------------- |
| Python 3.10+      | Main programming language                      |
| PyQt6             | Graphical user interface                       |
| Astropy           | Astronomical data processing and FITS handling |
| NumPy             | Numerical and array processing                 |
| Matplotlib        | Data visualization                             |
| Pytest            | Unit testing                                   |
| PINT / fermiphase | Pulsar phase calculation                       |
| Git               | Version control                                |
| GitHub            | Collaboration and repository hosting           |
| GitHub Actions    | Automated testing and continuous integration   |

---

# Git and Collaboration

The project uses `main` as its main branch.

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

Example workflow:

```text
main
 │
 ├── feature/file-validation
 │
 ├── feature/event-processing
 │
 └── feature/gui
       │
       ▼
   Pull Request
       │
       ▼
      main
```

---

# Current Limitations

Although Sprint 3 implements a substantially more complete processing workflow, some aspects can still be improved:

* Further optimization of processing for large FITS datasets.
* Expansion of automated test coverage.
* Additional validation of astronomical input formats.
* Further improvements to the graphical interface and user feedback.
* Additional analysis and visualization features can be incorporated in future Sprints.

---

# License

This project was developed for academic purposes as part of the **Software Development course**.
