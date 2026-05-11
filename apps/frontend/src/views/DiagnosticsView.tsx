import { useEffect, useMemo, useRef, useState } from 'react';

import { apiGet, apiPost, copyText, openAppView } from '../lib/bridge';
import { currentParam } from '../lib/view';

type DiagnosticAction = {
  id: string;
  label: string;
  command: string;
  description: string;
};

type DiagnosticResult = {
  ok?: boolean;
  success?: boolean;
  error?: string;
  message?: string;
  action_id?: string;
  label?: string;
  description?: string;
  command?: string;
  returncode?: number;
  stdout?: string;
  stderr?: string;
  output?: string;
  elapsed_seconds?: number;
  cached_at?: string;
  stale?: boolean;
  diagnostic_cache?: DiagnosticCache;
  doctor_summary?: {
    readiness_level?: string;
    limited_tools?: string[];
    doctor_issues_count?: number;
  };
};

type DiagnosticCache = {
  stale?: boolean;
  reason?: string;
  updated_at?: string;
  commands?: Record<string, DiagnosticResult>;
};

type DashboardStatus = {
  bridge?: { state?: string; status?: string; running?: string; url?: string };
  hermes?: {
    ready?: boolean;
    command_exists?: boolean;
    readiness_level?: string;
    platform?: string;
    doctor_issues_count?: number;
  };
  workspace?: { initialized?: boolean; path?: string };
};

type RuntimeStatus = {
  service?: string;
  version?: string;
  uptime_seconds?: number;
  task_counts?: Record<string, number>;
  hermes_ready?: boolean;
};

type TaskInfo = {
  task_id: string;
  description: string;
  task_type: string;
  status: string;
  risk_level: string;
  created_at: string;
  updated_at: string;
  result?: string | null;
  error?: string | null;
  chat_session_id?: string | null;
};

type TaskListResponse = {
  tasks?: TaskInfo[];
  total?: number;
};

type TaskResponse = {
  task?: TaskInfo;
};

type AssistantIntentResult = {
  ok?: boolean;
  action?: string;
  task_id?: string | null;
  message?: string;
};

type ScreenshotProbe = {
  image_base64?: string;
  format?: string;
  width?: number;
  height?: number;
  captured_at?: string;
};

type ActiveWindowProbe = {
  title?: string;
  app_name?: string;
  pid?: number | null;
  queried_at?: string;
};

type DiagnosticOverviewItem = {
  label: string;
  detail: string;
  status: 'passed' | 'warning' | 'error';
};

const DIAGNOSTIC_ACTIONS: DiagnosticAction[] = [
  {
    id: 'config-check',
    label: '检查配置结构',
    command: 'hermes config check',
    description: '检查缺失或过期配置，不会发起模型请求。',
  },
  {
    id: 'doctor',
    label: '运行 Doctor',
    command: 'hermes doctor',
    description: '检查 Hermes 依赖、配置和运行环境。',
  },
  {
    id: 'auth-list',
    label: '查看凭据池',
    command: 'hermes auth list',
    description: '查看 Hermes 记录的 provider 凭据状态；输出会脱敏。',
  },
];

