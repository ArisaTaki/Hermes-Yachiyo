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
