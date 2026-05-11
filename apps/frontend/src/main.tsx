import React from 'react';
import ReactDOM from 'react-dom/client';

import { App } from './App';
import './styles/app.css';

if (window.hermesDesktop) {
  document.body.classList.add('electron-window');
}

// 提前判断桌面表现态，避免首帧黑底闪现
const hash = window.location.hash || '';
const searchParams = new URLSearchParams(window.location.search);
const surface = searchParams.get('surface') || '';
if (surface === 'desktop' && (hash.includes('#/bubble') || hash.includes('#/live2d') || hash.includes('#/bubble-menu'))) {
  document.documentElement.classList.add('desktop-mode-root');
  document.body.classList.add('desktop-mode-body');
  document.documentElement.style.background = 'transparent';
  document.body.style.background = 'transparent';
}

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
