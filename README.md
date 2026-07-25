# GraphFlow

Проект производственной практики: обработка документов и новостей, построение графовых моделей, хранение в OrientDB, экспорт в Google Sheets и интерактивная визуализация.

## Архитектура

```text
Google News RSS -> Python -> OpenRouter -> OrientDB -> Graph API -> React Flow
                                      \-> Google Sheets
DOCX -> OOXML reader -> universal import profile -> OrientDB -> Graph API -> React Flow / Three.js
```

n8n в текущую архитектуру не входит.

Основные компоненты:

- `src/electromotiv_pipeline` - Python-пайплайн, Graph API и HTML-панель;
- `frontend` - React 19 и React Flow;
- `orientdb/schema.sql` - вершины, ребра и индексы OrientDB;
- `profiles` - декларативные профили отображения документов в граф;
- `infra/docker-compose.yml` - закрепленный образ OrientDB;
- `tests` - модульные и интеграционные тесты;
- `.github/workflows/ci.yml` - CI для Python, frontend и OrientDB.

## Требования

- рабочая директория на диске `D:` (`/mnt/d/...` в WSL);
- Python 3.11 или новее;
- `uv` 0.10.11 или новее;
- Node.js 22 или новее;
- Docker Desktop с WSL integration или Docker Engine;
- OpenSSL;
- действующий ключ OpenRouter для реального поиска.

## Установка и запуск

На новой машине или виртуальной машине:

```bash
cd /mnt/d/electromotiv
bash scripts/bootstrap_local.sh
bash scripts/run_local_solution.sh
```

`bootstrap_local.sh` создает локальные каталоги на диске D, устанавливает зависимости по lock-файлам и выполняет проверки. Если `.env` отсутствует, скрипт создает его из `.env.example` и генерирует локальные пароли для OrientDB и Graph API.

После запуска:

- frontend: `http://127.0.0.1:5173`;
- Graph API: `http://127.0.0.1:8090`;
- OrientDB Studio: `http://127.0.0.1:2480`;
- логи: `.runtime/logs`.

Логин и пароль frontend берутся из `GRAPH_API_USERNAME` и `GRAPH_API_PASSWORD` в локальном `.env`. Доступ к данным без Basic Auth запрещен.

## Конфигурация

Секреты задаются только в `.env`, который исключен из Git:

```env
OPENROUTER_API_KEY=replace_with_openrouter_key
OPENROUTER_MODEL=deepseek/deepseek-v4-flash
ORIENTDB_ROOT_PASSWORD=replace_with_strong_local_password
ORIENTDB_DATABASE=news
GRAPH_API_USERNAME=admin
GRAPH_API_PASSWORD=replace_with_graph_api_password
GOOGLE_SHEETS_ENABLED=false
GOOGLE_SHEETS_SPREADSHEET_ID=replace_with_google_spreadsheet_id
GOOGLE_SHEETS_SHEET_NAME=news_links
GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE=key.txt
```

Ключи, service account JSON и `.env` нельзя добавлять в репозиторий.

## Поиск новостей

```bash
bash scripts/run_python_pipeline.sh \
  --query "Will Bitcoin be above 70000 dollars in August" \
  --max-records 10 \
  --ensure-schema \
  --save-sheets \
  --output outputs/bitcoin_august.json
```

Модель берется из `OPENROUTER_MODEL`. Для разового переопределения используется `OPENROUTER_MODEL_OVERRIDE`.

Пайплайн:

1. получает кандидатов из Google News RSS;
2. удаляет дубли по URL;
3. передает заголовки и сниппеты в OpenRouter;
4. принимает только ссылки из исходного набора кандидатов;
5. проверяет JSON, диапазон оценки и конечность чисел;
6. сохраняет отдельный `SearchResult` для каждого запуска;
7. при необходимости добавляет строки в Google Sheets в режиме `RAW`.

Пустой RSS, пустой ответ модели, отсутствие валидных кандидатов и частичная ошибка Google Sheets завершаются явной ошибкой, а не ложным успешным результатом.

## Модель OrientDB

Вершины:

