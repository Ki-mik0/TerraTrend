"""Build map trend grids from NASA Earthdata collections and publish them where the API reads them.

    python scripts/earthdata_grids.py                    # every source: download (resumable) + analyse + publish
    python scripts/earthdata_grids.py --only gldas airs  # some sources (see --list)
    python scripts/earthdata_grids.py --analyse-only     # rebuild grids from the downloaded cache
    python scripts/earthdata_grids.py --probe            # read one granule of each source and print it

Needs an Earthdata Login in ~/_netrc (`earthaccess.login(persist=True)`) with the GES DISC application
approved. Each granule is reduced right away to the 1 degree map grid and cached as a small file under
`STORAGE_ROOT/grids/earthdata-raw/<source>/`, so a run resumes where it stopped and the raw files are
never kept. Access per source:

- GES DISC collections (MERRA-2, AIRS, IMERG daily) are subset on the server through Cloud OPeNDAP, so only
  the needed variable travels;
- HDF5 / netCDF-4 files (GLDAS, IMERG monthly, OMI, NSIDC, ocean colour) are fetched whole into memory;
- HDF4 MODIS files and the on-premises MODIS SST are downloaded, read and deleted.

Monthly cubes then go through the same analysis as `grid_scan.py` (Sen slope + Mann-Kendall + OLS-AR1 per
cell, FDR across the globe, yearly anomaly frames) for the year and the four seasons.
"""

from __future__ import annotations

import argparse
import calendar
import hashlib
import io
import json
import re
import sys
import threading
import time
import warnings
from collections import deque
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import numpy as np

HDF5_MAGIC = bytes([0x89]) + b"HDF"

sys.path.insert(0, str(Path(__file__).resolve().parent))

import grid_scan as gs  # noqa: E402

LAST_YEAR = datetime.now(UTC).year - 1
WET_MM = 1.0  # a day with less precipitation is dry (ETCCDI)
HOT_K = 303.15  # daily maximum above 30 degC
FROST_K = 273.15  # daily minimum below 0 degC

Fields = dict[str, np.ndarray]


@dataclass(frozen=True)
class Output:
    """One catalog variable made from a cached field: monthly `mean`, `count` of days, `rx5day` or `dry_spell`."""

    units: str
    field: str
    how: str = "mean"


@dataclass(frozen=True)
class Source:
    key: str
    short_name: str
    version: str | None
    first_year: int
    outputs: dict[str, Output]
    read: Callable[[object], Fields | list[tuple[date, Fields]]]
    label: str
    daily: bool = False
    day_step: int = 1
    granule_name: str | None = None
    name_regex: str | None = None
    heavy: bool = False
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- grid and decoding helpers


