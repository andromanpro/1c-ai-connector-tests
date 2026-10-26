# Проверка изменённого кода кандидата 1.8.7

После восстановления сети выполнены свежая сторожевая проверка std792
и поиск по теме перехвата исключений и журналирования. Живые страницы
std498/std499 побайтно совпали с ранее прочитанными первичными страницами.

В изменённых участках исходное исключение сохраняется в ЖР с уровнем Ошибка,
имя события и шаблон комментария локализованы. Категории не определяются по
тексту ошибки. Проверка BadExceptionCategory относится к созданию исключений:
изменённый код читает категории и не создаёт исключение с новой категорией.
Проверка проектного решения и реализации восстановлена ретроспективно по
исходникам, исходным страницам стандартов и красным/зелёным пробам. Это
сверка готового решения, а не заявление, что сейчас код проектируется заново.
Проектное решение: дополнительные поля результата без изменения публичных
сигнатур, исходное исключение только в ЖР, отсутствие исполнения текстовых команд.
Реализация: прослежены обработчик вызова, регистрация исключения, возврат
безопасных полей и независимое уведомление источника; DSML проверяется после
обработки настоящих вызовов, примеры Markdown исключаются из поиска.
Полное соответствие всех модулей стандартам этим не заявляется.
Прежняя недоступность сервиса сохранена отдельным историческим свидетельством
standards-unavailable.json и не считается текущим результатом.

## v8std evidence

[v8std sentinel: id=std792, status=found, phase=review]
[v8std applied: phase=review, scope=tool-error-handling, ids_checked=[std499,std498,bslls:UsageWriteLogEvent,acc:153,acc:156], conclusion=clean]
[v8std discovered: phase=review, scope=tool-error-handling, query="перехват исключений журнал регистрации категории ошибок", top_ids=[std498,std499,bslls:BadExceptionCategory,bslls:UsageWriteLogEvent,acc:153,acc:156], new_ids=[bslls:UsageWriteLogEvent,acc:153,acc:156], decision=applied]
[v8std discovered: phase=review, scope=exception-category-generation, query="перехват исключений журнал регистрации категории ошибок", top_ids=[std498,std499,bslls:BadExceptionCategory,bslls:UsageWriteLogEvent,acc:153,acc:156], new_ids=[bslls:BadExceptionCategory], decision=not_relevant]

[v8std applied: phase=design, scope=tool-error-contract, ids_checked=[std499,std498], conclusion=clean]
[v8std applied: phase=implementation, scope=tool-error-diagnostic-path, ids_checked=[std499,std498], conclusion=clean]
