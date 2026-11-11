import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import { WorkbenchProvider } from './state';
import './style.css';

// One stable entry route. Any other path (including "/") redirects to /workbench, keeping the query.
if (location.pathname !== '/workbench') history.replaceState(null, '', `/workbench${location.search}`);

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <WorkbenchProvider>
      <App />
    </WorkbenchProvider>
  </StrictMode>,
);