def to_grid(values: np.ndarray, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """Average a field on any lat/lon grid (1-D axes or 2-D coordinates) into the 1 degree map grid."""
    values = np.asarray(values, dtype=np.float32)
    lat, lon = np.asarray(lat, dtype=np.float64), np.asarray(lon, dtype=np.float64)
    if lat.ndim == 1 and lon.ndim == 1:
        rows = np.clip(np.floor(90.0 - lat).astype(np.int32), 0, 179)
        cols = np.clip(np.floor((lon + 180.0) % 360.0).astype(np.int32), 0, 359)
        flat = (rows[:, None] * 360 + cols[None, :]).ravel()
    else:
        rows = np.clip(np.floor(90.0 - lat).astype(np.int32), 0, 179)
        cols = np.clip(np.floor((lon + 180.0) % 360.0).astype(np.int32), 0, 359)
        flat = (rows * 360 + cols).ravel()
    data = values.ravel()
    ok = np.isfinite(data)
    total = np.bincount(flat[ok], weights=data[ok], minlength=64800)
    count = np.bincount(flat[ok], minlength=64800)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(count > 0, total / np.maximum(count, 1), np.nan).reshape(180, 360).astype(np.float32)


def decode(ds, selection=()) -> np.ndarray:
    """Read an HDF5 / netCDF variable with its fill value, valid range, scale and offset applied."""
    raw = ds[selection]
    attrs = ds.attrs
    bad = np.zeros(raw.shape, dtype=bool)
    for name in ("_FillValue", "MissingValue", "missing_value"):
        if name in attrs:
            bad |= raw == np.asarray(attrs[name]).ravel()[0]
    if "valid_range" in attrs:
        low, high = np.asarray(attrs["valid_range"]).ravel()[:2]
        bad |= (raw < low) | (raw > high)
    out = raw.astype(np.float64)
    if "scale_factor" in attrs:
        out = out * float(np.asarray(attrs["scale_factor"]).ravel()[0])
    if "add_offset" in attrs:
        out = out + float(np.asarray(attrs["add_offset"]).ravel()[0])
    out[bad] = np.nan
    out[np.abs(out) > 1e29] = np.nan  # OMI fills (-1.27e30) that survived a dtype round trip
    return out


def find(h5, name: str):
    """Dataset whose path ends with `name` (OPeNDAP replies keep or flatten groups)."""
    hits: list = []

    def visit(path, obj):
        if getattr(obj, "shape", None) is not None and (path == name or path.endswith("/" + name)):
            hits.append(obj)

    if name in h5:
        return h5[name]
    h5.visititems(visit)
    if not hits:
        raise KeyError(name)
    return hits[0]


# ---------------------------------------------------------------- access to Earthdata

_local = threading.local()


def session():
    import earthaccess

    if getattr(_local, "session", None) is None:
        _local.session = earthaccess.get_requests_https_session()
    return _local.session


def opendap_url(granule) -> str:
    for item in granule["umm"].get("RelatedUrls", []):
        url = item.get("URL", "")
        if "opendap.earthdata.nasa.gov" in url:
            return url
    raise LookupError("no Cloud OPeNDAP link")


@contextmanager
def dap(granule, *variables: str) -> Iterator:
    """Server-side subset (Cloud OPeNDAP, DAP4) returned as netCDF-4 and opened in memory."""
    import h5py

    constraint = ";".join(variables)
    url = opendap_url(granule) + ".dap.nc4?dap4.ce=" + quote(constraint, safe="/[]:;_")
    response = session().get(url, timeout=600)
    response.raise_for_status()
    if not response.content.startswith(b"\x89HDF"):
        raise OSError(f"OPeNDAP returned {response.headers.get('content-type')}, not netCDF-4")
    with h5py.File(io.BytesIO(response.content), "r") as h5:
        yield h5


@contextmanager
def stream(granule) -> Iterator:
    """HDF5 / netCDF-4 file fetched in one request and opened in memory.

    Reading in place over HTTPS costs one round trip per HDF5 chunk and metadata block, which made a
    17 MB IMERG month take almost a minute; one GET of the whole file takes a few seconds.
    """
    import h5py

    response = session().get(granule.data_links()[0], timeout=900)
    response.raise_for_status()
    if not response.content.startswith(HDF5_MAGIC):
        raise OSError(f"expected an HDF5 file, got {response.headers.get('content-type')}")
    with h5py.File(io.BytesIO(response.content), "r") as h5:
        yield h5


@contextmanager
def fetched(granule) -> Iterator[Path]:
    """Whole file downloaded to a scratch folder and deleted after use."""
    url = granule.data_links()[0]
    folder = raw_root() / "_download"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{threading.get_ident()}-{Path(url.split('?')[0]).name}"
    try:
        with session().get(url, stream=True, timeout=900) as response:
            response.raise_for_status()
            with path.open("wb") as out:
                for chunk in response.iter_content(4 * 2**20):
                    out.write(chunk)
        yield path
    finally:
        path.unlink(missing_ok=True)


def hdf4(path: Path, *names: str) -> list[tuple[np.ndarray, dict]]:
    from pyhdf.SD import SD, SDC

    sd = SD(str(path), SDC.READ)
    try:
        out = []
        for name in names:
            ds = sd.select(name)
            out.append((ds.get(), ds.attributes()))
            ds.endaccess()
        return out
    finally:
        sd.end()


# ---------------------------------------------------------------- readers, one per source

CMG_LAT = 89.975 - 0.05 * np.arange(3600)
CMG_LON = -179.975 + 0.05 * np.arange(7200)
ONE_LAT = 89.5 - np.arange(180.0)
ONE_LON = -179.5 + np.arange(360.0)
OMI_LAT = -89.875 + 0.25 * np.arange(720)
OMI_LON = -179.875 + 0.25 * np.arange(1440)


def merra2(names: dict[str, tuple[str, float]], level: int | None = None) -> Callable:
    """MERRA-2 monthly 2-D fields (or one pressure level of a 3-D file) via OPeNDAP."""

    def read(granule) -> Fields:
        hyperslab = "" if level is None else f"[0][{level}][0:360][0:575]"
        with dap(granule, *(f"/{var}{hyperslab}" for var, _ in names.values()), "/lat", "/lon") as h5:
            lat, lon = find(h5, "lat")[...], find(h5, "lon")[...]
            return {key: to_grid(decode(find(h5, var)).reshape(361, 576) * scale, lat, lon) for key, (var, scale) in names.items()}

    return read


def read_gldas(granule) -> Fields:
    names = {
        "gldas_sm": ("SoilMoi0_10cm_inst", 1 / 100),  # kg m-2 in the top 10 cm -> m3 m-3
        "gldas_evap": ("Evap_tavg", 86400.0),  # kg m-2 s-1 -> mm/day
        "gldas_runoff": ("Qs_acc", 8.0),  # kg m-2 per 3 h -> mm/day
        "gldas_precip": ("Rainf_f_tavg", 86400.0),
        "gldas_swe": ("SWE_inst", 1.0),  # kg m-2 = mm
    }
    with stream(granule) as h5:
        lat, lon = h5["lat"][...], h5["lon"][...]
        return {key: to_grid(decode(h5[var], 0) * scale, lat, lon) for key, (var, scale) in names.items()}


def read_imerg_month(granule) -> Fields:
    with stream(granule) as h5:
        rain = decode(h5["Grid/precipitation"], 0).T * 24.0  # (lon, lat) mm/h -> (lat, lon) mm/day
        rain[rain < 0] = np.nan
        return {"gpm_imerg": to_grid(rain, h5["Grid/lat"][...], h5["Grid/lon"][...])}


def read_imerg_day(granule) -> Fields:
    """One 0.1 degree pixel near the centre of each 1 degree cell (stride 10 on the server)."""
    with dap(granule, "/precipitation[0][5:10:3599][5:10:1799]", "/lat[5:10:1799]", "/lon[5:10:3599]") as h5:
        rain = decode(find(h5, "precipitation"))[0].T
        rain[rain < 0] = np.nan
        return {"precip": to_grid(rain, find(h5, "lat")[...], find(h5, "lon")[...])}


def read_merra2_day(granule) -> Fields:
    with dap(granule, "/T2MMAX", "/T2MMIN", "/lat", "/lon") as h5:
        lat, lon = find(h5, "lat")[...], find(h5, "lon")[...]
        tmax = decode(find(h5, "T2MMAX")).reshape(361, 576)
        tmin = decode(find(h5, "T2MMIN")).reshape(361, 576)
        hot = np.where(np.isfinite(tmax), (tmax > HOT_K).astype(np.float32), np.nan)
        frost = np.where(np.isfinite(tmin), (tmin < FROST_K).astype(np.float32), np.nan)
        return {"hot": to_grid(hot, lat, lon), "frost": to_grid(frost, lat, lon)}


AIRS_500HPA = 5  # StdPressureLev: 1000, 925, 850, 700, 600, 500 hPa ...


def read_airs(granule) -> Fields:
    """AIRS v7 L3 monthly, the mean of the ascending (13:30) and descending (01:30) orbits."""
    with dap(
        granule,
        "/ascending/Data_Fields/SurfAirTemp_A",
        "/descending/Data_Fields/SurfAirTemp_D",
        f"/ascending/Data_Fields/Temperature_A[{AIRS_500HPA}][0:179][0:359]",
        f"/descending/Data_Fields/Temperature_D[{AIRS_500HPA}][0:179][0:359]",
    ) as h5:
        out = {}
        for key, (a, d) in {"airs_t": ("SurfAirTemp_A", "SurfAirTemp_D"), "airs_profile": ("Temperature_A", "Temperature_D")}.items():
            pair = np.stack([decode(find(h5, a)).reshape(180, 360), decode(find(h5, d)).reshape(180, 360)])
            pair[pair < 0] = np.nan
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                out[key] = to_grid(np.nanmean(pair, axis=0), ONE_LAT, ONE_LON)
        return out


def omi(path: str, key: str, scale: float = 1.0) -> Callable:
    def read(granule) -> Fields:
        with stream(granule) as h5:
            return {key: to_grid(decode(h5[path]) * scale, OMI_LAT, OMI_LON)}

    return read


def read_grace(granule) -> list[tuple[date, Fields]]:
    import h5py

    with fetched(granule) as path, h5py.File(path, "r") as h5:
        days = h5["time"][...]
        lat, lon = h5["lat"][...], h5["lon"][...]
        out = []
        for index, day in enumerate(days):
            when = date(2002, 1, 1) + timedelta(days=float(day))
            out.append((when.replace(day=1), {"grace_tws": to_grid(decode(h5["lwe_thickness"], index) * 10.0, lat, lon)}))  # cm -> mm
        return out


_polar: dict[str, tuple[np.ndarray, np.ndarray]] = {}
_polar_lock = threading.Lock()


def read_nsidc(granule) -> Fields:
    """Monthly sea ice concentration on the 25 km polar stereographic grid of one hemisphere."""
    north = "_PS_N" in granule["umm"]["GranuleUR"]
    with stream(granule) as h5:
        names = [name for name in h5 if name.endswith("_ICECON")]
        x, y = h5["x"][...], h5["y"][...]
        stack = np.stack([decode(h5[name], 0) for name in names])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        ice = np.nanmean(stack, axis=0)
    hemisphere = "N" if north else "S"
    with _polar_lock:
        if hemisphere not in _polar:
            from pyproj import Transformer

            to_lonlat = Transformer.from_crs("EPSG:3411" if north else "EPSG:3412", "EPSG:4326", always_xy=True)
            xx, yy = np.meshgrid(x, y)
            lon, lat = to_lonlat.transform(xx, yy)
            _polar[hemisphere] = (lat, lon)
    lat, lon = _polar[hemisphere]
    return {"nsidc_ice": to_grid(ice, lat, lon)}


def ocean(var: str, key: str, download: bool = False) -> Callable:
    """MODIS Aqua Level-3 mapped monthly 9 km (OB.DAAC)."""

    def read(granule) -> Fields:
        import h5py

        if download:
            with fetched(granule) as path, h5py.File(path, "r") as h5:
                return {key: to_grid(decode(h5[var]), h5["lat"][...], h5["lon"][...])}
        with stream(granule) as h5:
            return {key: to_grid(decode(h5[var]), h5["lat"][...], h5["lon"][...])}

    return read


def read_mod13c2(granule) -> Fields:
    with fetched(granule) as path:
        (ndvi, _), (evi, _) = hdf4(path, "CMG 0.05 Deg Monthly NDVI", "CMG 0.05 Deg Monthly EVI")
    out = {}
    for key, raw in (("modis_ndvi", ndvi), ("modis_evi", evi)):
        value = np.where((raw >= -2000) & (raw <= 10000), raw / 10000.0, np.nan)
        out[key] = to_grid(value, CMG_LAT, CMG_LON)
    return out


def read_mod11c3(granule) -> Fields:
    """Land surface temperature, the mean of day and night (K)."""
    with fetched(granule) as path:
        (day, _), (night, _) = hdf4(path, "LST_Day_CMG", "LST_Night_CMG")
    both = np.stack([np.where(day >= 7500, day * 0.02, np.nan), np.where(night >= 7500, night * 0.02, np.nan)])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return {"modis_lst": to_grid(np.nanmean(both, axis=0), CMG_LAT, CMG_LON)}


def read_mod10cm(granule) -> Fields:
    with fetched(granule) as path:
        ((snow, _),) = hdf4(path, "Snow_Cover_Monthly_CMG")
    return {"modis_snow": to_grid(np.where(snow <= 100, snow / 100.0, np.nan), CMG_LAT, CMG_LON)}


def read_myd08(granule) -> Fields:
    with fetched(granule) as path:
        ((aod, _),) = hdf4(path, "AOD_550_Dark_Target_Deep_Blue_Combined_Mean_Mean")
    return {"modis_aod": to_grid(np.where(aod >= 0, aod * 0.001, np.nan), ONE_LAT, ONE_LON)}


# ---------------------------------------------------------------- the sources

MERRA2_500HPA = 16  # lev: 1000, 975, ... 550, 500 hPa


def sources() -> list[Source]:
    m = Output
    return [
        Source("merra2_slv", "M2TMNXSLV", None, 1991, {"merra2_t2m": m("K", "merra2_t2m")}, merra2({"merra2_t2m": ("T2M", 1.0)}), "MERRA-2 M2TMNXSLV T2M"),
        Source("merra2_flx", "M2TMNXFLX", None, 1991, {"merra2_prectot": m("mm/day", "merra2_prectot")}, merra2({"merra2_prectot": ("PRECTOT", 86400.0)}), "MERRA-2 M2TMNXFLX PRECTOT"),
        Source("merra2_lnd", "M2TMNXLND", None, 1991, {"merra2_sfmc": m("m3 m-3", "merra2_sfmc")}, merra2({"merra2_sfmc": ("SFMC", 1.0)}), "MERRA-2 M2TMNXLND SFMC"),
        Source("merra2_aer", "M2TMNXAER", None, 1991, {"merra2_aod": m("1", "merra2_aod")}, merra2({"merra2_aod": ("TOTEXTTAU", 1.0)}), "MERRA-2 M2TMNXAER TOTEXTTAU"),
        Source(
            "merra2_asm", "M2IMNPASM", None, 1991,
            {"merra2_t_profile": m("K", "merra2_t_profile"), "merra2_q_profile": m("g/kg", "merra2_q_profile")},
            merra2({"merra2_t_profile": ("T", 1.0), "merra2_q_profile": ("QV", 1000.0)}, level=MERRA2_500HPA),
            "MERRA-2 M2IMNPASM T and QV at 500 hPa",
        ),
        Source("imerg", "GPM_3IMERGM", "07", 1998, {"gpm_imerg": m("mm/day", "gpm_imerg")}, read_imerg_month, "GPM IMERG V07 monthly precipitation"),
        Source(
            "gldas", "GLDAS_NOAH025_M", "2.1", 2000,
            {
                "gldas_sm": m("m3 m-3", "gldas_sm"),
                "gldas_evap": m("mm/day", "gldas_evap"),
                "gldas_runoff": m("mm/day", "gldas_runoff"),
                "gldas_precip": m("mm/day", "gldas_precip"),
                "gldas_swe": m("mm", "gldas_swe"),
            },
            read_gldas, "GLDAS Noah 2.1 monthly",
        ),
        Source("airs", "AIRS3STM", "7.0", 2003, {"airs_t": m("K", "airs_t"), "airs_profile": m("K", "airs_profile")}, read_airs, "AIRS v7 L3 monthly (surface air, 500 hPa)"),
        Source(
            "omi_no2", "OMNO2d", "003", 2005, {"omi_no2": m("1e15 molec/cm2", "omi_no2")},
            omi("HDFEOS/GRIDS/ColumnAmountNO2/Data Fields/ColumnAmountNO2TropCloudScreened", "omi_no2", 1e-15),
            "OMI OMNO2d tropospheric NO2 (every 3rd day)", daily=True, day_step=3,
        ),
        Source(
            "omi_o3", "OMTO3e", "003", 2005, {"omi_o3": m("DU", "omi_o3")},
            omi("HDFEOS/GRIDS/OMI Column Amount O3/Data Fields/ColumnAmountO3", "omi_o3"),
            "OMI OMTO3e total ozone (every 3rd day)", daily=True, day_step=3,
        ),
        Source(
            "omi_so2", "OMSO2e", "003", 2005, {"omi_so2": m("DU", "omi_so2")},
            omi("HDFEOS/GRIDS/OMI Total Column Amount SO2/Data Fields/ColumnAmountSO2", "omi_so2"),
            "OMI OMSO2e planetary boundary layer SO2 (every 3rd day)", daily=True, day_step=3,
        ),
        Source("grace", "TELLUS_GRAC-GRFO_MASCON_CRI_GRID_RL06.3_V4", None, 2003, {"grace_tws": m("mm", "grace_tws")}, read_grace, "JPL GRACE/GRACE-FO mascon RL06.3 CRI"),
        Source("nsidc", "NSIDC-0051", "2", 1991, {"nsidc_ice": m("1", "nsidc_ice")}, read_nsidc, "NSIDC-0051 v2 sea ice concentration",
               granule_name="NSIDC0051_SEAICE_PS_*25km_??????_v2.0.nc", name_regex=r"_\d{6}_v2"),
        Source(
            "modis_chl", "MODISA_L3m_CHL", None, 2003, {"modis_chlor": m("mg m-3", "modis_chlor")},
            ocean("chlor_a", "modis_chlor"), "MODIS Aqua L3m chlorophyll-a", granule_name="*L3m.MO.CHL.chlor_a.9km*",
        ),
        Source(
            "modis_sst", "MODISA_L3m_SST", None, 2003, {"modis_sst": m("degC", "modis_sst")},
            ocean("sst", "modis_sst", download=True), "MODIS Aqua L3m SST", granule_name="*L3m.MO.SST.sst.9km*",
        ),
        Source("mod13c2", "MOD13C2", "061", 2001, {"modis_ndvi": m("1", "modis_ndvi"), "modis_evi": m("1", "modis_evi")}, read_mod13c2, "MODIS Terra MOD13C2 v061"),
        Source("mod11c3", "MOD11C3", "061", 2001, {"modis_lst": m("K", "modis_lst")}, read_mod11c3, "MODIS Terra MOD11C3 v061 (day and night)"),
        Source("mod10cm", "MOD10CM", "61", 2001, {"modis_snow": m("1", "modis_snow")}, read_mod10cm, "MODIS Terra MOD10CM v061"),
        Source(
            "merra2_daily", "M2SDNXSLV", None, 1991,
            {"hot_days": m("days", "hot", "count"), "frost_days": m("days", "frost", "count")},
            read_merra2_day, "MERRA-2 M2SDNXSLV daily (Tmax > 30 degC, Tmin < 0 degC)", daily=True,
        ),
        Source(
            "imerg_daily", "GPM_3IMERGDF", "07", 1998,
            {"rx5day": m("mm", "precip", "rx5day"), "dry_spell": m("days", "precip", "dry_spell")},
            read_imerg_day, "GPM IMERG V07 daily (Rx5day, longest run of days < 1 mm)", daily=True,
        ),
        Source("myd08", "MYD08_M3", "61", 2003, {"modis_aod": m("1", "modis_aod")}, read_myd08, "MODIS Aqua MYD08_M3 v061 AOD 550 nm", heavy=True),
    ]


# ---------------------------------------------------------------- download and cache


def raw_root() -> Path:
    return gs.storage() / "earthdata-raw"


def granule_date(granule) -> date:
    return date.fromisoformat(granule["umm"]["TemporalExtent"]["RangeDateTime"]["BeginningDateTime"][:10])


def cache_path(source: Source, when: date, granule_ur: str) -> Path:
    tag = hashlib.md5(granule_ur.encode()).hexdigest()[:8]
    return raw_root() / source.key / f"{when:%Y%m%d}__{tag}.npz"


def save(path: Path, fields: Fields) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.stem + ".tmp.npz")
    np.savez_compressed(tmp, **{key: value.astype(np.float32) for key, value in fields.items()})
    tmp.replace(path)


