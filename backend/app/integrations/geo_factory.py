"""Сборка геокодера из настроек: DaData (если есть ключ) → Nominatim, с кэшем в Redis."""

from redis.asyncio import Redis

from app.core.config import Settings
from app.integrations.dadata import DadataGeoProvider
from app.integrations.geo import CachedGeoProvider, ChainGeoProvider, GeoProvider
from app.integrations.nominatim import NominatimGeoProvider


def build_geo_provider(settings: Settings, redis: Redis) -> GeoProvider | None:
    """None в OFFLINE_MODE: поиск идёт только по локальному справочнику."""
    if settings.offline_mode:
        return None
    providers: list[GeoProvider] = []
    if settings.dadata_api_key is not None:
        providers.append(DadataGeoProvider(settings.dadata_api_key.get_secret_value()))
    providers.append(NominatimGeoProvider(settings.nominatim_user_agent, redis))
    return CachedGeoProvider(ChainGeoProvider(providers), redis)
