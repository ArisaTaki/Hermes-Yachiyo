import { useState } from 'react';

import { apiGet } from '../lib/bridge';

export function InstallerView() {
  const [message, setMessage] = useState('等待操作');

  async function recheck() {
    try {
      const result = await apiGet<Record<string, unknown>>('/hermes/install-info');
      setMessage(JSON.stringify(result));
    } catch (err) {
      setMessage(err instanceof Error ? err.message : '检测失败');
    }
  }

  return (
    <main className="app-shell installer-shell">
      <header className="topbar">
        <div>
          <h1>Hermes-Yachiyo 安装引导</h1>
          <p>专业前端入口已就绪，安装流程会逐步迁移到这里。</p>
        </div>
      </header>
      <section className="panel">
        <h2>运行时检测</h2>
        <p>{message}</p>
        <button type="button" onClick={recheck}>重新检测</button>
      </section>
    </main>
  );
}
