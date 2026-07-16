import assert from 'node:assert/strict';
import test from 'node:test';
import {
  arrangeGraphNodes,
  stronglyConnectedComponents,
} from '../../.runtime/frontend-tests/src/graphLayout.js';

function node(id, createdAt = '', nodeType = 'task') {
  return { id, createdAt, nodeType, position: { x: 0, y: 0 } };
}

test('follow-цепочка располагается слева направо', () => {
  const positions = arrangeGraphNodes(
    [node('a'), node('b'), node('c')],
    [
      { source: 'a', target: 'b', type: 'follow' },
      { source: 'b', target: 'c', type: 'follow' },
    ],
    'follow',
  );

  assert.ok(positions.get('a').x < positions.get('b').x);
  assert.ok(positions.get('b').x < positions.get('c').x);
});

test('циклические узлы не накладываются друг на друга', () => {
  const edges = [
    { source: 'a', target: 'b', type: 'follow' },
    { source: 'b', target: 'a', type: 'follow' },
  ];
  const positions = arrangeGraphNodes([node('a'), node('b')], edges, 'follow');

  assert.deepEqual(stronglyConnectedComponents(['a', 'b'], edges), [['b', 'a']]);
  assert.notDeepEqual(positions.get('a'), positions.get('b'));
});

test('timeline группирует одинаковые даты и сортирует разные даты', () => {
  const positions = arrangeGraphNodes(
    [
      node('second', '2026-07-11T10:00:00Z'),
      node('first', '2026-07-10T08:00:00Z'),
      node('first-later', '2026-07-10T12:00:00Z'),
    ],
    [],
    'timeline',
  );

  assert.equal(positions.get('first').x, positions.get('first-later').x);
  assert.ok(positions.get('first').x < positions.get('second').x);
  assert.notEqual(positions.get('first').y, positions.get('first-later').y);
});

test('structure располагает связанные уровни сверху вниз', () => {
  const positions = arrangeGraphNodes(
    [node('root', '', 'section'), node('child', '', 'task')],
    [{ source: 'root', target: 'child', type: 'contains' }],
    'structure',
  );

  assert.ok(positions.get('root').y < positions.get('child').y);
});

test('overview учитывает связи всех типов и формирует уровни', () => {
  const positions = arrangeGraphNodes(
    [node('actor'), node('run'), node('rss'), node('news'), node('source')],
    [
      { source: 'actor', target: 'run', type: 'request' },
      { source: 'run', target: 'rss', type: 'request' },
      { source: 'rss', target: 'news', type: 'found' },
      { source: 'news', target: 'source', type: 'from_source' },
    ],
    'overview',
  );

  assert.ok(positions.get('actor').x < positions.get('run').x);
  assert.ok(positions.get('run').x < positions.get('rss').x);
  assert.ok(positions.get('rss').x < positions.get('news').x);
  assert.ok(positions.get('news').x < positions.get('source').x);
});

test('узлы одного уровня получают разные вертикальные позиции', () => {
  const positions = arrangeGraphNodes(
    [node('root'), node('left'), node('center'), node('right')],
    [
      { source: 'root', target: 'left', type: 'contains' },
      { source: 'root', target: 'center', type: 'contains' },
      { source: 'root', target: 'right', type: 'contains' },
    ],
    'overview',
  );

  assert.equal(new Set(['left', 'center', 'right'].map((id) => positions.get(id).y)).size, 3);
});
