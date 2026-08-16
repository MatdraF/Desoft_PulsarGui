# 🌌 Desoft PulsarGUI

A Python-based graphical application for the initial loading, validation, processing, and visualization of astronomical data associated with pulsar studies.

---

##  Description

**Desoft PulsarGUI** is a desktop application developed in Python that provides a graphical interface for the initial stages of processing astronomical data used in pulsar studies.

The application uses:

* **PyQt6** for the graphical user interface.
* **Astropy** for astronomical data processing and FITS file handling.
* **Matplotlib** for data visualization.
* **Pytest** for automated testing.
* **PINT / fermiphase** for the initial calculation of pulsar event phases.
* **Git and GitHub** for version control and collaboration.
* **GitHub Actions** for automated testing.

The current version corresponds to the partial implementation of **Sprint 2**.

---

#  Problem

The initial analysis of pulsar data requires working with different astronomical files, such as `.par` parameter files and FITS files containing photon events.

These tasks may require command-line tools and specific knowledge about the structure of astronomical data files.

**PulsarGUI aims to simplify this process through a graphical interface**, allowing users to:

* Select astronomical data files.
* Validate `.par` parameter files.
* Validate FITS files.
* Check the required event columns.
* Merge events from multiple FITS files.
* Visualize the spatial distribution of events.
* Run the initial `fermiphase` processing.
* Verify the generation of the `PULSE_PHASE` column.

The application therefore provides a graphical layer over the initial stages of the pulsar data-processing workflow.

---

# Installation

## Requirements

The following software is required:

* Python **3.10 or higher**
* Git
* Pip

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

This will launch the graphical application:

```text
PulsarGUI - Sprint 2
```

The application allows users to load the required files and execute the processing and visualization features implemented during Sprint 2.

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

The project also includes an initial **GitHub Actions** workflow that automatically runs the tests when changes are pushed to the repository.

---

# Examples of Use

## File Validation

The user can load a `.par` parameter file and one or more photon FITS files.

Photon event FITS files must contain the following columns in **HDU 1**:

```text
TIME
RA
DEC
ENERGY
```

The application verifies that these required columns are present before continuing with the processing workflow.

---

## FITS Event Merging

The application can preliminarily merge event tables from multiple photon FITS files.

The current implementation:

* Preserves the Primary HDU from the first file.
* Preserves the event table header.
* Preserves additional extensions from the first FITS file.
* Does not merge GTI extensions from additional files.

---

## RA–DEC Visualization

The application can generate a two-dimensional spatial histogram using:

```text
RA
DEC
```

This visualization provides a representation of the spatial distribution of detected events.

---

## Pulsar Phase Calculation

When a `.par` file and a processed FITS file are available, the application can run `fermiphase` to calculate the event phases.

The process is executed using a **QThread**, preventing the graphical interface from freezing while the calculation is running.

The application then verifies the presence of the:

```text
PULSE_PHASE
```

column.

---

# Team Members

This project was developed collaboratively by:

* **Matias Fernandez**
* **Ivan Paredes**
* **Adolfo Ceballos**
* **Jhoon Ladera**

The team uses Git and GitHub for version control, branch management, commits, Pull Requests, and continuous integration through GitHub Actions.

---

# Client

The project was developed under the guidance of:

**Cristóbal Espinoza Romo**

Astrophysicist specializing in **pulsars**, who acts as the project's **client and domain expert**.

The client provides guidance regarding the astronomical requirements and the pulsar data-processing workflow that the application is intended to support.

The development of PulsarGUI follows the requirements, objectives, and feedback provided throughout the Software Development course.

---

# Current Development Status

**PulsarGUI is currently in Sprint 2**, with a partial implementation of the initial pulsar data-processing workflow.

| Feature                                        | Status                 |
| ---------------------------------------------- | ---------------------- |
| `.par` file validation                         | Implemented            |
| Photon FITS validation                         | Implemented            |
| Spacecraft FITS validation                     | Implemented            |
| HDU 1 column validation                        | Implemented            |
| `TIME`, `RA`, `DEC`, and `ENERGY` verification | Implemented            |
| Preliminary FITS event merging                 | Implemented            |
| RA–DEC 2D histogram                            | Implemented            |
| `fermiphase` integration                       | Partial                |
| `PULSE_PHASE` verification                     | Partial                |
| Pytest unit tests                              | Implemented            |
| GitHub Actions                                 | Initial implementation |
| Automatic barycentric correction               | Pending                |
| Complete GTI merging                           | Pending                |
| Complete phaseogram                            | Pending                |
| Pulse profile                                  | Pending                |
| Processing optimization                        | Pending                |

---

# Processing Workflow

The current Sprint 2 workflow can be summarized as follows:

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

| Technology        | Purpose                                      |
| ----------------- | -------------------------------------------- |
| Python 3.10+      | Main programming language                    |
| PyQt6             | Graphical user interface                     |
| Astropy           | Astronomical data processing                 |
| Matplotlib        | Data visualization                           |
| Pytest            | Unit testing                                 |
| PINT / fermiphase | Pulsar phase calculation                     |
| Git               | Version control                              |
| GitHub            | Collaboration and repository hosting         |
| GitHub Actions    | Automated testing and continuous integration |

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

The current Sprint 2 implementation has several limitations:

* GTI extensions from additional FITS files are not merged.
* The spacecraft FITS file is not yet used for automatic barycentric correction.
* The `fermiphase` integration is still in an initial stage.
* A complete phaseogram has not yet been implemented.
* The pulse profile has not yet been implemented.
* Processing optimization is planned for future Sprints.

---

# License

This project was developed for academic purposes as part of the **Software Development course**.

