"""Curated process links and papers per catalog variable.

This is catalog knowledge (`ProcessLink`), not computed numbers: lags are the usual physical delay,
and `partial_r` stays empty until analytics computes it for a case.
"""

from __future__ import annotations

from earthtrend.api.domain.story.model import Paper, RelatedVariable

GLDAS = Paper(
    "The Global Land Data Assimilation System",
    "https://doi.org/10.1175/BAMS-85-3-381",
    "10.1175/BAMS-85-3-381",
)
MERRA2 = Paper(
    "The Modern-Era Retrospective Analysis for Research and Applications, Version 2 (MERRA-2)",
    "https://doi.org/10.1175/JCLI-D-16-0758.1",
    "10.1175/JCLI-D-16-0758.1",
)
DROUGHT = Paper(
    "Increasing drought under global warming in observations and models",
    "https://doi.org/10.1038/nclimate1633",
    "10.1038/nclimate1633",
)
SOIL_CLIMATE = Paper(
    "Investigating soil moisture–climate interactions in a changing climate: A review",
    "https://doi.org/10.1016/j.earscirev.2010.02.004",
    "10.1016/j.earscirev.2010.02.004",
)
SURFACE_TEMPERATURE = Paper(
    "Global surface temperature change",
    "https://doi.org/10.1029/2010RG000345",
    "10.1029/2010RG000345",
)

KNOWLEDGE: dict[str, dict] = {
    "gldas_sm": {
        "related": (
            RelatedVariable("merra2_t2m", "driver", 0, name="Air temperature"),
            RelatedVariable("precipitation", "driver", 1, name="Precipitation"),
            RelatedVariable("evapotranspiration", "process", 0, name="Evapotranspiration"),
            RelatedVariable("ndvi", "response", 2, name="Vegetation index"),
        ),
        "patterns": {"decreasing": "drying", "increasing": "wetting"},
        "papers": (GLDAS, DROUGHT, SOIL_CLIMATE),
    },
    "merra2_t2m": {
        "related": (
            RelatedVariable("gldas_sm", "response", 1, name="Soil moisture"),
            RelatedVariable("evapotranspiration", "response", 0, name="Evapotranspiration"),
        ),
        "patterns": {"increasing": "warming", "decreasing": "cooling"},
        "papers": (MERRA2, SURFACE_TEMPERATURE),
    },
}


def related_for(variable_id: str) -> tuple[RelatedVariable, ...]:
    return KNOWLEDGE.get(variable_id, {}).get("related", ())


def papers_for(variable_id: str) -> tuple[Paper, ...]:
    return KNOWLEDGE.get(variable_id, {}).get("papers", ())


def pattern_for(variable_id: str, direction: str) -> str:
    return KNOWLEDGE.get(variable_id, {}).get("patterns", {}).get(direction, "no_clear_pattern")
