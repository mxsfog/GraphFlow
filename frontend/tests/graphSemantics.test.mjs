import assert from 'node:assert/strict';
import test from 'node:test';
import {
  attributeOptions,
  canonicalNodeLabel,
  hiddenBranchNodeIds,
  hierarchyLevels,
  matchesAttributeFilters,
  nodeMetadata,
} from '../../.runtime/frontend-tests/src/graphSemantics.js';

function node(id, properties = [], raw = {}, nodeType = 'task', createdAt = '') {
  return { id, label: id, nodeType, createdAt, properties, raw };
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
});

test('атрибутные фильтры и опции используют единую нормализацию', () => {
  const nodes = [
    node('a', [{ key: 'status', value: 'done' }, { key: 'region', value: '77' }]),
    node('b', [{ key: 'status', value: 'active' }, { key: 'region', value: '77' }]),
  ];

  assert.deepEqual(attributeOptions(nodes).status, ['active', 'done']);
  assert.equal(matchesAttributeFilters(nodes[0], {
    status: 'done', region: '77', organization: '', year: '',
  }), true);
  assert.equal(matchesAttributeFilters(nodes[1], {
    status: 'done', region: '', organization: '', year: '',
  }), false);
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
