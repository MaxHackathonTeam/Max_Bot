"""Справочник категорий событий; те же slug — интересы пользователя (FR-ONB-3)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Category:
    slug: str
    name: str
    emoji: str


CATEGORIES: tuple[Category, ...] = (
    Category("concert", "Концерты", "🎵"),
    Category("theatre", "Спектакли", "🎭"),
    Category("cinema", "Кино", "🎬"),
    Category("exhibition", "Выставки и музеи", "🖼"),
    Category("masterclass", "Мастер-классы", "🛠"),
    Category("lecture", "Лекции и встречи", "💬"),
    Category("festival", "Праздники и фестивали", "🎉"),
    Category("sport", "Спорт и активный отдых", "⚽"),
    Category("excursion", "Экскурсии", "🧭"),
    Category("games", "Игры и квесты", "🎲"),
    Category("kids", "Детям", "🧸"),
    Category("other", "Другое", "✨"),
)
BY_SLUG = {c.slug: c for c in CATEGORIES}


def is_known(slug: str) -> bool:
    return slug in BY_SLUG
