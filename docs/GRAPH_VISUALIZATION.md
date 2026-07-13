# Интерактивная визуализация графов

## Назначение

Модуль отображает результаты новостного пайплайна и пользовательские графы из OrientDB. Backend реализован на Python, frontend - на React 19 и `@xyflow/react`.

## Доступ

Graph API запускается только на loopback без TLS:

```bash
PYTHONPATH=src .venv/bin/python -m electromotiv_pipeline graph-api \
  --host 127.0.0.1 \
  --port 8090
```

Все `/api/...` маршруты требуют Basic Auth из `GRAPH_API_USERNAME` и `GRAPH_API_PASSWORD`. `/health` не требует авторизации, но выполняет реальный запрос к OrientDB. CORS разрешен только для localhost-origin.

## API

```http
GET  /health
GET  /api/session
GET  /api/search-runs
GET  /api/graph/schema
GET  /api/graph/latest-run?notation=flow&limit=6
GET  /api/graph/run/{run_id}?notation=flow&limit=6
GET  /api/graph/custom/{graph_id}?notation=flow
POST /api/graph/annotations
POST /api/graph/annotations/batch
POST /api/graphs
```

Ответ графа:

```json
{
  "graph_id": "run:uuid",
  "title": "Запуск: запрос",
  "notation": "flow",
  "nodes": [
    {
      "id": "result-id",
      "label": "Новость",
      "type": "news",
      "shape": "document",
      "position": {"x": 330, "y": 0},
      "style": {"background": "#f8fafc", "borderColor": "#0f766e"},
      "data": {"llm_score": 0.91, "annotation_revision": 2}
    }
  ],
  "edges": [
    {
      "id": "edge-id",
      "source": "run",
      "target": "result-id",
      "type": "found",
      "label": "найдено",
      "style": {"stroke": "#2563eb"},
      "data": {"annotation_revision": 0}
    }
  ]
}
```

Новостной граф строится из реального пути `SearchRun.out('Found')`; каждое найденное значение является отдельным `SearchResult`. Пользовательские графы читаются из `GraphNode` и физических ребер `GraphConnection`.

## Постоянные изменения

Пример сохранения узла:

```json
{
  "graph_id": "run:uuid",
  "notation": "flow",
  "element_id": "result-id",
  "element_kind": "node",
  "revision": 2,
  "payload": {
    "label": "Новое название",
    "shape": "document",
    "createdAt": "2026-07-10T10:00:00Z",
    "imageUrl": "data:image/png;base64,...",
    "position": {"x": 100, "y": 200},
    "properties": [{"id": "p1", "key": "status", "value": "done"}]
  }
}
```

Аннотации хранятся в `GraphAnnotation` с составным уникальным индексом. Поля `graph_id`, `notation`, `element_kind` и `element_id` определяют элемент. `revision` обеспечивает optimistic locking: устаревшая запись получает HTTP 409.

Frontend последовательно отправляет изменения одного элемента, сохраняет последнее значение перед сменой графа или нотации и использует batch-маршрут для координат после раскладки.

## Редактор структуры

Новостной граф является исходным представлением. Кнопка создания редактируемой копии сохраняет его как `GraphDocument`. В пользовательском графе можно добавлять узлы и ребра. Backend проверяет уникальность идентификаторов и наличие обоих концов связи.

Декомпозиция текстового документа выполняется отдельной CLI-командой `decompose-document`. LLM возвращает ограниченную JSON-структуру, после проверки узлы и ребра записываются в `GraphNode` и `GraphConnection`.

## Нотации

- `flow` - процессы, условия, документы и хранилища;
- `use_case` - actor, системная граница, эллипсы вариантов использования и `include` только для соответствующего типа ребра;
- `component` - компоненты, документы и хранилища;
- `class` - прямоугольники с секциями атрибутов и методов.

Смена нотации меняет форму, стиль и структуру представления, но не исходные данные. Аннотации разных нотаций не смешиваются.

## Фильтры и раскладки

Левая панель фильтрует типы узлов и ребер. Доступны:

- `Follow` - граф связей `follow` слева направо;
- `Timeline` - группы по дате создания слева направо;
- `Structure` - уровни связного графа сверху вниз.

Для циклических компонент применяется поиск strongly connected components; узлы цикла располагаются по окружности внутри общего уровня, поэтому цикл сохраняется и не накладывается в одну точку.

## Изображения

Можно указать HTTP(S)-URL или загрузить PNG, JPEG, WebP либо GIF размером до 700 КБ. Загруженный файл преобразуется в `data:image/...;base64` и сохраняется в OrientDB. Backend ограничивает поле одним мегабайтом и отклоняет другие схемы URL.

## Запуск frontend

```bash
npm ci --prefix frontend
npm run dev --prefix frontend
```

Vite проксирует `/api` и `/health` на `127.0.0.1:8090`, поэтому production-код не содержит жестко заданного API URL.

## 3D

Переключатель `2D/3D` находится в верхней панели. 3D-режим реализован на `react-force-graph-3d` и Three.js и загружается лениво только при первом открытии.

Возможности 3D:

- orbit-камера, zoom и автоматическое кадрирование;
- перемещение узлов и сохранение отдельных координат `position3d`;
- выбор узла или ребра с открытием общей правой панели;
- разные геометрии и цвета для процессов, условий, документов, актеров и хранилищ;
- постоянные подписи, направленные стрелки и частицы активных связей;
- общие фильтры типов узлов и ребер.

Двумерные и трехмерные координаты хранятся раздельно. Перемещение в 3D не меняет раскладку React Flow.
