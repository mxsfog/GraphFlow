# Интерактивная визуализация графов

## Назначение

Модуль показывает реальные результаты работы пайплайна как интерактивный граф. Основной источник данных - классы OrientDB `SearchRun`, `NewsLink`, `Source`, `Topic`, `ModelRun`.

Frontend использует React Flow. Пользователь может выбрать запуск пайплайна, переключить нотацию, перемещать узлы, масштабировать схему и открывать детали выбранного узла.

## Что визуализируется

Для выбранного `SearchRun` строится граф:

```text
Пользователь -> SearchRun
SearchRun -> Google News RSS
SearchRun -> NewsLink
ModelRun -> NewsLink
NewsLink -> Source
SearchRun -> Topic
SearchRun -> OrientDB
SearchRun -> Google Sheets
```

Узлы:

- `Пользователь` - инициатор запроса.
- `SearchRun` - конкретный запуск поиска.
- `Google News RSS` - источник кандидатов.
- `ModelRun` - модель OpenRouter, которая оценила релевантность.
- `NewsLink` - найденные ссылки с `llm_score`, keywords и reason.
- `Source` - источник новости.
- `Topic` - поисковый запрос как тема.
- `OrientDB` и `Google Sheets` - места сохранения результата.

Связи:

- `запрос` - пользователь запустил поиск.
- `RSS запрос` - запуск обратился к Google News RSS.
- `найдено` - запуск сохранил найденную ссылку.
- `score` - модель оценила ссылку.
- `источник` - ссылка относится к источнику.
- `тема` - запуск относится к поисковому запросу.
- `сохранено` - результат записан в OrientDB.
- `экспорт` - результат выгружен в Google Sheets.

## Backend

Запуск API:

```bash
cd /mnt/d/ElectroMotiv
PYTHONPATH=src python3 -m electromotiv_pipeline graph-api --host 127.0.0.1 --port 8090
```

Проверка:

```bash
curl "http://127.0.0.1:8090/health"
curl "http://127.0.0.1:8090/api/search-runs"
curl "http://127.0.0.1:8090/api/graph/latest-run?notation=flow&limit=6"
```

Получить граф конкретного запуска:

```http
GET /api/graph/run/{run_id}?notation=flow&limit=6
```

Получить последний запуск:

```http
GET /api/graph/latest-run?notation=flow&limit=6
```

## Нотации

- `flow` - процессная схема с документами, компонентами и хранилищами.
- `use_case` - actor, системная рамка, use-case эллипсы и include-связи.
- `component` - компонентное представление тех же данных.
- `class` - классовое представление с секциями данных.

## Frontend

Запуск:

```bash
cd /mnt/d/ElectroMotiv/frontend
npm install
npm run dev
```

Открыть:

```text
http://127.0.0.1:5173
```

Frontend загружает список запусков из:

```text
http://127.0.0.1:8090/api/search-runs
```

Затем строит граф выбранного запуска через:

```text
http://127.0.0.1:8090/api/graph/run/{run_id}?notation={flow|use_case|component|class}&limit=6
```

По умолчанию выбирается первый запуск, где есть не менее четырех найденных ссылок. Это сделано для демонстрации: граф сразу открывается достаточно насыщенным, но в списке можно выбрать любой другой запуск.