export function DiagnosticsView() {
  const initialCommand = normalizeDiagnosticCommand(currentParam('command'));
  const returnTarget = normalizeReturnTarget(currentParam('return_to'));
  const returnLabel = returnTarget === 'tools' ? '回到工具中心' : '返回主控台';
  const [selectedCommand, setSelectedCommand] = useState(initialCommand || DIAGNOSTIC_ACTIONS[0].command);
  const [result, setResult] = useState<DiagnosticResult | null>(null);
  const [diagnosticCache, setDiagnosticCache] = useState<DiagnosticCache | null>(null);
  const [overview, setOverview] = useState<DashboardStatus | null>(null);
  const [runtimeStatus, setRuntimeStatus] = useState<RuntimeStatus | null>(null);
  const [tasks, setTasks] = useState<TaskInfo[]>([]);
  const [taskDraft, setTaskDraft] = useState({ description: '', task_type: 'general', risk_level: 'low' });
  const [intentText, setIntentText] = useState('');
  const [intentResult, setIntentResult] = useState<AssistantIntentResult | null>(null);
  const [screenProbe, setScreenProbe] = useState<ScreenshotProbe | null>(null);
  const [activeWindowProbe, setActiveWindowProbe] = useState<ActiveWindowProbe | null>(null);
  const [runtimeBusy, setRuntimeBusy] = useState('');
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState('');
  const lastAutoRunRef = useRef('');

  const selectedAction = useMemo(
    () => DIAGNOSTIC_ACTIONS.find((action) => action.command === selectedCommand) || DIAGNOSTIC_ACTIONS[0],
    [selectedCommand],
  );

  useEffect(() => {
    if (!initialCommand || lastAutoRunRef.current === initialCommand) return;
    lastAutoRunRef.current = initialCommand;
    void runDiagnostic(initialCommand);
  }, [initialCommand]);

  useEffect(() => {
    if (initialCommand) return;
    void loadDiagnosticCache(selectedAction.id);
  }, [initialCommand, selectedAction.id]);

  useEffect(() => {
    let disposed = false;
    apiGet<DashboardStatus>('/ui/dashboard')
      .then((payload) => {
        if (!disposed) setOverview(payload);
      })
      .catch(() => {
        if (!disposed) setOverview(null);
      });
    return () => {
      disposed = true;
    };
  }, []);

  useEffect(() => {
    let disposed = false;
    void loadRuntimeSnapshot(() => disposed);
    return () => {
      disposed = true;
    };
  }, []);

  async function loadDiagnosticCache(actionId: string) {
    try {
      const cache = await apiGet<DiagnosticCache>('/ui/hermes/diagnostics/cache');
      setDiagnosticCache(cache);
      const cachedResult = cache.commands?.[actionId];
      if (cachedResult) {
        setResult(cachedResult);
        setStatus(diagnosticCacheStatus(cache, cachedResult));
      }
    } catch {
      setDiagnosticCache(null);
    }
  }

  async function runDiagnostic(command: string = selectedCommand) {
    const normalized = normalizeDiagnosticCommand(command) || DIAGNOSTIC_ACTIONS[0].command;
    const action = DIAGNOSTIC_ACTIONS.find((item) => item.command === normalized) || DIAGNOSTIC_ACTIONS[0];
    setSelectedCommand(action.command);
    setBusy(true);
    setStatus(`正在执行：${action.command}`);
    try {
      const payload = await apiPost<DiagnosticResult>('/ui/hermes/diagnostic-command', { command: action.command });
      setResult(payload);
      if (payload.diagnostic_cache) setDiagnosticCache(payload.diagnostic_cache);
      setStatus(payload.success ? payload.message || `${action.label} 完成` : payload.error || `${action.label} 失败`);
    } catch (err) {
      setResult(null);
      setStatus(err instanceof Error ? err.message : `${action.label} 失败`);
    } finally {
      setBusy(false);
    }
  }

  async function copyOutput() {
    if (!result) return;
    const text = result.output || [result.stdout, result.stderr].filter(Boolean).join('\n') || '';
    if (!text) return;
    await copyText(text);
    setStatus('诊断输出已复制');
  }

  async function loadRuntimeSnapshot(isDisposed: () => boolean = () => false) {
    setRuntimeBusy((current) => current || 'refresh');
    try {
      const [runtimeResult, tasksResult] = await Promise.allSettled([
        apiGet<RuntimeStatus>('/status'),
        apiGet<TaskListResponse>('/tasks'),
      ]);
      if (isDisposed()) return;
      if (runtimeResult.status === 'fulfilled') setRuntimeStatus(runtimeResult.value);
      if (tasksResult.status === 'fulfilled') setTasks(tasksResult.value.tasks || []);
    } finally {
      if (!isDisposed()) setRuntimeBusy((current) => (current === 'refresh' ? '' : current));
    }
  }

  async function createTask() {
    if (!taskDraft.description.trim() || runtimeBusy) return;
    setRuntimeBusy('create-task');
    setStatus('正在创建低风险任务...');
    try {
      const result = await apiPost<TaskResponse>('/tasks', {
        description: taskDraft.description.trim(),
        task_type: taskDraft.task_type,
        risk_level: taskDraft.risk_level,
      });
      if (result.task) setTasks((current) => [result.task as TaskInfo, ...current.filter((task) => task.task_id !== result.task?.task_id)]);
      setTaskDraft((current) => ({ ...current, description: '' }));
      setStatus('任务已创建');
      void loadRuntimeSnapshot();
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '创建任务失败');
    } finally {
      setRuntimeBusy('');
    }
  }

  async function cancelTask(taskId: string) {
    if (runtimeBusy) return;
    setRuntimeBusy(`cancel-${taskId}`);
    setStatus('正在取消任务...');
    try {
      const result = await apiPost<TaskResponse>(`/tasks/${encodeURIComponent(taskId)}/cancel`);
      if (result.task) setTasks((current) => current.map((task) => task.task_id === taskId ? result.task as TaskInfo : task));
      setStatus('任务已取消');
      void loadRuntimeSnapshot();
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '取消任务失败');
    } finally {
      setRuntimeBusy('');
    }
  }

  async function runAssistantIntent(dryRun: boolean) {
    const text = intentText.trim();
    if (!text || runtimeBusy) return;
    setRuntimeBusy(dryRun ? 'intent-dry-run' : 'intent-create');
    setIntentResult(null);
    setStatus(dryRun ? '正在分析助手意图...' : '正在通过助手意图创建低风险任务...');
    try {
      const result = await apiPost<AssistantIntentResult>('/assistant/intent', {
        text,
        source: 'desktop-diagnostics',
        sender_id: 'desktop',
        dry_run: dryRun,
      });
      setIntentResult(result);
      setStatus(result.ok ? result.message || '助手意图已完成' : result.message || '助手意图未执行');
      if (!dryRun) void loadRuntimeSnapshot();
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '助手意图测试失败');
    } finally {
      setRuntimeBusy('');
    }
  }

  async function probeScreen() {
    if (runtimeBusy) return;
    setRuntimeBusy('screen');
    setStatus('正在获取当前屏幕摘要...');
    try {
      const result = await apiGet<ScreenshotProbe>('/screen/current');
      setScreenProbe(result);
      setStatus(`已获取屏幕截图摘要：${result.width || '—'}×${result.height || '—'}`);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '截图探测失败');
    } finally {
      setRuntimeBusy('');
    }
  }

  async function probeActiveWindow() {
    if (runtimeBusy) return;
    setRuntimeBusy('active-window');
    setStatus('正在读取活动窗口...');
    try {
      const result = await apiGet<ActiveWindowProbe>('/system/active-window');
      setActiveWindowProbe(result);
      setStatus(`当前活动窗口：${result.app_name || '—'} — ${result.title || '无标题'}`);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '活动窗口探测失败');
    } finally {
      setRuntimeBusy('');
    }
  }

  return (
    <main className="app-shell diagnostics-shell">
      <header className="topbar dashboard-topbar">
        <div>
          <h1>Hermes 诊断工具</h1>
          <p>配置检查、Doctor 和凭据状态在这里直接运行并展示结果。</p>
        </div>
        <div className="topbar-actions">
          <button type="button" onClick={() => void openAppView(returnTarget)}>{returnLabel}</button>
          <button
            className="primary-action"
            type="button"
            disabled={busy}
            onClick={() => void runDiagnostic()}
          >
            {busy ? '运行中...' : '重新运行'}
          </button>
        </div>
      </header>

      {status ? <div className={diagnosticNoticeClass(status)}>{status}</div> : null}

      <section className="hy-diagnostic-grid" aria-label="系统检测">
        {diagnosticOverviewItems(overview, diagnosticCache).map((item) => (
          <article className={`hy-diagnostic-check ${item.status}`} key={item.label}>
            <span>{item.label}</span>
            <strong>{diagnosticStatusLabel(item.status)}</strong>
            <small>{item.detail}</small>
          </article>
        ))}
      </section>

      <section className="diagnostic-command-grid" aria-label="诊断命令">
        {DIAGNOSTIC_ACTIONS.map((action) => (
          <button
            type="button"
            className={action.command === selectedAction.command ? 'diagnostic-command-card selected' : 'diagnostic-command-card'}
            disabled={busy}
            key={action.id}
            onClick={() => void runDiagnostic(action.command)}
          >
            <span>{action.label}</span>
            <strong>{action.command}</strong>
            <small>{action.description}</small>
          </button>
        ))}
      </section>

      <section className="panel diagnostic-result-panel">
        <div className="section-heading-row">
          <div>
            <h2>运行状态</h2>
            <p className="section-caption">读取 /status 与 /tasks，显示 Bridge Runtime、Hermes ready 和任务计数。</p>
          </div>
          <button type="button" disabled={Boolean(runtimeBusy)} onClick={() => void loadRuntimeSnapshot()}>
            {runtimeBusy === 'refresh' ? '刷新中...' : '刷新'}
          </button>
        </div>
        <div className="diagnostic-result-meta">
          <span>服务：{runtimeStatus?.service || '—'}</span>
          <span>版本：{runtimeStatus?.version || '—'}</span>
          <span>Uptime：{formatDuration(runtimeStatus?.uptime_seconds)}</span>
          <span>Hermes：{runtimeStatus?.hermes_ready ? 'ready' : 'not ready'}</span>
          <span>任务：{formatTaskCounts(runtimeStatus?.task_counts)}</span>
        </div>
      </section>

      <section className="panel diagnostic-result-panel">
        <div className="section-heading-row">
          <div>
            <h2>任务队列</h2>
            <p className="section-caption">只创建默认低风险任务；pending / running 任务可以取消。</p>
          </div>
          <span>{tasks.length} 项</span>
        </div>
        <div className="hermes-config-form-grid">
          <label className="settings-field wide" htmlFor="diagnostics-task-description">
            <span>任务描述</span>
            <input
              id="diagnostics-task-description"
              value={taskDraft.description}
              maxLength={500}
              placeholder="例如：检查当前运行状态"
              disabled={Boolean(runtimeBusy)}
              onChange={(event) => setTaskDraft((current) => ({ ...current, description: event.target.value }))}
            />
          </label>
          <label className="settings-field" htmlFor="diagnostics-task-type">
            <span>任务类型</span>
            <select
              id="diagnostics-task-type"
              value={taskDraft.task_type}
              disabled={Boolean(runtimeBusy)}
              onChange={(event) => setTaskDraft((current) => ({ ...current, task_type: event.target.value }))}
            >
              <option value="general">general</option>
              <option value="status_query">status_query</option>
              <option value="screenshot">screenshot</option>
              <option value="active_window">active_window</option>
            </select>
          </label>
          <label className="settings-field" htmlFor="diagnostics-task-risk">
            <span>风险等级</span>
            <select
              id="diagnostics-task-risk"
              value={taskDraft.risk_level}
              disabled={Boolean(runtimeBusy)}
              onChange={(event) => setTaskDraft((current) => ({ ...current, risk_level: event.target.value }))}
            >
              <option value="low">low</option>
              <option value="medium">medium</option>
            </select>
          </label>
          <div className="settings-savebar wide-form-note">
            <span>不提供 high 风险快捷创建入口。</span>
            <button type="button" className="primary-action" disabled={Boolean(runtimeBusy) || !taskDraft.description.trim()} onClick={() => void createTask()}>
              {runtimeBusy === 'create-task' ? '创建中...' : '创建任务'}
            </button>
          </div>
        </div>
        <div className="diagnostic-task-list">
          {tasks.slice(0, 10).map((task) => (
            <article className="diagnostic-task-row" key={task.task_id}>
              <div>
                <strong>{task.description}</strong>
                <small>{task.task_type} · {task.risk_level} · {formatShortDateTime(task.updated_at)}</small>
                {task.result || task.error ? <p>{task.error || task.result}</p> : null}
              </div>
              <div className="diagnostic-task-actions">
                <span className={task.status === 'completed' ? 'status-pill ok' : 'status-pill warn'}>{task.status}</span>
                {task.status === 'pending' || task.status === 'running' ? (
                  <button type="button" disabled={Boolean(runtimeBusy)} onClick={() => void cancelTask(task.task_id)}>
                    {runtimeBusy === `cancel-${task.task_id}` ? '取消中...' : '取消'}
                  </button>
                ) : null}
              </div>
            </article>
          ))}
          {!tasks.length ? <div className="empty-state inline-empty">暂无任务</div> : null}
        </div>
      </section>

      <section className="panel diagnostic-result-panel">
        <div className="section-heading-row">
          <div>
            <h2>助手意图测试</h2>
            <p className="section-caption">默认先 dry-run；执行按钮会调用 /assistant/intent 创建低风险任务。</p>
          </div>
        </div>
        <div className="hermes-config-form-grid">
          <label className="settings-field wide" htmlFor="diagnostics-intent-text">
            <span>输入文本</span>
            <input
              id="diagnostics-intent-text"
              value={intentText}
              maxLength={1000}
              placeholder="例如：帮我检查当前系统状态"
              disabled={Boolean(runtimeBusy)}
              onChange={(event) => setIntentText(event.target.value)}
            />
          </label>
          <div className="settings-savebar wide-form-note">
            <span>{intentResult ? `${intentResult.action || 'intent'}：${intentResult.message || '完成'}` : '不会自动执行高风险动作。'}</span>
            <button type="button" disabled={Boolean(runtimeBusy) || !intentText.trim()} onClick={() => void runAssistantIntent(true)}>
              {runtimeBusy === 'intent-dry-run' ? '分析中...' : 'Dry-run'}
            </button>
            <button type="button" className="primary-action" disabled={Boolean(runtimeBusy) || !intentText.trim()} onClick={() => void runAssistantIntent(false)}>
              {runtimeBusy === 'intent-create' ? '执行中...' : '创建低风险任务'}
            </button>
          </div>
        </div>
      </section>

      <section className="panel diagnostic-result-panel">
        <div className="section-heading-row">
          <div>
            <h2>本地能力探测</h2>
            <p className="section-caption">手动调用截图与活动窗口接口；截图只显示本地缩略预览和尺寸。</p>
          </div>
          <div className="diagnostic-result-actions">
            <button type="button" disabled={Boolean(runtimeBusy)} onClick={() => void probeScreen()}>{runtimeBusy === 'screen' ? '探测中...' : '截图摘要'}</button>
            <button type="button" disabled={Boolean(runtimeBusy)} onClick={() => void probeActiveWindow()}>{runtimeBusy === 'active-window' ? '探测中...' : '活动窗口'}</button>
          </div>
        </div>
        <div className="diagnostic-probe-grid">
          <article className="diagnostic-probe-card">
            <strong>屏幕截图</strong>
            <span>{screenProbe ? `${screenProbe.width || '—'}×${screenProbe.height || '—'} · ${screenProbe.format || 'png'} · ${formatShortDateTime(screenProbe.captured_at)}` : '未探测'}</span>
            {screenProbe?.image_base64 ? <img src={`data:image/${screenProbe.format || 'png'};base64,${screenProbe.image_base64}`} alt="当前屏幕缩略图" /> : null}
          </article>
          <article className="diagnostic-probe-card">
            <strong>活动窗口</strong>
            <span>{activeWindowProbe ? `${activeWindowProbe.app_name || '—'} · ${activeWindowProbe.title || '无标题'}` : '未探测'}</span>
            <small>{activeWindowProbe?.pid ? `pid ${activeWindowProbe.pid}` : ''}{activeWindowProbe?.queried_at ? ` · ${formatShortDateTime(activeWindowProbe.queried_at)}` : ''}</small>
          </article>
        </div>
      </section>

      <section className="panel diagnostic-result-panel">
        <div className="section-heading-row">
          <div>
            <h2>{result?.label || selectedAction.label}</h2>
            <p className="section-caption">{result?.command || selectedAction.command}</p>
          </div>
          <StatusPill active={Boolean(result?.success) && !result?.stale} label={diagnosticResultLabel(result, busy)} />
        </div>
        <div className="diagnostic-result-meta">
          <span>退出码：{result?.returncode ?? '—'}</span>
          <span>耗时：{result?.elapsed_seconds !== undefined ? `${result.elapsed_seconds}s` : '—'}</span>
          {result?.cached_at ? <span>缓存：{formatShortDateTime(result.cached_at)}</span> : null}
          {diagnosticCache?.stale ? <span>配置已变化，建议重新运行</span> : null}
        </div>
        <pre className="diagnostic-output">{diagnosticOutput(result, busy)}</pre>
        <div className="diagnostic-result-actions">
          <button type="button" disabled={!result || busy} onClick={() => void copyOutput()}>复制输出</button>
          <button type="button" onClick={() => void openAppView(returnTarget)}>{returnLabel}</button>
        </div>
      </section>
    </main>
  );
}

