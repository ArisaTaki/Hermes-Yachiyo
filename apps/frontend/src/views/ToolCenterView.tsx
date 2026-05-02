import { useEffect, useState } from 'react';

import { apiGet, apiPost, openAppView } from '../lib/bridge';

type HermesStatus = {
  status?: string;
  version?: string;
  platform?: string;
  command_exists?: boolean;
  hermes_home?: string;
  ready?: boolean;
  readiness_level?: string;
  limited_tools?: string[];
  doctor_issues_count?: number;
};

type DashboardData = {
  hermes?: HermesStatus;
};

type DoctorSummary = {
  readiness_level?: string;
  limited_tools?: string[];
  doctor_issues_count?: number;
};

type DiagnosticResult = {
  success?: boolean;
  label?: string;
  command?: string;
  cached_at?: string;
  stale?: boolean;
  doctor_summary?: DoctorSummary;
};

type DiagnosticCache = {
  stale?: boolean;
  reason?: string;
  updated_at?: string;
  commands?: Record<string, DiagnosticResult>;
};

type HermesToolCatalogItem = {
  id: string;
  label: string;
  category: string;
  description: string;
  requirement?: string;
  aliases?: string[];
  planned?: boolean;
};

type ToolStatus = {
  kind: 'ready' | 'limited' | 'pending' | 'planned';
  label: string;
  detail: string;
};

const HERMES_TOOL_CATALOG: HermesToolCatalogItem[] = [
  {
    id: 'web',
    label: '联网与网页读取',
    category: '信息检索',
    description: '搜索、读取网页内容并把结果交给 Hermes 推理。',
    requirement: '需要 Hermes web/search 工具可用',
    aliases: ['search'],
  },
  {
    id: 'browser',
    label: '浏览器自动化',
    category: '信息检索',
    description: '通过浏览器会话访问需要交互的页面。',
    requirement: '需要浏览器 CDP 或对应 MCP 服务',
    aliases: ['browser-cdp'],
  },
  {
    id: 'vision',
    label: '图像理解',
    category: '多模态',
    description: '读取截图和图片内容，辅助视觉类任务。',
    requirement: '需要模型或 provider 支持视觉输入',
  },
  {
    id: 'image_gen',
    label: '图片生成',
    category: '多模态',
    description: '调用图片生成 provider 产出图片资产。',
    requirement: '需要图片生成 provider 和密钥',
  },
  {
    id: 'terminal',
    label: '终端执行',
    category: '本地工作',
    description: '在 Hermes 允许范围内执行命令和读取结果。',
    requirement: '需要 Hermes 本地执行权限',
  },
  {
    id: 'file',
    label: '文件读写',
    category: '本地工作',
    description: '读取、生成和修改本地工作文件。',
    requirement: '需要 Hermes 文件工具权限',
  },
  {
    id: 'skills',
    label: '技能加载',
    category: '本地工作',
    description: '加载 Hermes 或项目内定义的技能工作流。',
    requirement: '需要技能目录或插件可读取',
  },
  {
    id: 'code_execution',
    label: '代码执行',
    category: '本地工作',
    description: '运行受控代码片段，处理数据或验证逻辑。',
    requirement: '需要 Hermes 代码执行环境',
  },
  {
    id: 'memory',
    label: '记忆',
    category: '长期上下文',
    description: '读取和维护 Hermes 记忆信息。',
    requirement: '需要 memory 工具集启用',
  },
  {
    id: 'session_search',
    label: '会话检索',
    category: '长期上下文',
    description: '检索历史会话，帮助跨会话延续上下文。',
    requirement: '需要会话索引可用',
  },
  {
    id: 'todo',
    label: '任务清单',
    category: '长期上下文',
    description: '维护 Hermes 内部的待办与计划状态。',
    requirement: '需要 todo 工具集启用',
  },
  {
    id: 'cronjob',
    label: '定时任务',
    category: '自动化',
    description: '创建或管理 Hermes 侧的定时自动化。',
    requirement: '需要 cronjob 工具集配置',
  },
  {
    id: 'messaging',
    label: '消息通知',
    category: '外部服务',
    description: '向外部消息渠道发送通知或结果。',
    requirement: '需要 webhook、token 或服务地址',
  },
  {
    id: 'discord',
    label: 'Discord',
    category: '外部服务',
    description: '连接 Discord 用户或频道工作流。',
    requirement: '需要 Discord 凭据',
    aliases: ['discord_admin'],
  },
  {
    id: 'homeassistant',
    label: 'Home Assistant',
    category: '外部服务',
    description: '连接家庭自动化设备和场景。',
    requirement: '需要 Home Assistant 地址和 token',
  },
  {
    id: 'spotify',
    label: 'Spotify',
    category: '外部服务',
    description: '读取或控制 Spotify 相关工作流。',
    requirement: '需要 Spotify 授权',
  },
  {
    id: 'yuanbao',
    label: '腾讯元宝',
    category: '第三方扩展',
    description: '连接 Hermes 的元宝扩展能力。',
    requirement: '需要 hermes-yuanbao 配置',
    aliases: ['hermes-yuanbao'],
  },
  {
    id: 'moa',
    label: 'MoA',
    category: '第三方扩展',
    description: '使用 Hermes 的多模型协作能力。',
    requirement: '需要实验工具或额外 provider 配置',
  },
  {
    id: 'rl',
    label: 'RL',
    category: '第三方扩展',
    description: '连接 Hermes 实验性强化学习相关能力。',
    requirement: '需要实验工具开关或额外依赖',
  },
  {
    id: 'local-app-control',
    label: 'Yachiyo 本机应用控制',
    category: 'Yachiyo 规划',
    description: '未来可把音乐、快捷指令和窗口控制做成 Yachiyo 原生能力。',
    requirement: '当前仅展示规划，不启用调用',
    planned: true,
  },
];

