"""Curated catalog seed: one passport for every BEST group, plus the named places."""

from __future__ import annotations

from earthtrend.api.domain.catalog.model import ProcessLink, Region, SensorEvent, VariablePassport


def _passport(
    variable_id: str,
    name: str,
    name_uk: str,
    kid: str,
    units: str,
    theme: str,
    domain: str,
    witnesses: tuple[str, ...] = (),
    doi: str = "",
) -> VariablePassport:
    return VariablePassport(
        id=variable_id,
        name=name,
        name_uk=name_uk,
        kid_description=kid,
        units=units,
        theme=theme,
        domain=domain,
        level="curated",
        witnesses=witnesses,
        doi=doi,
    )


def curated_passports() -> dict[str, VariablePassport]:
    items = [
        _passport("merra2_t2m", "Air temperature", "Температура повітря", "Тепло біля поверхні.", "K", "atmosphere", "temperature", ("airs_t", "modis_lst"), "10.5067/A7S6XP56VZWS"),
        _passport("airs_t", "AIRS air", "Повітря AIRS", "Незалежний термометр атмосфери.", "K", "atmosphere", "temperature", ("merra2_t2m",)),
        _passport("modis_lst", "Land surface day night", "Поверхня суходолу", "День і ніч на суходолі.", "K", "land", "temperature", ("merra2_t2m",)),
        _passport("modis_sst", "Sea surface", "Поверхня моря", "Тепло верхнього шару океану.", "K", "ocean", "temperature", ("airs_t",)),
        _passport("merra2_t_profile", "Pressure-level air", "Повітря за висотою", "Тренд від поверхні до стратосфери.", "K", "atmosphere", "profile", ("airs_profile",)),
        _passport("airs_profile", "AIRS profile", "Профіль AIRS", "Свідок вертикального профілю.", "K", "atmosphere", "profile", ("merra2_t_profile",)),
        _passport("merra2_q_profile", "Humidity profile", "Вологість за висотою", "Водяна пара на рівнях тиску.", "1", "atmosphere", "profile"),
        _passport("gpm_imerg", "Monthly precipitation", "Місячні опади", "Скільки води випало за місяць.", "mm", "water", "precip", ("merra2_prectot", "gldas_precip"), "10.5067/GPM/IMERG/3B-MONTH/07"),
        _passport("merra2_prectot", "Reanalysis precipitation", "Опади реаналізу", "Свідок опадів.", "mm", "water", "precip", ("gpm_imerg",)),
        _passport("gldas_precip", "Forcing precipitation", "Опади форсингу", "Опади, якими женуть модель суходолу.", "mm", "water", "precip", ("gpm_imerg",)),
        _passport("gldas_sm", "Soil moisture", "Волога ґрунту", "Скільки води в ґрунті.", "1", "land", "land_water", ("merra2_sfmc", "grace_tws"), "10.5067/E7TYRXPJKWOQ"),
        _passport("merra2_sfmc", "Surface soil moisture", "Поверхнева волога", "Свідок вологи ґрунту.", "1", "land", "land_water", ("gldas_sm",)),
        _passport("gldas_evap", "Evapotranspiration", "Випаровування", "Скільки води йде в повітря.", "mm", "land", "land_water"),
        _passport("gldas_runoff", "Runoff", "Стік", "Вода, що стікає з суходолу.", "mm", "water", "land_water"),
        _passport("grace_tws", "Total water storage", "Запас води", "Зміна маси води з орбіти.", "mm", "water", "land_water", ("gldas_sm",)),
        _passport("modis_ndvi", "Vegetation greenness", "Зелень рослин", "Наскільки живий рослинний покрив.", "1", "land", "vegetation", ("modis_evi",)),
        _passport("modis_evi", "Enhanced vegetation", "Посилена зелень", "Свідок рослинного індексу.", "1", "land", "vegetation", ("modis_ndvi",)),
        _passport("modis_phenology", "Growing season", "Сезон росту", "Початок і кінець вегетації.", "day", "land", "vegetation"),
        _passport("modis_snow", "Snow cover", "Сніговий покрив", "Частка місяця під снігом.", "1", "cryosphere", "snow", ("gldas_swe",)),
        _passport("gldas_swe", "Snow water", "Вода в снігу", "Запас води в сніговому покриві.", "mm", "cryosphere", "snow", ("modis_snow",)),
        _passport("nsidc_ice", "Sea ice", "Морський лід", "Концентрація льоду в океані.", "1", "cryosphere", "snow"),
        _passport("omi_no2", "Nitrogen dioxide", "Діоксид азоту", "Слід міського повітря.", "1", "air", "composition", ("merra2_aod",)),
        _passport("omi_o3", "Ozone", "Озон", "Озоновий шар і приземний озон.", "DU", "atmosphere", "composition"),
        _passport("omi_so2", "Sulfur dioxide", "Діоксид сірки", "Вулкани і спалювання палива.", "DU", "air", "composition"),
        _passport("merra2_aod", "Aerosol optical depth", "Аерозолі", "Наскільки мутне повітря.", "1", "atmosphere", "composition", ("modis_aod",)),
        _passport("modis_aod", "MODIS aerosols", "Аерозолі MODIS", "Свідок каламутності.", "1", "atmosphere", "composition", ("merra2_aod",)),
        _passport("modis_chlor", "Ocean chlorophyll", "Хлорофіл", "Скільки фітопланктону в морі.", "mg m-3", "ocean", "ocean"),
        _passport("hot_days", "Hot days", "Спекотні дні", "Дні, спекотніші за поріг.", "day", "atmosphere", "indicator"),
        _passport("frost_days", "Frost days", "Морозні дні", "Дні з морозом.", "day", "atmosphere", "indicator"),
        _passport("rx5day", "Five-day rain", "П'ятиденний дощ", "Найсильніші п'ять днів опадів.", "mm", "water", "indicator"),
        _passport("dry_spell", "Dry spell", "Сухий період", "Найдовша черга днів без дощу.", "day", "land", "indicator"),
        _passport("season_bounds", "Season bounds", "Межі сезону", "Початок і кінець снігу або вегетації.", "day", "land", "indicator"),
    ]
    return {item.id: item for item in items}


