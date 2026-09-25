from pydantic import BaseModel, Field


class LocalityOut(BaseModel):
    id: int
    name: str
    kind: str
    region: str | None
    municipality: str | None
    lat: float
    lon: float
    timezone: str
    distance_km: float | None = Field(default=None, description="Расстояние от точки запроса")


class AddressOut(BaseModel):
    value: str
    lat: float | None
    lon: float | None
    fias_id: str | None
    locality_name: str | None


class CategoryOut(BaseModel):
    slug: str
    name: str
    emoji: str
