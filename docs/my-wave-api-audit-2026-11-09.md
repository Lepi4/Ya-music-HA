# Полный аудит API «Моей волны» и Rotor

Проверено 9 ноября 2026 года.

- Python-клиент: `yandex-music==3.2.0`.
- Источник инвентаря: `_client/radio.py`, `_client/wave.py`,
  `_client/rotor_sessions.py`, `_client/queue.py` и модели `rotor/*`.
- Домашний HA: 2026.11.0, установленная ЯМ-ХАОС 0.3.2.
- Вызовы изменения настроек, feedback, создания сессий и очередей во время
  аудита не выполнялись.

В текущем live-сеансе безопасно проверены через уже установленную интеграцию:

| Операция | Результат |
|---|---|
| `/status` | авторизация есть, найдено 10 медиаплееров, есть состояние Rotor-сеанса |
| `/wave` | API вернул 5 треков в первом пакете; это размер пакета, а не размер потока |
| `/wave/settings` | 5 настроений: `active`, `fun`, `calm`, `sad`, `all`; текущие `all`, `default`, `any` |

## 1. Station API — классический Rotor

Это рабочий уровень, на котором сейчас построено продолжение волны в интеграции.

### Чтение

| Метод клиента | HTTP endpoint | Назначение |
|---|---|---|
| `rotor_account_status()` | `GET /rotor/account/status` | статус пользователя Rotor, дополнительные ограничения и лимиты |
| `rotor_stations_dashboard()` | `GET /rotor/stations/dashboard` | персональная панель станций пользователя |
| `rotor_stations_list(language)` | `GET /rotor/stations/list?language=ru` | полный каталог станций; язык `en`, `uz`, `uk`, `us`, `ru`, `kk`, `hy` |
| `rotor_station_info(station)` | `GET /rotor/station/{station}/info` | описание станции, `settings`, `settings2`, `restrictions`, название и категория |
| `rotor_station_tracks(station, settings2, queue)` | `GET /rotor/station/{station}/tracks` | следующий пакет треков; первый запрос с `settings2=True`, продолжение с `queue=<последний ID>` |
| `rotor_station_stream(station)` | `GET /rotor/station/{station}/stream` | поток нейромузыки/generative, например `generative:focus` или `generative:calm` |

Ответ `rotor_station_tracks` содержит:

- `sequence` — треки и служебные элементы;
- `batch_id` — идентификатор пакета для feedback;
- `radio_session_id` — идентификатор новой session, если API его выдал;
- `id` — идентификатор станции/потока;
- `pumpkin` — служебный флаг.

Станция задаётся seed-строкой. Подтверждённые формы из клиента:

- `user:onyourwave` — общая «Моя волна»;
- `track:12345` — волна по треку;
- `artist:12345` — волна по исполнителю;
- `genre:rock` — волна по жанру;
- `album:12345` — волна по альбому;
- дополнительные станции и точные значения нужно брать из `stations_dashboard`,
  `stations_list` и их `id_for_from`, а не зашивать в интерфейс.

Поэтому «В дороге», «Для работы», «Утро», «Фокус», «Спорт», «Спокойная»,
жанры, эпохи и региональные станции должны отображаться как каталог ответа API.
Имена и идентификаторы у Яндекса могут меняться.

### Настройки станции

| Метод | HTTP endpoint | Изменяет данные |
|---|---|---|
| `rotor_station_settings2(station, mood_energy, diversity, language, type_)` | `POST /rotor/station/{station}/settings3` | да |

Поддерживаемые значения, которые сообщает клиент:

- `mood_energy`: `fun`, `active`, `calm`, `sad`, `all`;
- `diversity`: `favorite`, `popular`, `discover`, `default`;
- `language`: `not-russian`, `russian`, `any`;
- `type_`: `rotor`, `generative`.

