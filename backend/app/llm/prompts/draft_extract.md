<!-- version: draft_extract.v1 -->
## system
Извлеки из объявления о событии только явно указанные сведения. Ничего не додумывай.
Верни JSON с полями title, description, category, locality, starts_at (ISO 8601 с
часовым поясом, только если дата, год и время однозначны), price_type
(free|paid|donation), price_min (целые рубли), ticket_url (только https).
Не возвращай контакты, неизвестные значения — null. Категория только из: $categories.
## user
$text
