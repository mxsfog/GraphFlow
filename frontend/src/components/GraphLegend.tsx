export type LegendEntry = {
  type: string;
  color: string;
  dashed?: boolean;
};

export function GraphLegend({
  nodeEntries,
  edgeEntries,
  hasSharedNodes,
}: {
  nodeEntries: LegendEntry[];
  edgeEntries: LegendEntry[];
  hasSharedNodes: boolean;
}) {
  return (
    <details className="graph-legend" open>
      <summary>Легенда</summary>
      <div className="legend-columns">
        <section>
          <strong>Узлы</strong>
          {nodeEntries.map((entry) => (
            <span key={entry.type}>
              <i className="legend-node-swatch" style={{ background: entry.color }} />
              {entry.type}
            </span>
          ))}
          {hasSharedNodes ? (
            <span><i className="legend-shared-swatch" />Несколько карт</span>
          ) : null}
        </section>
        <section>
          <strong>Связи</strong>
          {edgeEntries.map((entry) => (
            <span key={entry.type}>
              <i
                className={`legend-edge-swatch${entry.dashed ? ' is-dashed' : ''}`}
                style={{ borderColor: entry.color }}
              />
              {entry.type}
            </span>
          ))}
        </section>
      </div>
    </details>
  );
}
