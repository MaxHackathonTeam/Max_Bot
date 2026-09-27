from pydantic import BaseModel, ConfigDict, Field


class VenueIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=255)
    address: str | None = Field(default=None, max_length=500)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    org_id: int | None = Field(default=None, description="Площадка организации")
    locality_id: int | None = Field(
        default=None,
        description="По умолчанию — ближайший к точке населённый пункт; без координат"
        " обязателен, площадка ставится в центр населённого пункта",
    )
    fias_id: str | None = Field(default=None, max_length=64)


class VenueOut(BaseModel):
    id: int
    name: str
    address: str | None
    locality_id: int
    locality_name: str | None
    lat: float
    lon: float
    org_id: int | None


class MediaOut(BaseModel):
    id: int
    url: str
    width: int | None
    height: int | None
    size: int
