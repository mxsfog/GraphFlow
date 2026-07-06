# ElectroMotiv: Python-пайплайн новостей

Локальный Python-проект для поиска новостей, оценки релевантности через OpenRouter и сохранения результатов в OrientDB и Google Sheets.

## Назначение

Проект решает прикладную задачу: по поисковому запросу собрать новостные ссылки, оценить их релевантность через LLM и сохранить структурированный результат в графовую базу OrientDB. Дополнительно результат может записываться в Google Sheets для демонстрации и ручного просмотра.

Основной контур:

```text
Python CLI -> Google News RSS -> LLM OpenRouter -> OrientDB + Google Sheets
```

## Состав проекта

- `src/electromotiv_pipeline` - основной Python-код.
- `tests` - unit-тесты.
- `orientdb/schema.sql` - схема графовой базы.
- `infra/docker-compose.yml` - локальный контейнер OrientDB.
- `scripts/start_stack.sh` - запуск инфраструктуры.
- `scripts/check_environment.sh` - проверка окружения и Docker.
- `docs/PYTHON_PIPELINE.md` - инструкция по пайплайну.
- `docs/D_ONLY_STORAGE.md` - контроль хранения Docker-данных на диске D.

## Требования

- Python 3.11+.
- Docker Desktop или Docker Engine.
- Доступ к OpenRouter API.
- Локальная рабочая директория на диске D.

Секреты хранятся только в `.env`. Файл `.env` не коммитится.

## Конфигурация

Создать `.env` на основе `.env.example`:

```bash
cp .env.example .env
```

Обязательные параметры:

```env
OPENROUTER_API_KEY=replace_with_openrouter_key
OPENROUTER_MODEL=deepseek/deepseek-v4-flash
ORIENTDB_ROOT_PASSWORD=replace_with_strong_local_password
ORIENTDB_DATABASE=news
GOOGLE_SHEETS_ENABLED=false
GOOGLE_SHEETS_SPREADSHEET_ID=replace_with_google_spreadsheet_id
GOOGLE_SHEETS_SHEET_NAME=news_links
GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE=key.txt
SEARCH_QUERY=(oil OR crude OR Brent OR WTI) price spike market futures week
SEARCH_MAX_RECORDS=10
```

`ORIENTDB_AUTH_HEADER` можно не задавать: Python-код сформирует Basic Auth из `ORIENTDB_ROOT_PASSWORD`.

Для записи в Google Sheets нужно:

- положить service account JSON в локальный файл, например `key.txt`;
- выдать этому service account доступ редактора к Google-таблице;
- указать `GOOGLE_SHEETS_ENABLED=true`;
- указать `GOOGLE_SHEETS_SPREADSHEET_ID` и `GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE`.

Файл service account не коммитится.

## Запуск OrientDB

```bash
cd /mnt/d/ElectroMotiv
bash scripts/start_stack.sh
```

Проверить доступность:

```bash
PYTHONPATH=src python3 -m electromotiv_pipeline check-orientdb
```

OrientDB Studio:

```text
http://127.0.0.1:2480
```

## Запуск пайплайна

```bash
cd /mnt/d/ElectroMotiv
PYTHONPATH=src python3 -m electromotiv_pipeline run --model deepseek/deepseek-v4-flash --ensure-schema
```

Результат:

- JSON-файл в `outputs/python_news_links.json`;
- вершины и ребра в OrientDB.
- строки в Google Sheets, если `GOOGLE_SHEETS_ENABLED=true` или указан флаг `--save-sheets`.

Разовый запуск с записью в Google Sheets:

```bash
PYTHONPATH=src python3 -m electromotiv_pipeline run --model deepseek/deepseek-v4-flash --ensure-schema --save-sheets
```

## Структура данных в OrientDB

Вершины:

- `SearchRun` - запуск пайплайна.
- `NewsLink` - найденная новость.
- `Source` - источник новости.
- `Topic` - тематическая привязка.
- `ModelRun` - ответ LLM.

Ребра:

- `Found` - запуск нашел новость.
- `FoundBy` - совместимость со старой схемой.
- `FromSource` - новость относится к источнику.
- `About` - новость относится к теме.
- `AnalyzedBy` - новость оценена моделью.
- `AnalyzedAs` - совместимость со старой схемой.

## Локальная панель просмотра

```bash
PYTHONPATH=src python3 -m electromotiv_pipeline dashboard --host 127.0.0.1 --port 8088
```

Открыть:

```text
http://127.0.0.1:8088
```

## Проверки

```bash
ruff check src tests
PYTHONPATH=src python3 -m pytest -q
python3 -m compileall -q src tests
```

## Ограничения и риски

- Google News RSS используется как демонстрационный источник.
- OpenRouter API требует действующий ключ.
- Google Sheets требует service account с доступом редактора к таблице.
- Docker image layers управляются Docker daemon; их размещение на D задается вне проекта.
- Raw-ответ LLM сохраняется в OrientDB, но секреты туда не записываются.
