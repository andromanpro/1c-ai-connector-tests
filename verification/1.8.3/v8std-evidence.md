# Проверка изменений ИИконы 1.8.3

Проверены клиентское представление суммы и валюты, отсутствие новых серверных вызовов,
сохранение длинной подписи и обработка отсутствующих полей результата.
Сторожевая страница и поиск повторно получены 22.10.2026.
Полные ответы источника находятся в локальном каталоге standards.
Нормы применены к изменённому участку; это не новый аудит всего продукта.
std778: пункт 4, не фиксируется общая длина числовой суммы.
std487: пункты 1.1 и 3.2.1, форматирование остаётся на клиенте, длительная операция использует БСП.
Внутренние правила: СтрШаблон с НСтр, явные ветви для отсутствующих ключей;
публичные сигнатуры, права, настройки моделей и постоянная структура данных не изменены.
Проверка bslfmt и отдельная проверка читаемости: без замечаний.
Оформление тестов специально не приводилось к стандартам по указанию владельца.

## v8std evidence

[v8std sentinel: id=std792, status=found, phase=review]
[v8std discovered: phase=design, scope=chat-cost-format, query="Представление числовых значений денежных сумм форматирование на клиенте передача данных JSON", top_ids=[std778,acc:376,std443], new_ids=[], decision=applied]
[v8std applied: phase=design, scope=chat-cost-format, ids_checked=[std778,std487], conclusion=clean]
[v8std applied: phase=implementation, scope=chat-cost-format, ids_checked=[std778,std487], conclusion=clean]
[v8std discovered: phase=review, scope=chat-cost-format, query="Представление числовых значений денежных сумм форматирование на клиенте передача данных JSON", top_ids=[std778,acc:376,std443], new_ids=[], decision=applied]
[v8std applied: phase=review, scope=chat-cost-format, ids_checked=[std778,std487], conclusion=clean]
