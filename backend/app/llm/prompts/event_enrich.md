<!-- version: event_enrich.v1 -->
## system
Разметь только сведения, которые явно следуют из карточки события. Не придумывай факты.
Верни JSON: category — slug одной из категорий $categories или null; tags — до 10 коротких
тегов; short_description — краткое описание до 200 символов или null; indoor — indoor,
outdoor, mixed или unknown; youth_score — насколько событие подходит аудитории 14–22 лет,
число от 0 до 1 или null. Не повышай достоверность исходного события.
## user
Название: $title
Описание: $description
Категория источника: $category
