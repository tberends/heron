""" 
This script reads a las file and extracts the points that are within a polygon
written by: Thomas Berends, March 2023
"""
import json
import numpy as np
import pandas as pd
import laspy
import open3d as o3d
from shapely.geometry import shape, Point, MultiPolygon, Polygon, box
from shapely.strtree import STRtree
import matplotlib.pyplot as plt

# read las file
# las = laspy.read("data/raw/X127500Y502000.laz")  # small size
las = laspy.read("data/raw/X125500Y499500.laz")  # medium size
# las = laspy.read("data/raw/X125500Y500000.laz") # large size
print(las)

print(las.header)
print(las.header.point_format)
print(las.header.point_count)
print(las.vlrs)

print(list(las.point_format.dimension_names))

print(las.X)
print(las.intensity)
print(las.gps_time)

print(set(list(las.classification)))

# Make a 3D point cloud from the las file
point_data = np.stack([las.X, las.Y, las.Z], axis=0).transpose((1, 0))
geom = o3d.geometry.PointCloud()
geom.points = o3d.utility.Vector3dVector(point_data)
o3d.visualization.draw_geometries([geom])

# open waterdelen geojson file and with encoding utf-8
with open("data/external/bgt_waterdeel.geojson", encoding="utf-8") as f:
    js = json.load(f)

# create a polygon objects from the geojson file
waterbodies = []
for i in range(len(js["features"])):
    waterbodies.append(shape(js["features"][i]["geometry"]))
# print(waterbodies)

# open peilgebieden geojson file and with encoding utf-8
with open("data/external/peilgebieden_purmer.geojson", encoding="utf-8") as f:
    js = json.load(f)

peilgebieden = []
for i in range(len(js["features"])):
    peilgebieden.append(shape(js["features"][i]["geometry"]))
# print(peilgebieden)

# make waterbodies into a multipolygon and make a vadid geometry
waterbodies2 = MultiPolygon(waterbodies)
waterbodies2 = waterbodies2.buffer(0)

# use STRTREE to find the point based on Las.x and Las.y that are within the waterbodies
# and store the node ids, peilgebied en las.X, las.Y, las.Z and las.intensity,
# las.number_of_returns, las.gps_time, las.classification in a pandas dataframe
# df_las = pd.DataFrame(
#     columns=[
#         "X",
#         "Y",
#         "Z",
#         "intensity",
#         "number_of_returns",
#         "gps_time",
#         "classification",
#         "node_id",
#         "peilgebied",
#     ]
# )
# tree = STRtree(waterbodies)
# tree_pg = STRtree(peilgebieden)
# print("Total points: ", len(las.X))
# for i, point in enumerate(las.X):
#     point = Point(las.X[i] / 1000, las.Y[i] / 1000)
#     if tree.query(point, predicate="within").any():
#         if tree_pg.query(point, predicate="within").any():
#             new_row = pd.DataFrame(
#                 {
#                     "X": las.X[i] / 1000,
#                     "Y": las.Y[i] / 1000,
#                     "Z": las.Z[i] / 1000,
#                     "intensity": las.intensity[i],
#                     "number_of_returns": las.number_of_returns[i],
#                     "gps_time": las.gps_time[i],
#                     "classification": las.classification[i],
#                     "node_id": i,
#                     "peilgebied": tree_pg.query(point, predicate="within")[0],
#                 },
#                 index=[0],
#             )
#             df_las = pd.concat([df_las, new_row], ignore_index=True)
#     if i % 100000 == 0:
#         print(f"{i} points checked")
# # print first 5 rows of the dataframe
# print(df_las.head())

# # write the dataframe to a csv file
# df_las.to_csv("data/processed/df_las.csv", index=False)

# read csf file as dataframe
df_las = pd.read_csv("data/processed/df_las.csv")

# make a fequency table of the las.Z values per peilgebied and las.classification
df_las["node_id"] = df_las["node_id"].astype(int)
df_las["Z"] = df_las["Z"].astype(int)
df_las["peilgebied"] = df_las["peilgebied"].astype(str)
df_las["classification"] = df_las["classification"].astype(int)
df_las_freq = pd.crosstab(df_las["peilgebied"], df_las["classification"])
print(df_las_freq.head())

# print amount of las.Z values of dataframe df_las
print(len(df_las))

# group the las.Z values per peilgebied and las.classification
# and remove the 5% highest and lowest values  per peilgebied and las.classification
# and store the result in a ungrouped dataframe
# df_las = df_las.groupby(["peilgebied", "classification"]).apply(
#     lambda x: x.nlargest(int(len(x) * 0.95), "Z")
# )
# df_las.reset_index(drop=True, inplace=True)
# df_las = df_las.groupby(["peilgebied", "classification"]).apply(
#     lambda x: x.nsmallest(int(len(x) * 0.95), "Z")
# )
# df_las.reset_index(drop=True, inplace=True)
print(df_las.head())
# print amount of las.Z values of dataframe df_las
print(len(df_las))

# calculate the mean and standard deviation of the las.Z values and add both to the df_las dataframe
df_las_mean = df_las.groupby(["peilgebied", "classification"]).mean()
df_las_std = df_las.groupby(["peilgebied", "classification"]).std()

# merge the frequency table, mean and standard deviation based on peilgebied and classification
df_merge = pd.merge(
    df_las_mean,
    df_las_std,
    on=["peilgebied", "classification"],
    how="outer",
    suffixes=("", "_right"),
)
# rename column Z_right to Z_std
df_merge.rename(columns={"Z_right": "Z_std"}, inplace=True)
# remove columns with suffix _right
df_merge = df_merge.loc[:, ~df_merge.columns.str.endswith("_right")]
print(df_merge.head())
df_merge.to_csv("data/processed/df_merge.csv")

# plot the frequency table
df_las_freq.plot(kind="bar", stacked=True)
plt.savefig("reports/figures/barplot.png")

# create a new las file with only the points within the polygon and write it to disk
water = laspy.create(
    point_format=las.header.point_format, file_version=las.header.version
)
water.points = las.points[df_las["node_id"].values]
water.write("data/processed/water.las")

point_data = np.stack([water.X, water.Y, water.Z], axis=0).transpose((1, 0))
geom = o3d.geometry.PointCloud()
geom.points = o3d.utility.Vector3dVector(point_data)
o3d.visualization.draw_geometries([geom])

# plot polygon
fig, ax = plt.subplots()
# plot shapely multipolygon object polygon_sb using for loop
for waterbody in waterbodies:
    ax.plot(*waterbody.exterior.xy, color="blue")
ax.plot(las.X / 1000, las.Y / 1000, "ro")
ax.plot(water.X / 1000, water.Y / 1000, color="yellow")
ax.set_aspect("equal")
# write plot to disk in folder reports/figures
plt.savefig("reports/figures/map_laspoint.png")
# plt.show()

# buildings = laspy.create(
#     point_format=las.header.point_format, file_version=las.header.version
# )
# buildings.points = las.points[las.classification == 6]

# buildings.write("data/processed/buildings.las")
