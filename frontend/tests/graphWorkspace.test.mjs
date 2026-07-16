import assert from 'node:assert/strict';
import test from 'node:test';
import {
  descendantNodeIds,
  groupNodeId,
  projectWorkspace,
} from '../../.runtime/frontend-tests/src/graphWorkspace.js';

function node(id, x, y) {
  return { id, position: { x, y }, width: 100, height: 60 };
}

function edge(id, source, target, type = 'follow') {
  return { id, source, target, type, label: type };
}

function group(groupId, nodeIds, childGroupIds = [], collapsed = false) {
  return {
    graph_id: 'graph:test',
    notation: 'flow',
    group_id: groupId,
    title: groupId,
    node_ids: nodeIds,
    child_group_ids: childGroupIds,
    collapsed,
    revision: 1,
    created_at: '',
    updated_at: '',
  };
}

test('свернутая группа заменяет узлы и агрегирует внешние связи', () => {
  const projection = projectWorkspace(
    [node('a', 0, 0), node('b', 0, 100), node('target', 400, 40)],
    [edge('a-target', 'a', 'target'), edge('b-target', 'b', 'target')],
    [group('items', ['a', 'b'], [], true)],
  );

  assert.deepEqual([...projection.hiddenNodeIds].sort(), ['a', 'b']);
  assert.equal(projection.groups[0].id, groupNodeId('items'));
  assert.equal(projection.edges.length, 1);
  assert.equal(projection.edges[0].source, groupNodeId('items'));
  assert.equal(projection.edges[0].count, 2);
});

test('свернутая родительская группа скрывает вложенную проекцию', () => {
  const projection = projectWorkspace(
    [node('a', 0, 0), node('b', 200, 0)],
    [],
    [
      group('child', ['b'], [], true),
      group('parent', ['a'], ['child'], true),
    ],
  );

  assert.deepEqual(projection.groups.map((item) => item.groupId), ['parent']);
  assert.deepEqual([...projection.hiddenNodeIds].sort(), ['a', 'b']);
});

test('развернутая группа не скрывает исходные узлы', () => {
  const projection = projectWorkspace(
    [node('a', 0, 0), node('b', 200, 0)],
    [edge('a-b', 'a', 'b')],
    [group('items', ['a', 'b'])],
  );

  assert.equal(projection.hiddenNodeIds.size, 0);
  assert.equal(projection.groups[0].collapsed, false);
  assert.equal(projection.edges[0].id, 'a-b');
});

test('обход дочернего графа завершается при цикле и исключает корень', () => {
  const descendants = descendantNodeIds(
    'a',
    [edge('a-b', 'a', 'b', 'contains'), edge('b-a', 'b', 'a', 'contains')],
    new Set(['contains']),
  );

  assert.deepEqual(descendants, ['b']);
});