- `SearchRun` - запуск пайплайна и его статус;
- `SearchResult` - оценка конкретной новости в конкретном запуске;
- `NewsLink` - каноническая новостная ссылка;
- `Source`, `Topic`, `ModelRun` - источник, тема и запуск модели;
- `GraphDocument`, `GraphNode` - пользовательский или декомпозированный граф с периодом актуальности узлов;
- `GraphAnnotation` - версия пользовательских изменений элемента;
- `GraphGroup` - вложенная группа узлов и сохраненное состояние сворачивания;
- `GraphTemplate` - повторно используемая структура узлов, ребер и групп.
- `GraphView` - именованное состояние фильтров, уровней, режима и viewport карты.

Ребра:

- `Found`: `SearchRun -> SearchResult`;
- `References`: `SearchResult -> NewsLink`;
- `FromSource`: `SearchResult -> Source`;
- `About`: `SearchRun -> Topic`;
- `AnalyzedBy`: `SearchRun -> ModelRun`;
- `AnalyzedAs`: `ModelRun -> SearchResult`;
- `GraphConnection`: `GraphNode -> GraphNode`.

История оценки не хранится в `NewsLink`: одинаковый URL может иметь разные оценки в разных `SearchRun` без перезаписи предыдущего результата.

## Редактор графа

Frontend поддерживает:

- перемещение, zoom, выбор и фильтрацию узлов и ребер;
- нотации Flow, UML Use Case, Component и Class;
- типы ребер `todo`, `follow`, `include`, `properties` и другие;
- редактирование подписи, формы, периода актуальности, изображения и properties;
- загрузку PNG, JPEG, WebP или GIF до 700 КБ с хранением в OrientDB;
- сохранение координат и всех полей с контролем ревизий;
- сброс каждого поля и координат к базовому значению;
- обзорная, Follow, Timeline и Structure раскладки с обработкой циклов;
- ортогональная маршрутизация и разнесение параллельных ребер;
- создание редактируемой копии, новых узлов и новых ребер;
- вложенные группы, сворачивание дочерних графов и агрегирование внешних связей;
- сохранение всего графа или выбранного фрагмента как шаблона;
- добавление сохраненного шаблона в редактируемый граф с новыми идентификаторами;
- отдельный интерактивный 3D-режим на Three.js с вращением камеры, zoom, drag и выбором элементов.
- показ и скрытие иерархических уровней, сворачивание отдельной ветви на узле;
- фильтры по статусу, региону, организации и году;
- подсветку узлов с одинаковым названием в нескольких картах;
- карточку узла с описанием, источником, статусом и плановым/фактическим значением;
- редактируемый период актуальности `created_at`/`ended_at`;
- динамическую легенду узлов и связей;
- сохранение именованных представлений в OrientDB;
- экспорт текущей схемы в SVG и автономную HTML-презентацию.

Правки разделены по `graph_id`, элементу и нотации. Конфликт устаревшей ревизии возвращает HTTP 409.

Предметные атрибуты читаются из `properties` без жесткой привязки к языку ключа. Основные
ключи: `status`/`статус`, `region`/`регион`, `organization`/`организация`, `year`/`год`,
`description`/`описание`, `source`/`источник`, `planned`/`план`, `actual`/`факт`.
Поля `created_at` и `ended_at` задают начало и окончание актуальности в формате ISO 8601;
пустой `ended_at` означает открытый период.

## Декомпозиция документа

Команда отправляет указанный текст в настроенную модель OpenRouter и сохраняет полученные узлы и связи в OrientDB:

```bash
PYTHONPATH=src .venv/bin/python -m electromotiv_pipeline decompose-document \
  --file docs/example.txt \
  --title "Национальный проект" \
  --graph-id national-project
```

Команда применяет схему автоматически. Текст отправляется во внешний API только после явного запуска команды.

## Универсальный импорт DOCX

Основная команда принимает любое количество DOCX. Без профиля она сохраняет структуру
документа: документ, разделы, абзацы, списки, таблицы и строки таблиц.

```bash
PYTHONPATH=src .venv/bin/python -m electromotiv_pipeline import-documents \
  --file "/path/to/document-1.docx" \
  --file "/path/to/document-2.docx" \
  --graph-id document-graph \
  --title "Граф документов" \
  --output outputs/document_graph.json
```

Предметная семантика задается JSON-профилем:

