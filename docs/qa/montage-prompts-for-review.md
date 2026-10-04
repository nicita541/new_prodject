# Действующие инструкции монтажа: для совместной правки

Обновление 2026-10-05: финансовый слой из раздела 7 ниже снят по прямому указанию пользователя. Он больше не проверяет баланс, не считает деньги и не блокирует монтаж после сетевого сбоя. Запрос имеет максимум три попытки. Текст ниже сохраняет исторический срез; при подтверждённых обеих границах OP теперь действует приоритет всей заставки, включая её персонажей, реакции и отдельные реплики. Около 90 секунд — только подсказка поиска, а не заданная длина выреза. Кадры проверки титров стали крупнее; стандартный текстовый контекст увеличен до 64,000 байт. Сюжет после эндинга сохраняется.

Срез на 2026-10-04, код `2d8cb06f5cdd1a585ba1f62666e115a8e2fd856d`. Этот файл — обзор и место для обсуждения; его редактирование само по себе не меняет запросы модели. Работающие инструкции, настройки и финансовое состояние здесь не изменялись.

Версии: story12, edge13, roles4, sequence7, titles6, storyboard2, pacing14, closing5, global5, speech4, planner9. Ниже английские цитаты дословно воспроизводят авторские строки активного кода; русский текст объясняет их действие. В полном запросе также есть фактические кадры, распознанная речь, соседние фрагменты и строгая JSON-схема.

## Что требуется по сохранённому выбору пользователя

Источник: [спецификация](F:/new_prodject/docs/specs/montage-quality.md:26).

- «Последовательный сокращённый сюжет серии: понятно, что произошло, без потери важных сцен.»
- «Сохранять почти все реакции и шутки ради атмосферы.»
- Убирать длинные пустые пролёты/ожидание и неинформативные повторы; сохранять важное молчаливое действие.
- Убирать подтверждённые чистые OP/ED, рекламу и анонс следующей серии; оставлять сюжет этой серии после титров.
- Баланс сохранён; нет заданной длительности, процента удаления или ограничения расходов.

## 1. Общий профиль: сильная защита атмосферы

Источник: [app/editorial.py](F:/new_prodject/app/editorial.py:25). У проверяемого Marie job все четыре флага включены: `preserve_reactions`, `preserve_humor`, `remove_empty_holds`, `remove_exact_repetition`.

> Balanced chronological condensation: remove empty dwelling and exact repetition, with no duration or removal quota.
>
> Preserve almost all character reactions and emotional pauses for atmosphere, including quiet or unchanged poses; plot progress is not required.
>
> Preserve almost all jokes, banter, comic timing and their setup/payoff even without new plot facts.

Следствие: неподвижная поза может быть признана атмосферной паузой и сохранена. В коде также существуют `Do not shorten empty holds or neutral scenery.` и `Do not remove repetitions.`, но при этих включённых флагах они **не добавляются** в запрос Marie. Прямого запрета удалять пустые пролёты здесь нет.

## 2. Сокращение сюжета: целые units и значимые паузы

Источник: [app/story.py](F:/new_prodject/app/story.py:310).

> Make a noticeably edited, concise viewing, not an almost complete episode split into clips.
>
> Omit empty waiting and exact repeated information. There is no duration or count quota.
>
> A selected unit is retained WHOLE, including action before/after its words.
>
> A reaction, expression or held pose can convey the atmosphere even without new plot facts; preserve it.

Сокращение требуется явно, однако сохраняется целый исходный unit. Если один unit объединяет полезную реакцию и пустой хвост, защита реакции может удержать весь unit. Это возможный механизм, а не доказанная причина конкретного пролёта.

Независимая проверка пропусков, [app/story.py](F:/new_prodject/app/story.py:59):

> Never remove an action setup/progression then retain only its last few frames or reply.
>
> Empty scenery/waiting may go only when the retained surrounding scene already conveys the needed state/location and no new action or specific atmosphere is lost. Do not invent emotions from generic poses.
>
> For waiting use retained_witness=none. If unsure keep=true.

Здесь защищены начало, развитие и завершение действия. Повтор требует более раннего сохранённого свидетеля; одинаковые слова сами по себе недостаточны. Одобрение удаления требует уверенности не ниже 0.9 и отсутствия защищённого сюжетного/атмосферного содержания.

## 3. Титры, OP и preview: весь unit должен быть несюжетным

Первичная классификация, [app/source_roles.py](F:/new_prodject/app/source_roles.py:190):

> The whole unit must be nonstory to remove it. Character dialogue and current-episode narrator, new chronological actions, almost all jokes/reactions/emotional atmosphere remain even under credits.
>
> A series-title card alone without confirmed sequence context is insufficient; mixed story/dialogue under credits remains.
>
> Any mixed unit or uncertainty is kept. No source-time heuristics, deletion quota or plot-progress requirement.

Это наиболее жёсткий барьер удаления production-материала: видимая надпись с названием сама по себе не доказывает целую OP/ED-последовательность. Требуются признаки и контекст последовательности, уверенность ≥0.9 и отсутствие подтверждённого сюжета этого эпизода.

Скептическая вторая проверка, [app/source_roles.py](F:/new_prodject/app/source_roles.py:217):

> Independent skeptical review. Do NOT trust the previous role claims.
>
> Mixed or ambiguous units MUST be current_story or uncertain; meaningful_story/reaction_or_humor blocks deletion.
>
> Preview banter is not current-episode atmosphere; current-story banter and mixed footage must remain.

Две проверки должны согласиться с конкретной ролью. Недоверие направлено на предыдущий вывод модели, а не на пользовательское желание удалить заставку. Неудача одной проверки удерживает спорный материал. Реакция внутри подтверждённого preview **не обязана** сохраняться как атмосфера текущей серии.

