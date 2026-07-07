import React from 'react';
import { createRoot } from 'react-dom/client';
import { GraphViewer } from './components/GraphViewer';
import './styles.css';

const apiBaseUrl = import.meta.env.VITE_GRAPH_API_URL || 'http://127.0.0.1:8090';

createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <GraphViewer apiBaseUrl={apiBaseUrl} />
  </React.StrictMode>,
);
