# Graph Frontend

React Flow интерфейс для просмотра графа из OrientDB через backend API проекта.

## Запуск API

```bash
cd /mnt/d/ElectroMotiv
PYTHONPATH=src python3 -m electromotiv_pipeline graph-api --host 127.0.0.1 --port 8090
```

## Запуск frontend

```bash
cd /mnt/d/ElectroMotiv/frontend
npm install
npm run dev
```

Если API запущен не на `8090`:

```bash
VITE_GRAPH_API_URL=http://127.0.0.1:8091 npm run dev
```

Открыть:

```text
http://127.0.0.1:5173
```

## Нотации

- `flow` - workflow-диаграмма.
- `use_case` - UML Use Case, узлы отображаются эллипсами, связи подписываются `include`.
- `component` - компонентная диаграмма.
- `class` - диаграмма классов с секциями.

По умолчанию интерфейс показывает реальный запуск пайплайна из OrientDB. Список запусков берется из `/api/search-runs`, граф - из `/api/graph/run/{run_id}`.