## 4. Границы заставки и видимые титры

Источник: [app/production_sequence.py](F:/new_prodject/app/production_sequence.py:138).

> ASR over opening/ending songs or dub introductions is not an outside story witness.
>
> Preserve genuine interleaved story, silent causal action, jokes and emotional consequences as narrative_units.
>
> If sequence identity or either boundary is uncertain use kind=uncertain.

Источник: [app/titles.py](F:/new_prodject/app/titles.py:296).

> Music/silence alone is not evidence. Preserve new silent action and character dialogue even over credits.

Границы последовательности требуют уверенности ≥0.85; отдельный чистый титр тоже проверяется с порогом ≥0.85. Речь и знакомые персонажи могут встречаться в OP, поэтому распознавание требует доказать принадлежность действия текущей серии, а не просто заметить движение или слова.

## 5. Удаление пустого ожидания: отдельный проход pacing

Источник: [app/pacing.py](F:/new_prodject/app/pacing.py:299).

> Do not assign a later reaction to an earlier empty courtyard, or let one needed departure frame protect every following unchanged view.
>
> Retain the developing action and its distinct reaction; trim redundant neutral dwell between them when the retained surrounding frames already establish the location and causal transition.
>
> story_change=true includes essential emotional understanding even without physical change.
>
> action/setup/reaction and story_change=true are preserved. Only waiting/scenery/repeat with story_change=false and concrete visible evidence can be removed. Credit removal is a separate sequence classifier: mark production_credit and keep it here.

Уже есть прямой запрет приписывать более позднюю реакцию пустому двору. Но если модель присвоит пустому кадру эмоциональное значение (`story_change`/`reaction_or_humor`), удаление блокируется. Pacing намеренно не удаляет production_credit: для этого предназначены другие классификаторы. Если они не подтвердили OP, pacing не исправит это удалением титров.

## 6. Глобальный отбор: защита неполных сведений

Источник: [app/analysis.py](F:/new_prodject/app/analysis.py:550).

> uncertainty preserves it. An event with summary_complete=false has missing facts and MUST remain.
>
> For an omission containing any reaction, joke or atmospheric beat mark reaction_or_humor=true; such events remain.

Удаление на этом уровне также требует уверенности ≥0.85. Один широкий event с реакцией может сохраниться целиком; более точное сокращение должно произойти внутри него на предыдущих проходах. Неполное описание не является основанием удалить сцену.

## 7. Финансовые и форматные ограничения — отдельный слой

Источник: [app/deepseek.py](F:/new_prodject/app/deepseek.py:29). `TOTAL_BUDGET=None`, `EPISODE_BUDGET=None`: искусственного общего/эпизодного лимита денег нет. Проверяются доступный баланс и подтверждённость оплаченного ответа; неизвестный расход останавливает новые оплаты. Разрешённая политика — максимум два повтора после первого запроса, только для подтверждённо оплаченных допустимых ошибок ответа. Это не правило удаления кадров.

Строгая дисциплина ответа, [app/deepseek.py](F:/new_prodject/app/deepseek.py:524):

> Enum values are exhaustive allowed values, never examples. Use only supplied IDs even when images show other labels; those labels are context evidence, not additional output targets. Return exactly the coverage requested by the task.

Это запрещает придуманные IDs и сцены. Запрет не следует ослаблять ради прохождения запроса. В pacing ошибка удалённого провайдера может переключить оставшиеся проверки на локальную модель: [app/pacing.py](F:/new_prodject/app/pacing.py:40). Такой fallback меняет исполнителя, а не редакторский профиль.

## Что уже установлено и что пока предположение

- Первый свежий Marie-результат сохранил начало OP, preview и проверяемый пустой двор; почти все контрольные точки пробуждения/реакции сохранились. Он использовал более ранние roles3/sequence6/pacing13/titles5, поэтому не доказывает ошибку нынешних версий. В pacing тогда подтверждён локальный fallback после сбоя проверки баланса.
- Второй запуск не дал outputs: в подтверждении требовался только ID A, но модель вернула A–D из контекстного листа. Строгая схема корректно отвергла ответ; расход был подтверждён. Добавленная дисциплина IDs адресует этот конкретный сбой.
- Третий запуск также остановился без outputs; точная причина финансового/ответного сбоя диагностируется отдельно. Редакторское качество этого запуска ещё не оценено.
- Не доказано, что конкретный пустой двор удержан именно защитой атмосферы: ранее найденные защищённые диапазоны не покрывали эту контрольную точку. Не доказан актуальный stale-cache сбой. Кэш включает версии смысловых проходов; fallback имеет собственное происхождение.

## Места для совместной переформулировки — пока не применены

1. Развести **реакцию персонажа** и **нейтральную неподвижную выдержку**: какую конкретную эмоцию/новую реакцию должно показывать сохранение, если поза не меняется?
2. Сформулировать единый порядок: сначала установить принадлежность OP/preview/текущему эпизоду, затем защищать атмосферу именно текущего эпизода. Этот смысл уже есть, но повторён разными словами в нескольких запросах.
3. Согласовать «заметно сокращённый просмотр» с широким «эмоциональная пауза сохраняется»: пустой остаток после завершённой реакции не должен автоматически получать её защиту.
4. Обсудить, достаточно ли нынешних кадров/контекста для подтверждения заставки без читаемой надписи. Снижать порог уверенности без разбора конкретных исходных кадров пока не предложено.

После согласования текста нужны отдельное изменение исходных запросов, новая версия соответствующего кэша и проверка на исходнике/выходе. Этот обзор не разрешает удалять важное действие, принимать лишние IDs или автоматически снимать остановку при неизвестном расходе.
