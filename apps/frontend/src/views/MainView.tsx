import { useEffect, useState } from 'react';

import { apiGet, openAppView, openDesktopMode, quitApp } from '../lib/bridge';

type StatusRecord = {
  status?: string;
  label?: string;
  description?: string;
  blockers?: string[];
};

type ChatMessage = {
  role?: string;
  content?: string;
  status?: string;
  created_at?: string;
};

type ChatSession = {
  session_id?: string;
  title?: string;
  message_count?: number;
  is_current?: boolean;
};

type DashboardData = {
  app?: { uptime_seconds?: number; version?: string; running?: boolean };
  hermes?: {
    status?: string;
    version?: string;
    platform?: string;
    ready?: boolean;
    readiness_level?: string;
    limited_tools?: string[];
    doctor_issues_count?: number;
  };
  workspace?: { path?: string; initialized?: boolean; created_at?: string };
  bridge?: { state?: string; status?: string; running?: string; url?: string; config_dirty?: boolean; drift_details?: string[] };
  integrations?: { astrbot?: StatusRecord; hapi?: StatusRecord };
  modes?: { current?: string; items?: Array<{ id: string; name?: string; label?: string; description?: string }> };
  tasks?: { pending?: number; running?: number; completed?: number };
  chat?: {
    status_label?: string;
    is_processing?: boolean;
    empty?: boolean;
    messages?: ChatMessage[];
    recent_sessions?: ChatSession[];
    executor?: string;
    session_id?: string;
  };
};

export function MainView() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let disposed = false;
    async function refresh() {
      try {
        const payload = await apiGet<DashboardData>('/ui/dashboard');
        if (!disposed) {
          setData(payload);
          setError('');
        }
      } catch (err) {
        if (!disposed) setError(err instanceof Error ? err.message : '读取主控台失败');
      }
    }
    refresh();
    const timer = window.setInterval(refresh, 3000);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, []);

  return (
    <main className="app-shell dashboard-shell">
      <header className="topbar">
        <div>
          <h1>Hermes-Yachiyo</h1>
          <p>桌面优先本地个人 Agent</p>
        </div>
        <div className="topbar-actions">
          <button type="button" onClick={() => void openAppView('chat')}>打开对话</button>
          <button className="ghost-button" type="button" onClick={quitApp}>退出</button>
        </div>
      </header>

      {error ? <div className="notice danger">{error}</div> : null}

      <section className="metric-grid dashboard-metrics">
        <Metric title="Hermes Agent" value={data?.hermes?.status || '读取中'} detail={hermesDetail(data)} />
        <Metric title="Workspace" value={data?.workspace?.initialized ? '已初始化' : '未初始化'} detail={data?.workspace?.path || '—'} />
        <Metric title="Runtime" value={formatUptime(data?.app?.uptime_seconds)} detail={data?.app?.version || '—'} />
        <Metric title="Bridge" value={bridgeState(data)} detail={data?.bridge?.url || '—'} />
        <Metric title="Tasks" value={`${data?.tasks?.running ?? 0} 运行中`} detail={`${data?.tasks?.pending ?? 0} 等待 / ${data?.tasks?.completed ?? 0} 完成`} />
        <Metric title="Integrations" value={data?.integrations?.astrbot?.label || data?.integrations?.astrbot?.status || '—'} detail={data?.integrations?.hapi?.label || data?.integrations?.hapi?.status || '—'} />
      </section>

      <section className="dashboard-layout">
        <article className="panel dashboard-card">
          <div className="section-heading-row">
            <h2>Hermes Agent</h2>
            <StatusPill active={Boolean(data?.hermes?.ready)} label={data?.hermes?.ready ? '能力就绪' : '待检查'} />
          </div>
          <InfoList rows={[
            ['安装状态', data?.hermes?.status],
            ['就绪等级', data?.hermes?.readiness_level],
            ['版本', data?.hermes?.version],
            ['平台', data?.hermes?.platform],
            ['受限工具', listOrDash(data?.hermes?.limited_tools)],
            ['诊断提示', data?.hermes?.doctor_issues_count ? `${data.hermes.doctor_issues_count} 项` : '无'],
          ]} />
        </article>

        <article className="panel dashboard-card">
          <div className="section-heading-row">
            <h2>Yachiyo 工作空间</h2>
            <StatusPill active={Boolean(data?.workspace?.initialized)} label={data?.workspace?.initialized ? '已初始化' : '未初始化'} />
          </div>
          <InfoList rows={[
            ['路径', data?.workspace?.path],
            ['创建时间', formatDateTime(data?.workspace?.created_at)],
          ]} />
        </article>

        <article className="panel dashboard-card">
          <div className="section-heading-row">
            <h2>运行信息</h2>
            <StatusPill active={Boolean(data?.app?.running)} label={data?.app?.running ? '运行中' : '未运行'} />
          </div>
          <InfoList rows={[
            ['运行时间', formatUptime(data?.app?.uptime_seconds)],
            ['版本', data?.app?.version],
            ['Bridge', bridgeState(data)],
            ['Bridge 地址', data?.bridge?.url],
            ['配置漂移', data?.bridge?.config_dirty ? listOrDash(data?.bridge?.drift_details) : '无'],
          ]} />
        </article>

        <article className="panel dashboard-card">
          <div className="section-heading-row">
            <h2>任务统计</h2>
          </div>
          <InfoList rows={[
            ['等待中', String(data?.tasks?.pending ?? 0)],
            ['运行中', String(data?.tasks?.running ?? 0)],
            ['已完成', String(data?.tasks?.completed ?? 0)],
          ]} />
        </article>

        <article className="panel dashboard-card wide">
          <div className="section-heading-row">
            <h2>集成服务</h2>
          </div>
          <IntegrationBlock title="AstrBot / QQ" item={data?.integrations?.astrbot} />
          <IntegrationBlock title="Hapi / Codex" item={data?.integrations?.hapi} />
        </article>
      </section>

      <section className="panel action-panel">
        <h2>主控台</h2>
        <div className="action-row control-action-row">
          <button type="button" onClick={() => openDesktopMode(data?.modes?.current)}>打开表现态</button>
          <button type="button" onClick={() => void openAppView('chat')}>打开 Chat Window</button>
          <button type="button" onClick={() => void openAppView('settings')}>应用设置</button>
          <button type="button" onClick={() => void openAppView('settings', { mode: 'bubble' })}>Bubble 设置</button>
          <button type="button" onClick={() => void openAppView('settings', { mode: 'live2d' })}>Live2D 设置</button>
        </div>
      </section>

      <section className="dashboard-bottom-grid">
        <article className="panel chat-overview-panel">
          <div className="section-heading-row">
            <h2>会话中心</h2>
            <span>{data?.chat?.status_label || '读取中'}</span>
          </div>
          <RecentMessages messages={data?.chat?.messages || []} empty={Boolean(data?.chat?.empty)} />
          <RecentSessions sessions={data?.chat?.recent_sessions || []} />
          <button type="button" className="wide-action" onClick={() => void openAppView('chat')}>打开完整对话窗口</button>
        </article>

        <article className="panel mode-overview-panel">
          <div className="section-heading-row">
            <h2>模式设置</h2>
            <span>当前：{modeName(data)}</span>
          </div>
          <div className="mode-summary-list">
            {(data?.modes?.items || []).map((mode) => (
              <button type="button" key={mode.id} onClick={() => void openAppView('settings', { mode: mode.id })}>
                <strong>{mode.name || mode.label || mode.id}</strong>
                <span>{mode.description || (mode.id === data?.modes?.current ? '当前模式' : '可切换表现态')}</span>
              </button>
            ))}
          </div>
        </article>
      </section>
    </main>
  );
}

