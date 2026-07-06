# Python-пайплайн

## Назначение

Пайплайн собирает новости из Google News RSS, удаляет дубли, оценивает релевантность через OpenRouter и сохраняет результат в OrientDB. При включенной настройке результат также записывается в Google Sheets.

## Схема

```text
Google News RSS -> Python -> LLM OpenRouter -> OrientDB + Google Sheets
```

## Запуск

```bash
cd /mnt/d/ElectroMotiv
PYTHONPATH=src python3 -m electromotiv_pipeline run --model deepseek/deepseek-v4-flash --ensure-schema
```

## Проверка без записи

```bash
PYTHONPATH=src python3 -m electromotiv_pipeline run --model deepseek/deepseek-v4-flash --no-save
```

## Запись в Google Sheets

Настройки:

```env
GOOGLE_SHEETS_ENABLED=true
GOOGLE_SHEETS_SPREADSHEET_ID=replace_with_google_spreadsheet_id
GOOGLE_SHEETS_SHEET_NAME=news_links
GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE=key.txt
```

Таблица должна быть расшарена на `client_email` из service account JSON с правом редактирования.

Разовый запуск без изменения `.env`:

```bash
PYTHONPATH=src python3 -m electromotiv_pipeline run --model deepseek/deepseek-v4-flash --ensure-schema --save-sheets
```

## Проверка базы

```bash
PYTHONPATH=src python3 -m electromotiv_pipeline check-orientdb
```

## Локальная панель просмотра

```bash
PYTHONPATH=src python3 -m electromotiv_pipeline dashboard --host 127.0.0.1 --port 8088
```

## Оценка релевантности

Оценка выполняется моделью OpenRouter по общим критериям соответствия текущему поисковому запросу.

Пайплайн не использует жестко заданные доменные ключевые слова и не смешивает LLM-оценку с локальной формулой. Модель возвращает:

- `llm_score` - оценку релевантности от 0 до 1;
- `keywords` - ключевые слова и сущности, которые модель сама выделила как основание оценки;
- `reason` - краткое объяснение оценки.

## Хранимые классы

- `SearchRun`
- `NewsLink`
- `Source`
- `Topic`
- `ModelRun`

## Требования к эксплуатации

- Не выводить и не коммитить `.env`.
- Не коммитить `.runtime`.
- Перед демонстрацией выполнить `ensure-schema`.
- При ошибке `401` проверить ключ OpenRouter.
- При ошибке `No endpoints found` проверить slug модели.
