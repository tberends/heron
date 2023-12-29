hhnk-drone-inspection
==============================

![banner](docs/images/banner.jpg)


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
Processed file is written to a .csv file in data/processed.

if create_tif = True a tif is created and stored in data/tifs.