function bridgeState(data: DashboardData | null) {
  return data?.bridge?.state || data?.bridge?.status || data?.bridge?.running || '—';
}

function hermesDetail(data: DashboardData | null): string {
  const version = data?.hermes?.version || '—';
  const readiness = data?.hermes?.readiness_level || (data?.hermes?.ready ? 'ready' : 'unknown');
  return `${version} / ${readiness}`;
}

function modeName(data: DashboardData | null): string {
  const current = data?.modes?.current || '';
  const item = data?.modes?.items?.find((entry) => entry.id === current);
  return item?.name || item?.label || current || '—';
}

function Metric({ title, value, detail }: { title: string; value: string; detail: string }) {
  return (
    <article className="panel metric-card">
      <span>{title}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </article>
  );
}

function StatusPill({ active, label }: { active: boolean; label: string }) {
  return <span className={active ? 'status-pill ok' : 'status-pill warn'}>{label}</span>;
}

function InfoList({ rows }: { rows: Array<[string, string | number | undefined | null]> }) {
  return (
    <div className="settings-meta-list compact-list">
      {rows.map(([label, value]) => (
        <div className="settings-meta-row" key={label}>
          <span>{label}</span>
          <strong>{value === undefined || value === null || value === '' ? '—' : value}</strong>
        </div>
      ))}
    </div>
  );
}

function IntegrationBlock({ title, item }: { title: string; item?: StatusRecord }) {
  return (
    <div className="integration-block">
      <div className="integration-title-row">
        <strong>{title}</strong>
        <span>{item?.label || item?.status || '—'}</span>
      </div>
      {item?.description ? <p>{item.description}</p> : null}
      {item?.blockers?.length ? <p className="warn-text">{item.blockers.join('；')}</p> : null}
    </div>
  );
}

function RecentMessages({ messages, empty }: { messages: ChatMessage[]; empty: boolean }) {
  if (empty || messages.length === 0) return <div className="empty-state inline-empty">暂无消息。打开聊天窗口开始完整对话。</div>;
  return (
    <div className="recent-message-list">
      {messages.map((message, index) => (
        <div className="recent-message" key={`${message.created_at || index}-${message.role || 'message'}`}>
          <span>{roleLabel(message.role)} · {message.status || '—'}</span>
          <p>{message.content || '—'}</p>
        </div>
      ))}
    </div>
  );
}

function RecentSessions({ sessions }: { sessions: ChatSession[] }) {
  if (!sessions.length) return null;
  return (
    <div className="recent-session-list">
      {sessions.map((session) => (
        <div className={session.is_current ? 'recent-session current' : 'recent-session'} key={session.session_id || session.title}>
          <span>{session.title || '新对话'}</span>
          <small>{session.message_count ?? 0} 条消息</small>
        </div>
      ))}
    </div>
  );
}

function roleLabel(role?: string) {
  if (role === 'assistant') return 'Yachiyo';
  if (role === 'user') return '用户';
  return role || '系统';
}

function listOrDash(items?: string[]): string {
  return items?.length ? items.join('、') : '—';
}

function formatDateTime(value?: string) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function formatUptime(seconds?: number) {
  if (typeof seconds !== 'number') return '读取中';
  if (seconds < 60) return `${Math.floor(seconds)} 秒`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟`;
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return `${hours} 小时 ${minutes} 分钟`;
}