def curated_links() -> list[ProcessLink]:
    return [
        ProcessLink("merra2_t2m", "gldas_sm", "driver"),
        ProcessLink("gpm_imerg", "gldas_sm", "driver"),
        ProcessLink("gldas_sm", "modis_ndvi", "driver"),
        ProcessLink("merra2_t2m", "modis_lst", "witness"),
    ]


def curated_events() -> list[SensorEvent]:
    return [
        SensorEvent("merra2", "reanalysis", 2015, "MERRA-2"),
        SensorEvent("omi", "row_anomaly", 2008, "Рядкова аномалія OMI"),
        SensorEvent("grace", "launch", 2002, "Старт GRACE"),
        SensorEvent("grace-fo", "launch", 2018, "Старт GRACE-FO"),
    ]


def _region(
    region_id: str,
    name: str,
    kind: str,
    bbox: tuple[float, float, float, float],
    area: float,
    ring: tuple[float, float, float, float] | None = None,
) -> Region:
    return Region(
        id=region_id,
        name=name,
        kind=kind,
        bbox=bbox,
        area_km2=area,
        status="catalog",
        ring=ring,
    )


def curated_regions() -> dict[str, Region]:
    items = [
        _region("ukraine_south", "Ukraine south", "demo", (28.0, 44.0, 40.0, 49.0), 120000.0),
        _region("ukraine_north", "Ukraine north", "demo", (24.0, 49.0, 40.0, 52.0), 140000.0),
        _region("ar6_neu", "Northern Europe", "ar6", (5.0, 48.0, 30.0, 70.0), 1800000.0),
        _region("ukraine", "Ukraine", "country", (22.0, 44.0, 40.0, 52.5), 603000.0),
        _region("kyiv_oblast", "Kyiv oblast", "admin", (29.0, 49.0, 32.5, 51.5), 28000.0),
        _region("dnipro", "Dnipro basin", "basin", (24.0, 46.0, 36.0, 54.0), 500000.0),
        _region("sahel", "Sahel", "biome", (-18.0, 10.0, 40.0, 20.0), 3000000.0),
        _region("kyiv", "Kyiv", "city", (30.2, 50.2, 30.8, 50.6), 840.0, ring=(29.9, 50.0, 31.1, 50.8)),
        _region("black_sea", "Black Sea", "ocean", (27.0, 41.0, 42.0, 47.0), 436000.0),
        _region("carpathians_high", "Carpathians above 2000 m", "elevation", (24.0, 47.0, 26.5, 48.5), 2000.0),
        _region("amazon", "Amazon", "demo", (-75.0, -15.0, -45.0, 5.0), 7000000.0),
        _region("indo_gangetic", "Indo-Gangetic plain", "demo", (74.0, 22.0, 90.0, 32.0), 700000.0),
        _region("eastern_us", "Eastern United States", "demo", (-90.0, 25.0, -70.0, 47.0), 2000000.0),
        _region("arctic", "Arctic", "demo", (-180.0, 66.0, 180.0, 90.0), 14000000.0),
        _region("antarctica", "Antarctica", "demo", (-180.0, -90.0, 180.0, -60.0), 14000000.0),
        _region("california", "California", "demo", (-124.5, 32.5, -114.0, 42.0), 420000.0),
    ]
    return {item.id: item for item in items}
