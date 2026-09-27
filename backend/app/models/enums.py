"""Перечисления предметной области (§2, §4, §5, §6, §10)."""

from enum import StrEnum


class ConsentDoc(StrEnum):
    terms = "terms"
    privacy = "privacy"
    org_pd = "org_pd"


class LocalityKind(StrEnum):
    city = "city"
    town = "town"
    pgt = "pgt"
    village = "village"
    settlement = "settlement"
    other = "other"


class OrgKind(StrEnum):
    dk = "dk"
    museum = "museum"
    park = "park"
    library = "library"
    theatre = "theatre"
    cinema = "cinema"
    sport = "sport"
    nko = "nko"
    ip = "ip"
    club = "club"
    municipal = "municipal"
    other = "other"


class VerificationStatus(StrEnum):
    unverified = "unverified"
    pending = "pending"
    verified = "verified"
    rejected = "rejected"
    revoked = "revoked"


class VerificationMethod(StrEnum):
    invite = "invite"
    registry_auto = "registry_auto"
    manual = "manual"


class OrgRole(StrEnum):
    owner = "owner"
    editor = "editor"


class TrustTier(StrEnum):
    official = "official"
    community = "community"
    demo = "demo"


class EventStatus(StrEnum):
    draft = "draft"
    pending = "pending"
    published = "published"
    rejected = "rejected"
    cancelled = "cancelled"
    hidden = "hidden"
    archived = "archived"


class Indoor(StrEnum):
    indoor = "indoor"
    outdoor = "outdoor"
    mixed = "mixed"
    unknown = "unknown"


class PriceType(StrEnum):
    free = "free"
    paid = "paid"
    donation = "donation"
    unknown = "unknown"


class SessionStatus(StrEnum):
    scheduled = "scheduled"
    cancelled = "cancelled"


class DraftOrigin(StrEnum):
    bot_text = "bot_text"
    bot_photo = "bot_photo"
    form = "form"


class SubscriptionKind(StrEnum):
    organization = "organization"
    digest = "digest"


class NotificationStatus(StrEnum):
    scheduled = "scheduled"
    sent = "sent"
    failed = "failed"
    skipped = "skipped"


class ReportReason(StrEnum):
    fraud = "fraud"
    wrong_data = "wrong_data"
    offensive = "offensive"
    not_event = "not_event"
    other = "other"


class UserChannel(StrEnum):
    max = "max"  # бот или мини-приложение MAX
    web = "web"  # сайт: гость или вход по коду из бота


class ModerationActor(StrEnum):
    rules = "rules"
    llm = "llm"  # legacy: решения прежних версий, новых не бывает
    admin = "admin"


class ModerationVerdict(StrEnum):
    approve = "approve"
    reject = "reject"
    review = "review"
    hide = "hide"


class AuditActor(StrEnum):
    user = "user"
    admin = "admin"
    system = "system"
    llm = "llm"  # legacy: записи прежних версий