def search(source: Source) -> list:
    import earthaccess

    query: dict = {"short_name": source.short_name, "temporal": (f"{source.first_year}-01-01", f"{LAST_YEAR}-12-31T23:59:59")}
    if source.version:
        query["version"] = source.version
    if source.granule_name:
        query["granule_name"] = source.granule_name
    for attempt in range(6):  # the catalogue search survives a short network drop
        try:
            granules = earthaccess.search_data(**query)
            break
        except Exception as error:
            if attempt == 5:
                raise
            wait = 10 * 2**attempt
            print(f"[{source.key}] search failed ({type(error).__name__}), retrying in {wait}s", flush=True)
            time.sleep(wait)
    if source.name_regex:
        granules = [g for g in granules if re.search(source.name_regex, g["umm"]["GranuleUR"])]
    if source.read is read_grace:
        return granules[-1:]  # one file holds every month; take the newest release
    keep = []
    for granule in granules:
        when = granule_date(granule)
        if not source.first_year <= when.year <= LAST_YEAR:
            continue
        if source.daily and (when.day - 1) % source.day_step:
            continue
        keep.append(granule)
    return keep


def download(source: Source, workers: int) -> None:
    started = time.monotonic()
    granules = search(source)
    if source.read is read_grace:
        marker = raw_root() / source.key / f"_{hashlib.md5(granules[0]['umm']['GranuleUR'].encode()).hexdigest()[:8]}.done" if granules else None
        if marker is None or marker.exists():
            print(f"[{source.key}] up to date", flush=True)
            return
        for when, fields in read_grace(granules[0]):
            if source.first_year <= when.year <= LAST_YEAR:
                save(cache_path(source, when, granules[0]["umm"]["GranuleUR"] + str(when)), fields)
        marker.touch()
        print(f"[{source.key}] {granules[0]['umm']['GranuleUR']} split into months", flush=True)
        return
    todo = [g for g in granules if not cache_path(source, granule_date(g), g["umm"]["GranuleUR"]).exists()]
    print(f"[{source.key}] {len(granules)} granules, {len(todo)} to fetch", flush=True)
    done = failed = 0
    lock = threading.Lock()

    def one(granule) -> None:
        nonlocal done, failed
        name = granule["umm"]["GranuleUR"]
        for attempt in range(6):  # 3, 6, 12, 24, 48 s: rides out a short network drop
            try:
                fields = source.read(granule)
                break
            except Exception as error:  # network, server or decoding trouble: retry, then report
                if attempt == 5:
                    with lock:
                        failed += 1
                    print(f"  FAILED {name}: {type(error).__name__}: {str(error)[:160]}", flush=True)
                    return
                time.sleep(3 * 2**attempt)
        save(cache_path(source, granule_date(granule), name), fields)
        with lock:
            done += 1
            if done % 50 == 0 or done == len(todo):
                rate = done / (time.monotonic() - started)
                print(f"  [{source.key}] {done}/{len(todo)}, ~{(len(todo) - done) / rate / 60:.0f} min left", flush=True)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, todo))
    if failed:
        print(f"[{source.key}] {failed} granules failed; run again to retry them", flush=True)