Правильный интерфейс должен сначала прочитать `restrictions` у станции и строить
список из `possible_values`. Нельзя считать, что все значения доступны каждой
станции или аккаунту.

### Feedback классической станции

| Метод клиента | HTTP endpoint | Событие |
|---|---|---|
| `rotor_station_feedback` | `POST /rotor/station/{station}/feedback` | универсальный метод |
| `rotor_station_feedback_radio_started` | тот же endpoint | `radioStarted` |
| `rotor_station_feedback_track_started` | тот же endpoint | `trackStarted` |
| `rotor_station_feedback_track_finished` | тот же endpoint | `trackFinished` |
| `rotor_station_feedback_skip` | тот же endpoint | `skip` |

Универсальный метод принимает `timestamp`, `from`, `batch-id`, `trackId`,
`totalPlayedSeconds` и `streamId`. Для обычной волны нужны как минимум
`radioStarted`, `trackStarted`, `trackFinished`/`skip`, `trackId`, `batch-id`.

## 2. Wave API — сохранённое состояние «Моей волны»

| Метод клиента | HTTP endpoint | Назначение |
|---|---|---|
| `rotor_wave_last()` | `GET /rotor/wave/last` | последняя сохранённая волна пользователя: имя, описание, seeds, station ID |
| `rotor_wave_settings(seeds=None)` | `GET /rotor/wave/settings` | настройки волны, блоки, default station и `setting_restrictions`; `seeds` может быть `user:onyourwave` или набор seeds |
| `rotor_wave_last_reset()` | `POST /rotor/wave/last/reset` | сбрасывает последнюю волну; изменяющая операция |

Модель `Wave` содержит `name`, `description`, `seeds`, `station_id`,
`id_for_from`, `type`. Модель `WaveSettings` содержит `default_station`,
`blocks`, `setting_restrictions`. Через `serialized_seed` можно получить
готовые seeds вроде `settingDiversity:favorite`.

## 3. Новые Rotor Sessions

Это более современный API, который лучше подходит для полноценной реализации
«в дороге», нескольких seeds и детальных событий. В текущем 0.3.2 он ещё не
подключён.

### Создание и продолжение

| Метод клиента | HTTP endpoint | Назначение |
|---|---|---|
| `rotor_session_new(seeds, ...)` | `POST /rotor/session/new` | новая session по одному или нескольким seeds |
| `rotor_session_clone(radio_session_id, ...)` | `POST /rotor/session/{id}/clone` | копия существующей session с изменённым контекстом |
| `rotor_session_tracks(radio_session_id, queue, feedbacks)` | `POST /rotor/session/{id}/tracks` | следующий пакет через session ID; можно передать очередь и пачку feedback |

Параметры новой session:

- `seeds`: строки или список строк, например `user:onyourwave`, `genre:rock`,
  `track:12345`, `artist:12345`, а также `settingDiversity:discover`;
- `queue`: уже проигранные ID, чтобы не повторять их;
- `track_to_start_from`: стартовый трек;
- `include_tracks_in_response`, `include_wave_model`;
- `interactive`, `incognito`, `child`, `allow_explicit`.

Ответ session содержит `radio_session_id`, `batch_id`, `sequence`,
`accepted_seeds`, `description_seed`, `wave`, `terminated`, `interactive`.

### Session feedback

| Метод клиента | HTTP endpoint | Назначение |
|---|---|---|
| `rotor_session_feedback` | `POST /rotor/session/{id}/feedback` | одно событие `SessionEvent` |
| `rotor_session_feedback_radio_started` | тот же endpoint | старт радио |
| `rotor_session_feedback_track_started` | тот же endpoint | начало трека |
| `rotor_session_feedback_track_finished` | тот же endpoint | конец трека + секунды |
| `rotor_session_feedback_skip` | тот же endpoint | пропуск + секунды |
| `rotor_session_feedbacks` | `POST /rotor/session/{id}/feedbacks` | пачка событий одной session |
| `rotor_sessions_feedbacks` | `POST /rotor/sessions/feedbacks` | пачка событий нескольких sessions |

