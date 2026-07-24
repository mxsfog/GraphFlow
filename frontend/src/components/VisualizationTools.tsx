import { useState } from 'react';
import type { GraphViewRecord } from '../graphApiClient';
import type { AttributeFilters, AttributeOptions } from '../graphSemantics';

const FILTER_LABELS: Record<keyof AttributeFilters, string> = {
  status: 'Статус',
  region: 'Регион',
  organization: 'Организация',
  direction: 'Направление',
  year: 'Год',
};

export function VisualizationTools({
  attributeOptions,
  filters,
  onFilterChange,
  levels,
  hiddenLevels,
  onToggleLevel,
  views,
  onSaveView,
  onApplyView,
  onDeleteView,
  onExportSvg,
  onExportPresentation,
}: {
  attributeOptions: AttributeOptions;
  filters: AttributeFilters;
  onFilterChange: (field: keyof AttributeFilters, value: string) => void;
  levels: Array<{ level: number; count: number }>;
  hiddenLevels: number[];
  onToggleLevel: (level: number) => void;
  views: GraphViewRecord[];
  onSaveView: (name: string) => void;
  onApplyView: (view: GraphViewRecord) => void;
  onDeleteView: (viewId: string) => void;
  onExportSvg: () => void;
  onExportPresentation: () => void;
}) {
  const [viewName, setViewName] = useState('Рабочее представление');
  return (
    <>
      <section className="filter-section">
        <h3>Атрибуты</h3>
        {(Object.keys(FILTER_LABELS) as Array<keyof AttributeFilters>).map((field) => (
          <label className="filter-select" key={field}>
            <span>{FILTER_LABELS[field]}</span>
            <select
              value={filters[field]}
              disabled={attributeOptions[field].length === 0}
              onChange={(event) => onFilterChange(field, event.target.value)}
            >
              <option value="">Все</option>
              {attributeOptions[field].map((value) => (
                <option key={value} value={value}>{value}</option>
              ))}
            </select>
          </label>
        ))}
      </section>
      <section className="filter-section">
        <h3>Уровни</h3>
        <div className="level-filter-grid">
          {levels.map(({ level, count }) => (
            <label className="filter-option" key={level}>
              <input
                type="checkbox"
                checked={!hiddenLevels.includes(level)}
                onChange={() => onToggleLevel(level)}
              />
              Уровень {level} <small>{count}</small>
            </label>
          ))}
        </div>
      </section>
      <section className="filter-section workspace-section">
        <h3>Представления</h3>
        <input
          value={viewName}
          aria-label="Название представления"
          onChange={(event) => setViewName(event.target.value)}
        />
        <button type="button" onClick={() => onSaveView(viewName.trim() || 'Представление')}>
          Сохранить текущее
        </button>
        {views.length > 0 ? (
          <div className="workspace-list">
            {views.map((view) => (
              <div className="workspace-list-item" key={view.view_id}>
                <div className="template-heading">
                  <strong>{view.name}</strong>
                  <small>{view.state.view_mode.toUpperCase()} / {view.state.notation}</small>
                </div>
                <div className="workspace-item-actions">
                  <button type="button" onClick={() => onApplyView(view)}>Открыть</button>
                  <button type="button" onClick={() => onDeleteView(view.view_id)}>Удалить</button>
                </div>
              </div>
            ))}
          </div>
        ) : null}
      </section>
      <section className="filter-section">
        <h3>Экспорт</h3>
        <div className="layout-actions">
          <button type="button" onClick={onExportSvg}>Изображение SVG</button>
          <button type="button" onClick={onExportPresentation}>Презентация HTML</button>
        </div>
      </section>
    </>
  );
}
