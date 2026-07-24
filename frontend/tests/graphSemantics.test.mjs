import assert from 'node:assert/strict';
import test from 'node:test';
import {
  attributeOptions,
  canonicalNodeLabel,
  hiddenBranchNodeIds,
  hierarchyLevels,
  matchesAttributeFilters,
  nodeMetadata,
  readinessPresentation,
} from '../../.runtime/frontend-tests/src/graphSemantics.js';

function node(id, properties = [], raw = {}, nodeType = 'task', createdAt = '', endedAt = '') {
  return { id, label: id, nodeType, createdAt, endedAt, properties, raw };
}

test('метаданны читаются из properties и raw с русскими алиасами', () => {
  const metadata = nodeMetadata(node(
    'task-1',
    [
      { key: 'Статус', value: 'В работе' },
      { key: 'План', value: '10' },
      { key: 'Факт', value: '7' },
    ],
    { region: 'Москва', description: 'Описание' },
    'task',
    '2026-07-20T10:00:00Z',
  ));

  assert.equal(metadata.status, 'В работе');
  assert.equal(metadata.region, 'Москва');
  assert.equal(metadata.year, '2026');
  assert.equal(metadata.planned, '10');
  assert.equal(metadata.actual, '7');
  assert.equal(metadata.createdAt, '2026-07-20T10:00:00Z');
  assert.equal(metadata.endedAt, '');
});

test('фильтр по году учитывает весь период актуальности', () => {
  const ranged = node(
    'period',
    [],
    {},
    'task',
    '2024-01-01T00:00:00Z',
    '2026-12-31T23:59:59Z',
  );

  assert.deepEqual(attributeOptions([ranged]).year, ['2024', '2025', '2026']);
  assert.equal(matchesAttributeFilters(ranged, {
    status: '', region: '', organization: '', direction: '', year: '2025',
  }), true);
  assert.equal(matchesAttributeFilters(ranged, {
    status: '', region: '', organization: '', direction: '', year: '2027',
  }), false);
});

test('атрибутные фильтры и опции используют единую нормализацию', () => {
  const nodes = [
    node('a', [{ key: 'status', value: 'done' }, { key: 'region', value: '77' }]),
    node('b', [{ key: 'status', value: 'active' }, { key: 'region', value: '77' }]),
  ];

  assert.deepEqual(attributeOptions(nodes).status, ['active', 'done']);
  assert.equal(matchesAttributeFilters(nodes[0], {
    status: 'done', region: '77', organization: '', direction: '', year: '',
  }), true);
  assert.equal(matchesAttributeFilters(nodes[1], {
    status: 'done', region: '', organization: '', direction: '', year: '',
  }), false);
});

test('фильтр направления учитывает узлы нескольких карт', () => {
  const shared = node('shared', [{ key: 'direction', value: 'Роботы; Микросхемы' }]);

  assert.deepEqual(attributeOptions([shared]).direction, ['Микросхемы', 'Роботы']);
  assert.equal(matchesAttributeFilters(shared, {
    status: '', region: '', organization: '', direction: 'Микросхемы', year: '',
  }), true);
});

test('статус готовности преобразуется в фиксированную цветовую категорию', () => {
  assert.equal(readinessPresentation('Зелёный')?.level, 'green');
  assert.equal(readinessPresentation('Оранжевый: нужна адаптация')?.level, 'orange');
  assert.equal(readinessPresentation('Красный')?.level, 'red');
  assert.equal(readinessPresentation('В работе'), null);
});

test('уровни и сворачивание ветви обрабатывают циклы', () => {
  const nodes = [node('root'), node('a'), node('b'), node('other')];
  const edges = [
    { source: 'root', target: 'a', type: 'include' },
    { source: 'a', target: 'b', type: 'include' },
    { source: 'b', target: 'a', type: 'include' },
  ];
  const levels = hierarchyLevels(nodes, edges);

  assert.equal(levels.get('root'), 0);
  assert.equal(levels.get('a'), 1);
  assert.equal(levels.get('b'), 1);
  assert.deepEqual([...hiddenBranchNodeIds(new Set(['root']), edges)].sort(), ['a', 'b']);
});

test('каноническая подпись не зависит от регистра и пробелов', () => {
  assert.equal(canonicalNodeLabel('  Цель   проекта '), 'цель проекта');
});