# ---------------------------------------------------------------- monthly cubes


def cached(source: Source) -> dict[date, list[Path]]:
    by_day: dict[date, list[Path]] = {}
    for path in (raw_root() / source.key).glob("*__*.npz"):
        if path.name.endswith(".tmp.npz"):
            continue
        by_day.setdefault(datetime.strptime(path.name[:8], "%Y%m%d").date(), []).append(path)
    return by_day


def month_dates(first_year: int) -> list[date]:
    return [date(year, month, 1) for year in range(first_year, LAST_YEAR + 1) for month in range(1, 13)]


def _mean(stack: list[np.ndarray], need: int = 1) -> np.ndarray:
    block = np.stack(stack)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        mean = np.nanmean(block, axis=0)
    return np.where(np.isfinite(block).sum(axis=0) >= need, mean, np.nan)


def cubes(source: Source) -> tuple[list[date], dict[str, np.ndarray]] | None:
    """One (months, 180, 360) cube per output variable, None while too little is cached."""
    by_day = cached(source)
    dates = month_dates(source.first_year)
    expected = len(dates) if not source.daily else sum(len(range(0, calendar.monthrange(d.year, d.month)[1], source.day_step)) for d in dates)
    if not by_day or sum(len(v) for v in by_day.values()) < 0.8 * expected:
        return None
    out = {variable: np.full((len(dates), 180, 360), np.nan, dtype=np.float32) for variable in source.outputs}
    if not source.daily:
        for index, month in enumerate(dates):
            files = [p for day, paths in by_day.items() if (day.year, day.month) == (month.year, month.month) for p in paths]
            if not files:
                continue
            loaded = [np.load(p) for p in files]
            for variable, spec in source.outputs.items():
                out[variable][index] = _mean([f[spec.field] for f in loaded])
        return dates, out

    hows = {spec.how for spec in source.outputs.values()}
    window: deque[np.ndarray] = deque(maxlen=5)
    run = np.zeros((180, 360), dtype=np.float32)
    for index, month in enumerate(dates):
        n_days = calendar.monthrange(month.year, month.month)[1]
        days = [month.replace(day=d) for d in range(1, n_days + 1, source.day_step)]
        sums: dict[str, list[np.ndarray]] = {}
        rx5 = np.full((180, 360), -np.inf, dtype=np.float32)
        dry = np.zeros((180, 360), dtype=np.float32)
        present = 0
        for day in days:
            paths = by_day.get(day)
            fields = dict(np.load(paths[0])) if paths else None
            if fields is not None:
                present += 1
                for spec in source.outputs.values():
                    if spec.how in ("mean", "count"):
                        sums.setdefault(spec.field, []).append(fields[spec.field])
            if hows & {"rx5day", "dry_spell"}:
                rain = fields["precip"] if fields is not None else np.full((180, 360), np.nan, dtype=np.float32)
                window.append(rain)
                if len(window) == 5:
                    rx5 = np.fmax(rx5, np.sum(np.stack(window), axis=0))
                run = np.where(np.isfinite(rain) & (rain < WET_MM), run + 1, 0).astype(np.float32)
                dry = np.maximum(dry, run)
        if present < 0.8 * len(days):
            continue
        for variable, spec in source.outputs.items():
            if spec.how == "mean":
                out[variable][index] = _mean(sums[spec.field], need=min(3, present))
            elif spec.how == "count":
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", RuntimeWarning)
                    block = np.stack(sums[spec.field])
                    out[variable][index] = np.nanmean(block, axis=0) * n_days
            elif spec.how == "rx5day":
                out[variable][index] = np.where(np.isfinite(rx5), rx5, np.nan)
            elif spec.how == "dry_spell":
                out[variable][index] = dry
    return dates, out


