hhnk-drone-inspection
==============================
Inspection of waterlevels using LiDAR images from drones.

The scripts processes a .las/.laz file. Several functions filtering the .las/.laz can be called
to acquire the desired output of the file. If a function is used it adds an abbrevation
describing the function actions.

### Step 1
load .las/laz file
- copy .las/.laz file to data/raw
- define name las file
- define extension (.las/.laz)
- define coördinate reference system

load in geometries
- define geometries in data/exterma;

### Step 2 choose filter option
Define which filter functions will be applies to the point cloud


### Step 3: execute functions
Execution of defines functions

### step 4: write outpout to file(s)
Processed file is written to a .csv file in data/processed
if create_tif = True a tif is created and stored in data/tifs



Project Organization
------------

    ├── LICENSE
    ├── Makefile           <- Makefile with commands like `make data` or `make train`
    ├── README.md          <- The top-level README for developers using this project.
    ├── data
    │   ├── external       <- Data from third party sources.
    │   ├── tifs	       <- Intermediate data that has been transformed.
    │   ├── processed      <- The final, canonical data sets for modeling.
    │   └── raw            <- The original, immutable data dump.
    │
    ├── docs               <- A default Sphinx project; see sphinx-doc.org for details
    │
    ├── references         <- Data dictionaries, manuals, and all other explanatory materials.
    │
    ├── reports            <- Generated analysis as HTML, PDF, LaTeX, etc.
    │   └── figures        <- Generated graphics and figures to be used in reporting
    │
    ├── requirements.txt   <- The requirements file for reproducing the analysis environment, e.g.
    │                         generated with `pip freeze > requirements.txt`
    │
    ├── setup.py           <- makes project pip installable (pip install -e .) so src can be imported
    ├── src                <- Source code for use in this project.
    │   ├── __init__.py    <- Makes src a Python module
    │   │
    │   ├── data           <- Scripts to download or generate data
    │   │   └── make_dataset.py
    │   │
    │   ├── features       <- Scripts to turn raw data into features for modeling
    │   │   └── build_features.py
    │   │
    │   ├── models         <- Scripts to train models and then use trained models to make
    │   │



--------

<p><small>Project based on the <a target="_blank" href="https://drivendata.github.io/cookiecutter-data-science/">cookiecutter data science project template</a>. #cookiecutterdatascience</small></p>