export function ToolCenterView() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [diagnosticCache, setDiagnosticCache] = useState<DiagnosticCache | null>(null);
  const [error, setError] = useState('');
  const [actionStatus, setActionStatus] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let disposed = false;
    async function refresh() {
      try {
        const [payload, cache] = await Promise.all([
          apiGet<DashboardData>('/ui/dashboard'),
          apiGet<DiagnosticCache>('/ui/hermes/diagnostics/cache').catch(() => null),
        ]);
        if (!disposed) {
          setData(payload);
          setDiagnosticCache(cache);
          setError('');
        }
      } catch (err) {
        if (!disposed) setError(err instanceof Error ? err.message : '读取工具中心失败');
      }
    }
    refresh();
    const timer = window.setInterval(refresh, 3000);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, []);

  async function recheckHermes() {
    if (busy) return;
    setBusy(true);
    setActionStatus('正在重新检测 Hermes 工具状态...');
    try {
      const payload = await apiPost<DashboardData>('/ui/hermes/recheck');
      const cache = await apiGet<DiagnosticCache>('/ui/hermes/diagnostics/cache').catch(() => null);
      setData(payload);
      setDiagnosticCache(cache);
      setError('');
      setActionStatus('工具状态已刷新');
    } catch (err) {
      setActionStatus(err instanceof Error ? err.message : '重新检测 Hermes 失败');
    } finally {
      setBusy(false);
    }
  }

  const hermes = data?.hermes;
  const commandExists = Boolean(hermes?.command_exists);
  const doctorCache = diagnosticCache?.commands?.doctor;
  const doctorSummary = !diagnosticCache?.stale ? doctorCache?.doctor_summary : undefined;
  const limitedToolNames = diagnosticCache?.stale ? [] : doctorSummary?.limited_tools || hermes?.limited_tools || [];
  const issueCount = diagnosticCache?.stale ? 0 : doctorSummary?.doctor_issues_count ?? hermes?.doctor_issues_count ?? 0;
  const limitedItems = HERMES_TOOL_CATALOG.filter((item) => !item.planned && isToolLimited(item, limitedToolNames));
  const limitedUnknown = unknownLimitedTools(limitedToolNames);
  const checked = Boolean(!diagnosticCache?.stale && (doctorCache || (hermes?.readiness_level && hermes.readiness_level !== 'unknown')));

  return (
    <main className="app-shell tools-shell">
      <header className="topbar dashboard-topbar">
        <div>
          <h1>工具中心</h1>
          <p>集中查看 Hermes toolset、Doctor 受限项和 Yachiyo 后续扩展方向。</p>
        </div>
        <div className="topbar-actions">
          <button type="button" onClick={() => void openAppView('main')}>主控台</button>
          <button
            type="button"
            className="primary-action"
            disabled={!commandExists}
            onClick={() => void openAppView('diagnostics', { command: 'hermes doctor', return_to: 'tools' })}
          >
            运行 Doctor
          </button>
          <button
            type="button"
            className={busy ? 'attention-action' : undefined}
            disabled={busy}
            onClick={() => void recheckHermes()}
          >
            {busy ? '检测中...' : '重新检测'}
          </button>
        </div>
      </header>

      {error ? <div className="notice danger">{error}</div> : null}
      {actionStatus ? <div className={/失败|错误|无法/.test(actionStatus) ? 'notice danger' : 'notice'}>{actionStatus}</div> : null}

      <section className="tool-center-panel">
        <div className="section-heading-row">
          <div>
            <h2>工具概览</h2>
            <p className="section-caption">这里只展示和诊断工具状态，不启用新的本机工具调用。</p>
          </div>
          <StatusPill
            active={!limitedItems.length && !limitedUnknown.length && checked}
            label={checked ? `${limitedItems.length + limitedUnknown.length} 个受限` : '待 Doctor'}
          />
        </div>

        <div className="tool-center-summary" aria-label="工具概览">
          <ToolSummaryCard label="已知工具组" value={`${HERMES_TOOL_CATALOG.filter((item) => !item.planned).length}`} detail="来自 Hermes toolset 目录" />
          <ToolSummaryCard
            label="Doctor 受限"
            value={diagnosticCache?.stale ? '需重检' : `${limitedItems.length + limitedUnknown.length}`}
            detail={doctorCache?.cached_at ? `上次检查 ${formatShortDateTime(doctorCache.cached_at)}` : checked ? `${issueCount} 项诊断提示` : '尚未完成 Doctor 分级'}
            warn={Boolean(diagnosticCache?.stale || limitedItems.length || limitedUnknown.length)}
          />
          <ToolSummaryCard label="Yachiyo 扩展" value="规划中" detail="音乐、窗口、快捷指令等后续再接入" muted />
        </div>

        {diagnosticCache?.stale ? (
          <div className="tool-limited-banner">
            <strong>诊断缓存已过期</strong>
            <div>
              <span>配置文件或密钥状态已变化</span>
              <span>请手动运行 Doctor 刷新工具状态</span>
            </div>
          </div>
        ) : (limitedItems.length || limitedUnknown.length) ? (
          <div className="tool-limited-banner">
            <strong>需要处理的工具</strong>
            <div>
              {limitedItems.map((item) => <span key={item.id}>{item.label}</span>)}
              {limitedUnknown.map((tool) => <span key={tool}>{tool}</span>)}
            </div>
          </div>
        ) : (
          <div className="tool-empty-banner">
            <strong>{checked ? '当前没有受限工具记录' : '还没有 Doctor 结果'}</strong>
            <span>{checked ? '如果扩展能力表现异常，可以重新运行 Doctor。' : '运行 Doctor 后，这里会把受限工具整理成可读的配置清单。'}</span>
          </div>
        )}

        <div className="tool-action-row">
          <button
            type="button"
            className="primary-action"
            disabled={!commandExists}
            onClick={() => void openAppView('diagnostics', { command: 'hermes doctor', return_to: 'tools' })}
          >
            运行 Doctor 并查看结果
          </button>
          <button
            type="button"
            disabled={!commandExists}
            onClick={() => void openAppView('diagnostics', { command: 'hermes config check', return_to: 'tools' })}
          >
            检查配置结构
          </button>
          <button type="button" disabled={busy} onClick={() => void recheckHermes()}>
            {busy ? '检测中...' : '重新检测'}
          </button>
        </div>

        <ToolCategoryList hermes={hermes} limitedTools={diagnosticCache?.stale ? [] : limitedToolNames} cacheStale={Boolean(diagnosticCache?.stale)} />
      </section>
    </main>
  );
}