def save_series(variable: str, cube: np.ndarray, dates: list[date], source: Source) -> None:
    """The monthly cube itself, so cases can cut a regional series from real data (`GridSeriesSource`)."""
    folder = gs.storage() / "series"
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f"{variable}.tmp.npy"
    np.save(tmp, cube.astype(np.float32))
    tmp.replace(folder / f"{variable}.npy")
    meta = {
        "variable_id": variable,
        "dates": [f"{d:%Y-%m}" for d in dates],
        "units": source.outputs[variable].units,
        "dataset": f"NASA Earthdata {source.label}",
        "short_name": source.short_name,
        "aggregation": "sum" if source.outputs[variable].how == "count" else "mean",
        "resolution": 1.0,
    }
    (folder / f"{variable}.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")


def analyse(source: Source) -> list[dict]:
    built = cubes(source)
    if built is None:
        print(f"[{source.key}] too little data cached, skipped", flush=True)
        return []
    dates, by_variable = built
    baseline = (dates[0].year, min(dates[0].year + 29, LAST_YEAR))
    version = f"earthdata-grid-{datetime.now(UTC):%Y-%m-%d}"
    rows: list[dict] = []
    for variable, cube in by_variable.items():
        save_series(variable, cube, dates, source)
        share = np.isfinite(cube).any(axis=0).mean()
        print(f"[{source.key}] {variable}: {share:.0%} of cells have data, baseline {baseline[0]}-{baseline[1]}", flush=True)
        rows += gs.grid_products(
            cube,
            dates,
            file_stem=f"ed-{variable}",
            variables=[variable],
            units=source.outputs[variable].units,
            source=f"NASA Earthdata {source.label}",
            version=version,
            baseline=baseline,
        )
    return rows