```bash
PYTHONPATH=src .venv/bin/python -m electromotiv_pipeline import-documents \
  --file "/path/to/technology-maps.docx" \
  --file "/path/to/support-programs.docx" \
  --profile profiles/technology_leadership.json \
  --graph-id technology-leadership \
  --title "Технологическое лидерство" \
  --output outputs/technology_leadership_graph.json
```

Профиль определяет критерии распознавания документов, иерархии таблиц, правила разделов,
типы узлов и ребер, тематические словари и междокументные связи. Файлы назначаются ролям по
содержимому, а не по имени или позиции аргумента. Для нового формата создается новый профиль;
изменение Python-кода не требуется.

Тема направления задается профилем отдельно от слов, автоматически найденных в названии.
Это исключает ложное назначение батареи направлению «Роботы» только из-за словосочетания
«для робототехники». Автоматически созданные связи содержат формальное основание совпадения.

## Профиль технологического лидерства

Совместимая команда использует тот же универсальный движок с готовым профилем:

```bash
TECHNOLOGY_FILE="/path/to/Технологические_карты.docx"
PLAN_FILE="/path/to/Единый_план.docx"

PYTHONPATH=src .venv/bin/python -m electromotiv_pipeline import-technology-maps \
  --technology-file "$TECHNOLOGY_FILE" \
  --plan-file "$PLAN_FILE" \
  --profile profiles/technology_leadership.json \
  --graph-id technology-leadership \
  --title "Технологическое лидерство" \
  --output outputs/technology_leadership_graph.json
```

DOCX читается локально как OOXML. Профиль сопоставляет таблицы по названиям колонок, а
программные разделы - по настраиваемым выражениям. Индексы таблиц, имена файлов и конкретные
позиции абзацев в Python-коде не используются. Данные не покидают компьютер.

Иерархия технологий: `product -> technology_block -> process -> technology`. Иерархия
программ: `program -> program_goal -> indicator/activity -> project -> expected_result`.
Одинаковые технологии и мероприятия хранятся одним узлом с несколькими направлениями.
Готовность технологий отображается зеленым, оранжевым или красным цветом. Каждый узел и
каждая связь содержат `start_date`, `end_date`, `source`, `description` и `status`.

В исходном едином плане используются официальные наименования ГП
«Научно-технологическое развитие Российской Федерации» и НПТЛ «Беспилотные авиационные
системы». В интерфейсе они сгруппированы под краткими названиями «Госпрограмма „Наука“» и
«Федеральный проект БАС».

Междокументные `supports`, `develops` и `intersects_with` создаются по тематическим словарям
и лексическому пересечению, заданным в профиле. Основание и оценка совпадения сохраняются в
properties ребра. Эти связи требуют предметной проверки.

## Проверки

```bash
UV_CACHE_DIR=$PWD/.runtime/cache/uv uv run --frozen ruff check src tests
UV_CACHE_DIR=$PWD/.runtime/cache/uv uv run --frozen python -m pytest -q
ORIENTDB_INTEGRATION=1 ORIENTDB_DATABASE=news_ci \
  UV_CACHE_DIR=$PWD/.runtime/cache/uv \
  uv run --frozen python -m pytest -q tests/test_orientdb_integration.py
npm run test --prefix frontend
npm run build --prefix frontend
docker compose --env-file .env -f infra/docker-compose.yml config -q
```

CI выполняет эти проверки на Python 3.14 и Node.js 22 с реальным контейнером OrientDB.

## Ограничения

- Google News RSS остается демонстрационным источником и не гарантирует полноту выдачи.
- Basic Auth безопасен только на loopback без TLS; Graph API запрещает внешний bind.
- Автоматический режим универсален структурно, но не выполняет универсальное семантическое
  понимание текста. Предметные типы и связи требуют профиля или отдельно запущенной LLM.
- Docker Compose хранит данные OrientDB в `.runtime` на D, но размещение слоев Docker image определяется настройками Docker daemon.
- 3D-модуль загружается отдельным chunk размером около 373 КБ gzip только после переключения в 3D.

Подробности: [Python-пайплайн](docs/PYTHON_PIPELINE.md), [визуализация графов](docs/GRAPH_VISUALIZATION.md), [хранение на D](docs/D_ONLY_STORAGE.md).