function normalizeReturnTarget(value: string): 'main' | 'tools' {
  return value === 'tools' ? 'tools' : 'main';
}

function normalizeDiagnosticCommand(value: string): string {
  const normalized = value.trim().replace(/\s+/g, ' ');
  return DIAGNOSTIC_ACTIONS.find((action) => action.command === normalized || action.id === normalized)?.command || '';
}

function diagnosticNoticeClass(message: string) {
  return /失败|错误|无法|不支持|超时/.test(message) ? 'notice danger' : 'notice';
}

function diagnosticCacheStatus(cache: DiagnosticCache, result: DiagnosticResult): string {
  const label = result.label || result.command || '诊断结果';
  const time = formatShortDateTime(result.cached_at || cache.updated_at);
  if (cache.stale) return `${label} 使用上次缓存（${time}），配置已变化，请手动重新运行`;
  return `${label} 使用上次缓存（${time}）`;
}

function diagnosticResultLabel(result: DiagnosticResult | null, busy: boolean): string {
  if (busy) return '运行中';
  if (!result) return '待运行';
  if (result.stale) return '需重检';
  return result.success ? '完成' : '失败';
}

function diagnosticOutput(result: DiagnosticResult | null, busy: boolean): string {
  if (busy && !result) return '正在等待 Hermes 输出...';
  if (!result) return '选择一个诊断命令后，结果会显示在这里。';
  return result.output || result.stdout || result.stderr || '命令没有输出。';
}