# ---------------------------------------------------------------- command line


def probe(selected: list[Source]) -> None:
    for source in selected:
        started = time.monotonic()
        try:
            granules = search(source)
            if not granules:
                print(f"[{source.key}] no granules found")
                continue
            result = source.read(granules[len(granules) // 2])
            items = result if isinstance(result, list) else [(granule_date(granules[len(granules) // 2]), result)]
            when, fields = items[len(items) // 2]
            for key, grid in fields.items():
                finite = grid[np.isfinite(grid)]
                rows = [float(np.nanmean(grid[r])) if np.isfinite(grid[r]).any() else float("nan") for r in (10, 90, 170)]
                print(
                    f"[{source.key}] {len(granules)} granules, {when} {key}: {finite.size / grid.size:.0%} cells, "
                    f"min {finite.min():.4g} median {np.median(finite):.4g} max {finite.max():.4g}, "
                    f"row means 80N/0/80S {rows[0]:.4g}/{rows[1]:.4g}/{rows[2]:.4g}  ({time.monotonic() - started:.1f}s)",
                    flush=True,
                )
        except Exception as error:
            print(f"[{source.key}] PROBE FAILED {type(error).__name__}: {str(error)[:300]}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", nargs="*", help="source keys to run (default: all but the heavy ones)")
    parser.add_argument("--heavy", action="store_true", help="include MYD08_M3 (about 350 MB per month, ~100 GB in total)")
    parser.add_argument("--analyse-only", action="store_true", help="skip the download, use the cache")
    parser.add_argument("--workers", type=int, default=8, help="parallel requests to Earthdata")
    parser.add_argument("--probe", action="store_true", help="read one granule per source and print it, change nothing")
    parser.add_argument("--list", action="store_true", help="list the sources and exit")
    args = parser.parse_args()

    every = sources()
    if args.list:
        for source in every:
            print(f"{source.key:13s} {source.short_name:42s} {source.first_year}-{LAST_YEAR}  -> {', '.join(source.outputs)}{'  (heavy)' if source.heavy else ''}")
        return 0
    known = {source.key for source in every}
    unknown = set(args.only or []) - known
    if unknown:
        parser.error(f"unknown sources {sorted(unknown)}; known: {sorted(known)}")
    selected = [s for s in every if (s.key in args.only if args.only else (args.heavy or not s.heavy))]

    gs.storage().mkdir(parents=True, exist_ok=True)
    if not args.analyse_only:
        import earthaccess

        if not earthaccess.login(strategy="netrc").authenticated:
            print("Earthdata login failed: run  python -c \"import earthaccess; earthaccess.login(persist=True)\"")
            return 1
    if args.probe:
        probe(selected)
        return 0

    published = 0
    skipped: list[str] = []
    for source in selected:
        if not args.analyse_only:
            try:
                download(source, args.workers)
            except Exception as error:  # one unreachable source must not stop the others
                print(f"[{source.key}] download stopped: {type(error).__name__}: {str(error)[:200]}", flush=True)
                skipped.append(source.key)
        rows = analyse(source)
        if rows:
            gs.publish(rows)  # after every source, so the map fills in while the rest downloads
            published += len(rows)
    print(f"Done: {published} grid products published.")
    if skipped:
        print(f"Not downloaded this time: {' '.join(skipped)}. Run again (or --only {' '.join(skipped)}) to resume.")
    return 0 if published else 1


if __name__ == "__main__":
    raise SystemExit(main())
