import React from 'react';
import ReactDOM from 'react-dom/client';

import { App } from './App';
import './styles/app.css';

if (window.hermesDesktop) {
  document.body.classList.add('electron-window');
}

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