function StatusPill({ active, label }: { active: boolean; label: string }) {
  return <span className={active ? 'status-pill ok' : 'status-pill warn'}>{label}</span>;
}

function diagnosticOverviewItems(
  data: DashboardStatus | null,
  cache: DiagnosticCache | null,
): DiagnosticOverviewItem[] {
  const bridge = data?.bridge?.state || data?.bridge?.status || data?.bridge?.running || '';
  const bridgeOk = /running|listening|ready|ok/i.test(bridge);
  const hermesReady = Boolean(data?.hermes?.ready);
  const commandExists = Boolean(data?.hermes?.command_exists);
  const workspaceReady = Boolean(data?.workspace?.initialized);
  const doctorIssues = Number(data?.hermes?.doctor_issues_count || 0);
  const hasDoctorCache = Boolean(cache?.commands?.doctor);

  return [
    {
      label: 'Python',
      status: commandExists ? 'passed' : 'warning',
      detail: data?.hermes?.platform || '随 Hermes 环境检测',
    },
    {
      label: 'Node.js',
      status: 'passed',
      detail: '桌面前端运行中',
    },
    {
      label: 'Bridge',
      status: bridgeOk ? 'passed' : 'warning',
      detail: data?.bridge?.url || bridge || '等待本机 Bridge',
    },
    {
      label: '模型',
      status: hermesReady ? 'passed' : commandExists ? 'warning' : 'error',
      detail: hermesReady ? '基础链路可用' : commandExists ? '需要连接测试' : '未检测到 hermes',
    },
    {
      label: 'GPU',
      status: hasDoctorCache && !doctorIssues ? 'passed' : 'warning',
      detail: hasDoctorCache ? (doctorIssues ? `${doctorIssues} 项 Doctor 提示` : 'Doctor 未报告受限项') : '运行 Doctor 后刷新',
    },
    {
      label: '工作区',
      status: workspaceReady ? 'passed' : 'warning',
      detail: data?.workspace?.path || '等待初始化',
    },
    {
      label: 'Live2D',
      status: workspaceReady ? 'warning' : 'error',
      detail: workspaceReady ? '资源状态在 Live2D 页查看' : '需要工作区',
    },
    {
      label: 'TTS',
      status: workspaceReady ? 'warning' : 'error',
      detail: workspaceReady ? '语音状态在 GPT-SoVITS 页查看' : '需要工作区',
    },
  ];
}

function diagnosticStatusLabel(status: DiagnosticOverviewItem['status']): string {
  if (status === 'passed') return 'passed';
  if (status === 'error') return 'error';
  return 'warning';
}

function formatShortDateTime(value?: string) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatDuration(value?: number) {
  if (!Number.isFinite(Number(value))) return '—';
  const seconds = Math.max(0, Math.floor(Number(value)));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const rest = seconds % 60;
  if (hours) return `${hours}h ${minutes}m`;
  if (minutes) return `${minutes}m ${rest}s`;
  return `${rest}s`;
}

function formatTaskCounts(counts?: Record<string, number>) {
  if (!counts) return '—';
  const parts = ['pending', 'running', 'completed', 'failed', 'cancelled']
    .map((key) => `${key}=${Number(counts[key] || 0)}`);
  return parts.join(' · ');
}
