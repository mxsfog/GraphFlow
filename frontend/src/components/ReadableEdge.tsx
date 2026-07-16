import { BaseEdge, EdgeLabelRenderer, Position, type EdgeProps } from '@xyflow/react';
import type { CSSProperties } from 'react';

export type EdgeRoutingData = {
  label?: string;
  parallelIndex?: number;
  parallelTotal?: number;
  showLabel?: boolean;
  sourceOrder?: number;
  targetOrder?: number;
};

type Point = { x: number; y: number };

export function ReadableEdge({
  data,
  markerEnd,
  selected,
  sourcePosition,
  sourceX,
  sourceY,
  style,
  targetPosition,
  targetX,
  targetY,
}: EdgeProps) {
  const routing = (data || {}) as EdgeRoutingData;
  const points = routePoints(
    { x: sourceX, y: sourceY },
    { x: targetX, y: targetY },
    sourcePosition,
    targetPosition,
    routing,
  );
  const labelPosition = longestSegmentCenter(points);
  const label = String(routing.label || '');
  const edgeStyle: CSSProperties = {
    ...style,
    stroke: selected ? '#f59e0b' : style?.stroke,
    strokeWidth: selected ? 3.2 : style?.strokeWidth,
  };

  return (
    <>
      <BaseEdge
        path={roundedPath(points)}
        markerEnd={markerEnd}
        style={edgeStyle}
        interactionWidth={18}
      />
      {label && (routing.showLabel || selected) ? (
        <EdgeLabelRenderer>
          <div
            className={`graph-edge-label${selected ? ' is-selected' : ''}`}
            style={{
              transform: `translate(-50%, -50%) translate(${labelPosition.x}px, ${labelPosition.y}px)`,
            }}
          >
            {label}
          </div>
        </EdgeLabelRenderer>
      ) : null}
    </>
  );
}

function routePoints(
  source: Point,
  target: Point,
  sourcePosition: Position,
  targetPosition: Position,
  routing: EdgeRoutingData,
): Point[] {
  const parallelTotal = Math.max(1, routing.parallelTotal || 1);
  const parallelLane = (routing.parallelIndex || 0) - (parallelTotal - 1) / 2;
  const sourceOrder = Math.max(0, routing.sourceOrder || 0);
  const targetOrder = Math.max(0, routing.targetOrder || 0);
  const horizontal = sourcePosition === Position.Left || sourcePosition === Position.Right;

  if (horizontal) {
    const sourceDirection = sourcePosition === Position.Right ? 1 : -1;
    const targetDirection = targetPosition === Position.Left ? -1 : 1;
    const sourceLead = {
      x: source.x + sourceDirection * (34 + sourceOrder * 9),
      y: source.y,
    };
    const targetLead = {
      x: target.x + targetDirection * (34 + targetOrder * 9),
      y: target.y,
    };
    if (Math.abs(source.y - target.y) < 1 && parallelTotal === 1) {
      return [source, target];
    }
    const middleX = (sourceLead.x + targetLead.x) / 2 + parallelLane * 22;
    return compactPoints([
      source,
      sourceLead,
      { x: middleX, y: source.y },
      { x: middleX, y: target.y },
      targetLead,
      target,
    ]);
  }

  const sourceDirection = sourcePosition === Position.Bottom ? 1 : -1;
  const targetDirection = targetPosition === Position.Top ? -1 : 1;
  const sourceLead = {
    x: source.x,
    y: source.y + sourceDirection * (34 + sourceOrder * 9),
  };
  const targetLead = {
    x: target.x,
    y: target.y + targetDirection * (34 + targetOrder * 9),
  };
  if (Math.abs(source.x - target.x) < 1 && parallelTotal === 1) {
    return [source, target];
  }
  const middleY = (sourceLead.y + targetLead.y) / 2 + parallelLane * 22;
  return compactPoints([
    source,
    sourceLead,
    { x: source.x, y: middleY },
    { x: target.x, y: middleY },
    targetLead,
    target,
  ]);
}

function compactPoints(points: Point[]): Point[] {
  const unique = points.filter(
    (point, index) =>
      index === 0
      || point.x !== points[index - 1].x
      || point.y !== points[index - 1].y,
  );
  return unique.filter((point, index) => {
    if (index === 0 || index === unique.length - 1) {
      return true;
    }
    const previous = unique[index - 1];
    const next = unique[index + 1];
    return !(
      (previous.x === point.x && point.x === next.x)
      || (previous.y === point.y && point.y === next.y)
    );
  });
}

function roundedPath(points: Point[]): string {
  if (points.length < 2) {
    return '';
  }
  if (points.length === 2) {
    return `M ${points[0].x} ${points[0].y} L ${points[1].x} ${points[1].y}`;
  }
  let path = `M ${points[0].x} ${points[0].y}`;
  for (let index = 1; index < points.length - 1; index += 1) {
    const previous = points[index - 1];
    const current = points[index];
    const next = points[index + 1];
    const radius = Math.min(9, distance(previous, current) / 2, distance(current, next) / 2);
    const before = pointToward(current, previous, radius);
    const after = pointToward(current, next, radius);
    path += ` L ${before.x} ${before.y} Q ${current.x} ${current.y} ${after.x} ${after.y}`;
  }
  const last = points.at(-1) as Point;
  return `${path} L ${last.x} ${last.y}`;
}

function longestSegmentCenter(points: Point[]): Point {
  let longest = { start: points[0], end: points.at(-1) as Point, length: 0 };
  for (let index = 1; index < points.length; index += 1) {
    const length = distance(points[index - 1], points[index]);
    if (length > longest.length) {
      longest = { start: points[index - 1], end: points[index], length };
    }
  }
  return {
    x: (longest.start.x + longest.end.x) / 2,
    y: (longest.start.y + longest.end.y) / 2,
  };
}

function pointToward(from: Point, to: Point, distanceValue: number): Point {
  const total = distance(from, to) || 1;
  return {
    x: from.x + ((to.x - from.x) / total) * distanceValue,
    y: from.y + ((to.y - from.y) / total) * distanceValue,
  };
}

function distance(left: Point, right: Point): number {
  return Math.hypot(right.x - left.x, right.y - left.y);
}
