"""Small helper to read elevation from local GeoTIFF rasters if available.

This module will look for a `rasters_COP30.tar` archive in the geo folder and
extract it to a `rasters/` subdirectory the first time it runs. If `rasterio`
is installed it will open any TIFFs found and expose `sample_elevation(lat,
lon)` which returns elevation in metres or `None` when no data is available.

The code is defensive: if `rasterio` is not installed or the rasters are
missing/corrupted it simply sets `AVAILABLE = False` so callers can fall back
to the remote elevation API.
"""
from pathlib import Path
import tarfile
import logging
from typing import Optional

logger = logging.getLogger("vncrcc.geo.raster_elevation")

GEO_DIR = Path(__file__).parent
ARCHIVE = GEO_DIR / "rasters_COP30.tar"
EXTRACT_DIR = GEO_DIR / "rasters"

# Try to extract the archive (no-op if already extracted)
if ARCHIVE.exists():
    try:
        if not EXTRACT_DIR.exists():
            EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
            with tarfile.open(ARCHIVE, "r") as tf:
                # extract members into EXTRACT_DIR
                tf.extractall(path=EXTRACT_DIR)
            logger.info("Extracted raster archive to %s", EXTRACT_DIR)
    except Exception:
        logger.exception("Failed to extract raster archive")

# Attempt to import rasterio and open the first TIFF we find
RASTER_AVAILABLE = False
_raster_src = None
try:
    import rasterio
    from rasterio.errors import RasterioIOError
    # find first .tif in the extracted folder or geo dir
    candidates = list(EXTRACT_DIR.glob("*.tif")) or list(GEO_DIR.glob("*.tif"))
    if candidates:
        try:
            _raster_src = rasterio.open(str(candidates[0]))
            RASTER_AVAILABLE = True
            logger.info("Opened raster %s for elevation sampling", candidates[0].name)
        except RasterioIOError:
            logger.exception("Failed to open raster file %s", candidates[0].name)
except Exception:
    # rasterio not installed or other import errors
    logger.debug("rasterio not available; local raster elevation disabled")


def sample_elevation(lat: float, lon: float) -> Optional[float]:
    """Return elevation in metres for given lat/lon or None if unavailable.

    Note: rasterio expects coordinates in (lon, lat) / (x, y) order.
    """
    global _raster_src
    if not RASTER_AVAILABLE or _raster_src is None:
        return None
    try:
        # rasterio.sample expects an iterable of (x, y)
        for val in _raster_src.sample([(lon, lat)]):
            if val is None:
                return None
            # val is a numpy array (bands,), take band 1
            try:
                v = float(val[0])
            except Exception:
                v = None
            # Many DEMs use a nodata value (e.g., -9999); handle that
            nodata = _raster_src.nodata
            if v is None:
                return None
            if nodata is not None and v == nodata:
                return None
            return v
    except Exception:
        logger.exception("Error sampling raster at %s,%s", lat, lon)
        return None
