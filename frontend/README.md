# ElectroMotiv Graph Frontend

React 19 интерфейс для Graph API проекта. Визуализация и редактирование реализованы на `@xyflow/react`.

## Запуск

Сначала запустить OrientDB и Graph API из корня проекта, затем:

```bash
npm ci --prefix frontend
npm run dev --prefix frontend
```

Открыть `http://127.0.0.1:5173`. Vite проксирует `/api` и `/health` на `http://127.0.0.1:8090`.

Для входа используются `GRAPH_API_USERNAME` и `GRAPH_API_PASSWORD` из локального `.env`. Без успешной Basic Auth данные OrientDB не загружаются.

## Возможности

- выбор запуска поиска или пользовательского графа;
- нотации Flow, UML Use Case, Component и Class;
- zoom, перемещение и выбор элементов;
- переключаемый Three.js 3D-режим с orbit-камерой и сохранением `position3d`;
- фильтры по типам узлов и ребер;
- раскладки Follow, Timeline и Structure;
- редактирование label, type, shape, created at, image и properties;
- сброс каждого поля и координат;
- постоянное сохранение изменений в `GraphAnnotation`;
- контроль конфликтов по revision;
- создание редактируемой копии, узлов и ребер.

## Проверки

```bash
npm run test --prefix frontend
npm run build --prefix frontend
```

Тесты проверяют направление Follow, группировку Timeline, дерево Structure и раскладку циклических компонент.