Модель `SessionEvent` допускает больше событий, чем старый station API:
`radioStarted`, `trackStarted`, `trackFinished`, `skip`, `skipFailed`, `like`,
`unlike`, `dislike`, `undislike`, `playableItemStarted`,
`playableItemFinished`, `playableItemSkip`, `playableItemLike`,
`playableItemUnlike`, `playableItemDislike`, `playableItemUndislike`,
`combinedQueueStarted`, `ad`.

## 4. Combined sessions

Это отдельный поток для объединения контента, например музыки и клипов.

| Метод клиента | HTTP endpoint | Назначение |
|---|---|---|
| `rotor_combined_session_new(supported_types, queue, child, allow_explicit)` | `POST /rotor/combined/session/new` | создать combined session |
| `rotor_combined_session_next(session_id, queue)` | `POST /rotor/combined/session/{id}/next` | получить продолжение |
| `rotor_combined_session_landing(supported_types, child, allow_explicit)` | `POST /rotor/combined/session/landing` | получить стартовую витрину |

Поддержанные типы в клиенте: `TRACK`, `CLIP`. Для текущего аудиоплеера это
низкий приоритет.

## 5. Нейромузыка / generative

Для станций `generative:*` используется отдельный feedback-контракт:

- `rotor_station_stream(station)` возвращает `data`, `version`, `stream`;
- `stream` содержит `id` и `url`;
- `rotor_station_stream_feedback(station, type_, stream_id)` отправляет
  `streamStarted`, `streamPlay` или `streamPause`.

Для generative потока не нужно отправлять обычные `radioStarted` и
`trackStarted`: документация клиента разделяет эти два протокола.

## 6. Очередь HA и очередь Rotor — разные вещи

В клиенте есть ещё четыре метода:

- `queues_list(device=None)` — `GET /queues`;
- `queue(queue_id)` — `GET /queues/{id}`;
- `queue_update_position(queue_id, current_index, device=None)` — изменение позиции;
- `queue_create(queue, device=None)` — создание очереди.

Это облачная очередь аккаунта с device header. Она не равна `batch_id`/`queue`
у Rotor и не равна очереди конкретной Яндекс-колонки. В предыдущем live-аудите
сырой запрос `/queues` без device header вернул 400, поэтому использовать его
как универсальную очередь станции нельзя.

## 7. Что имеет смысл добавить в интерфейс

1. В разделе «Моя волна» — каталог `stations_dashboard` и `stations_list`,
   сгруппированный по `id_for_from`: личные, настроение, занятие, жанр, эпоха,
   язык/регион и редакционные станции. Пустые категории скрывать.
2. В плеере — отдельные действия «Волна по треку», «Волна по исполнителю»,
   «Волна по жанру», где seed получается из текущей композиции и API, а не из
   текста названия.
3. Для «В дороге», «Для работы», «Утро» и похожих режимов запускать station ID,
   который пришёл из каталога, и использовать тот же бесконечный cursor/feedback.
4. Перевести текущий контроллер с `rotor_station_tracks` на session API после
   проверки его реального ответа для этого аккаунта: session даёт меньше риска
   потерять cursor, поддерживает queue и позволяет отправлять feedback пачкой.
5. Для генеративных режимов сделать отдельный блок, не смешивая их с обычной
   очередью треков.

## 8. Границы текущего сканирования

Полный список методов и моделей просканирован локально по установленному wheel.
Безопасно вызваны только чтение и уже существующие read-only маршруты интеграции.
Не вызывались `rotor_wave_last_reset`, `rotor_station_settings2`, любые
feedback, создание/clone session, combined session, создание очереди и
изменение позиции. Их наличие в отчёте означает наличие метода API, а не то,
что операция разрешена аккаунту или уже работает на всех типах станций.