function ToolCategoryList({ hermes, limitedTools, cacheStale }: { hermes?: HermesStatus; limitedTools: string[]; cacheStale: boolean }) {
  return (
    <div className="tool-category-list">
      {toolCategoryGroups(HERMES_TOOL_CATALOG).map(([category, items]) => (
        <section className="tool-category-section" key={category}>
          <div className="tool-category-heading">
            <strong>{category}</strong>
            <span>{items.length} 项</span>
          </div>
          <div className="tool-grid">
            {items.map((item) => {
              const status = toolStatusFor(item, hermes, limitedTools, cacheStale);
              return (
                <article className={`tool-card ${status.kind}`} key={item.id}>
                  <div className="tool-card-head">
                    <strong>{item.label}</strong>
                    <span className={`tool-status-pill ${status.kind}`}>{status.label}</span>
                  </div>
                  <p>{item.description}</p>
                  <small>{item.requirement || status.detail}</small>
                </article>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}

function ToolSummaryCard({
  label,
  value,
  detail,
  warn,
  muted,
}: {
  label: string;
  value: string;
  detail: string;
  warn?: boolean;
  muted?: boolean;
}) {
  return (
    <article className={warn ? 'tool-summary-card warn' : muted ? 'tool-summary-card muted' : 'tool-summary-card'}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </article>
  );
}

function StatusPill({ active, label }: { active: boolean; label: string }) {
  return <span className={active ? 'status-pill ok' : 'status-pill warn'}>{label}</span>;
}

function toolCategoryGroups(items: HermesToolCatalogItem[]): Array<[string, HermesToolCatalogItem[]]> {
  const groups = new Map<string, HermesToolCatalogItem[]>();
  for (const item of items) {
    const entries = groups.get(item.category) || [];
    entries.push(item);
    groups.set(item.category, entries);
  }
  return Array.from(groups.entries());
}

function toolStatusFor(item: HermesToolCatalogItem, hermes: HermesStatus | undefined, limitedTools: string[], cacheStale: boolean): ToolStatus {
  if (item.planned) {
    return {
      kind: 'planned',
      label: '规划中',
      detail: '当前只展示方向，不启用本机工具调用。',
    };
  }
  if (isToolLimited(item, limitedTools)) {
    return {
      kind: 'limited',
      label: '受限',
      detail: 'Doctor 已标记该工具不可用或缺少配置。',
    };
  }
  if (cacheStale || !hermes?.command_exists || !hermes.ready || !hermes.readiness_level || hermes.readiness_level === 'unknown') {
    return {
      kind: 'pending',
      label: '待检测',
      detail: '运行 Doctor 后会显示更准确的工具状态。',
    };
  }
  return {
    kind: 'ready',
    label: '未受限',
    detail: '最近一次 Doctor 没有报告该工具受限。',
  };
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

function isToolLimited(item: HermesToolCatalogItem, limitedTools?: string[]): boolean {
  const limited = new Set((limitedTools || []).map(canonicalToolName));
  return toolNameAliases(item).some((alias) => limited.has(canonicalToolName(alias)));
}

function unknownLimitedTools(limitedTools?: string[]): string[] {
  const known = new Set(HERMES_TOOL_CATALOG.flatMap(toolNameAliases).map(canonicalToolName));
  return (limitedTools || []).filter((tool) => !known.has(canonicalToolName(tool)));
}

function toolNameAliases(item: HermesToolCatalogItem): string[] {
  return [item.id, ...(item.aliases || [])];
}

function canonicalToolName(value: string): string {
  return value.trim().toLowerCase().replace(/_/g, '-');
}
