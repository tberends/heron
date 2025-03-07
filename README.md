![banner](docs/images/heron.jpg)

# Heron

Dit project, gefinancierd door Digishape Seed Money, richt zich op het inspecteren van waterpeilen met behulp van LiDAR-beelden van drones. Het bevat scripts die .las/.laz bestanden verwerken. Je kunt verschillende filterfuncties toepassen op de .las/.laz bestanden om de gewenste output te verkrijgen. Elke gebruikte functie voegt een afkorting toe die de acties van de functie beschrijft. Meer informatie over het project is te vinden op https://www.digishape.nl/projecten/algoritmische-bepaling-van-waterstanden-met-remote-sensing en een rapport van het project (in het Nederlands) is te vinden in de 'docs' map.

## Functionaliteit

Het script biedt de volgende functionaliteit:

1. **Automatische bestandsverwerking**
   - Verwerkt automatisch alle .las/.laz bestanden in de `data/raw/` directory
   - Ondersteunt zowel .las als .laz formaten
   - Voorkomt dubbele verwerking van bestanden

2. **Filtering opties**
   - **Spatiale filtering**: Filtert punten binnen waterlichamen
   - **Hoogte filtering**: Filtert punten op basis van minimum en maximum waterpeil
   - **Centerline filtering**: Filtert punten rondom een berekende centerline van waterlichamen

3. **Output generatie**
   - Genereert rasterbestanden (.tif) met 1x1m celgrootte
   - Berekent Z-waarden op basis van gemiddelde, mediaan of modus
   - Maakt visualisaties (.png) met waterlichamen en rasterdata
   - Genereert frequentiediagrammen voor specifieke locaties

4. **Logging**
   - Uitgebreide logging van alle verwerkingsstappen
   - Logs worden opgeslagen in de `logs/` directory met timestamp
   - Bevat informatie over verwerking, fouten en resultaten

## Installatie

1. Clone de repository
2. Installeer de vereiste packages:
```bash
pip install -r requirements.txt
```

## Gebruik

Het script kan worden uitgevoerd met verschillende opties:

```python
main(
    filter_geometries=True,      # Filter op waterlichamen
    filter_minmax=False,         # Filter op hoogte
    min_peil=-1,                # Minimum waterpeil
    max_peil=1,                 # Maximum waterpeil
    filter_centerline=True,     # Filter op centerline
    dist_centerline=2,          # Afstand tot centerline in meters
    raster_averaging_mode="mode", # Berekening raster (mode/mean/median)
    create_tif=True,            # Genereer TIF bestanden
    frequencydiagram=False,     # Genereer frequentiediagram
    coordinates=(126012.5, 500481) # Locatie voor frequentiediagram
)
```

## Directory structuur

```
heron/
├── data/
│   ├── raw/           # Input .las/.laz bestanden
│   └── output/        # Output bestanden (.tif, .png)
├── logs/              # Log bestanden
├── src/               # Broncode
│   ├── filter_spatial.py
│   ├── filter_functions.py
│   ├── generate_raster.py
│   ├── get_waterdelen.py
│   ├── plot_frequency.py
│   └── chunk_files.py
└── main.py           # Hoofdscript
```

## Module beschrijvingen

### src/filter_spatial.py
- `filter_spatial(points, waterdelen)`: Filtert punten binnen waterlichamen

### src/filter_functions.py
- `filter_by_z_value(points, min_peil, max_peil)`: Filtert punten op basis van hoogte
- `filter_by_proximity_to_centerline(points, centerline, distance)`: Filtert punten rondom centerline

### src/generate_raster.py
- `generate_raster(points, mode)`: Genereert raster van punten met verschillende berekeningsmethoden

### src/get_waterdelen.py
- `get_waterdelen(bbox)`: Haalt waterlichamen op via PDOK API

### src/plot_frequency.py
- `plot_frequency(points, coordinates, filename)`: Genereert frequentiediagram voor specifieke locatie

### src/chunk_files.py
- Functies voor het opsplitsen van grote bestanden in kleinere delen

## Output bestanden

Het script genereert de volgende output bestanden:
- `*.tif`: Rasterbestanden met gefilterde punten
- `*.png`: Visualisaties van de resultaten
- `*.log`: Log bestanden met verwerkingsinformatie

## Logging

Alle verwerkingsstappen worden gelogd met:
- Timestamp
- Log level (INFO/WARNING/ERROR)
- Gedetailleerde berichten
- Bestandsnamen en verwerkingsresultaten

## Afhankelijkheden

- numpy
- pandas
- geopandas
- laspy
- contextily
- matplotlib
- pyproj
