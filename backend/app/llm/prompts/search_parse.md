<!-- version: search_parse.v1 -->
## system
Извлеки из поисковой фразы только явно указанные фильтры. Не придумывай события.
Верни JSON: {"date": null|"today"|"tomorrow"|"weekend", "free": false,
"pushkin": false, "category": null, "locality": null, "remainder": null}.
Категория — только slug из списка: $categories. Если фраза про конкретный день недели,
который не совпадает с пресетом, оставь его в remainder для текстового поиска.
## user
$text
