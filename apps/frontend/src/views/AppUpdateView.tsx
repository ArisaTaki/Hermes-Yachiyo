import { useEffect, useMemo, useState } from 'react';

import {
  type AppUpdateCheckResult,
  type AppUpdateDownloadProgress,
  type AppUpdateDownloadResult,
  type AppUpdateInfo,
  type LatestReleaseMetadata,
  type ReleaseChangelog,
  checkAppUpdate,
  downloadAppUpdate,
  getAppUpdateInfo,
  installAppUpdate,
  onAppUpdateDownloadProgress,
  openExternalUrl,
} from '../lib/bridge';
import { navigateTo } from '../lib/view';
import { usePageLoading } from './OpenDesignView';

type UpdateAction = '' | 'check' | 'download' | 'install';

export function AppUpdateView() {
  const [info, setInfo] = useState<AppUpdateInfo | null>(null);
  const [check, setCheck] = useState<AppUpdateCheckResult | null>(null);
  const [download, setDownload] = useState<AppUpdateDownloadResult | null>(null);
  const [progress, setProgress] = useState<AppUpdateDownloadProgress | null>(null);
  const [action, setAction] = useState<UpdateAction>('check');
  const [status, setStatus] = useState('正在检查应用更新...');

  usePageLoading(action === 'check' && !check && !info);

  const latest = check?.latest || download?.latest || info?.downloaded_update?.latest;
  const current = check?.current || info?.current;
  const downloaded = download?.ok ? download : info?.downloaded_update;
  const supported = Boolean(check?.supported ?? info?.supported);
  const updateAvailable = Boolean(check?.update_available);
  const changelog = latest?.changelog || downloaded?.latest?.changelog;
  const progressPercent = downloadProgressPercent(progress, downloaded);
  const channelLabel = latest?.channel || latest?.branch || current?.channel || current?.branch || '—';
  const versionRows = useMemo(() => updateVersionRows(current, latest), [current, latest]);

  useEffect(() => {
    let disposed = false;
    async function loadUpdateState() {
      setAction('check');
      try {
        const nextInfo = await getAppUpdateInfo();
        if (disposed) return;
        setInfo(nextInfo);
        if (nextInfo.downloaded_update?.ok) setDownload(nextInfo.downloaded_update);
        const result = await checkAppUpdate();
        if (disposed) return;
        setCheck(result);
        setInfo(result);
        setDownload(result.downloaded_update?.ok ? result.downloaded_update : nextInfo.downloaded_update || null);
        if (result.ok === false) {
          setStatus(result.error || '检查更新失败');
        } else if (result.update_available) {
          setStatus(result.reason || '发现可用更新');
        } else {
          setStatus(result.reason || '当前已是最新版本');
        }
      } catch (err) {
        if (!disposed) {
          setStatus(err instanceof Error ? err.message : '检查更新失败');
          setInfo({ supported: false, packaged: false, error: err instanceof Error ? err.message : '检查更新失败' });
        }
      } finally {
        if (!disposed) setAction('');
      }
    }
    void loadUpdateState();
    return () => {
      disposed = true;
    };
  }, []);

  useEffect(() => onAppUpdateDownloadProgress((payload) => {
    setProgress(payload);
    if (payload.status === 'failed') setStatus(payload.error || '下载更新失败');
  }), []);

  async function runCheck() {
    if (action) return;
    setAction('check');
    setStatus('正在检查应用更新...');
    try {
      const result = await checkAppUpdate();
      setCheck(result);
      setInfo(result);
      setDownload(result.downloaded_update?.ok ? result.downloaded_update : null);
      if (result.ok === false) throw new Error(result.error || '检查更新失败');
      setStatus(result.update_available ? result.reason || '发现可用更新' : result.reason || '当前已是最新版本');
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '检查更新失败');
    } finally {
      setAction('');
    }
  }

  async function runDownload() {
    if (action) return;
    setAction('download');
    setProgress({ status: 'starting', file_name: latest?.dmg_name });
    setStatus('正在下载应用更新...');
    try {
      const result = await downloadAppUpdate();
      setDownload(result);
      if (!result.ok) throw new Error(result.error || '下载应用更新失败');
      const nextInfo = await getAppUpdateInfo();
      setInfo(nextInfo);
      setProgress({ status: 'completed', file_name: result.file_name, percent: 100 });
      setStatus(result.verified ? '更新已下载并通过校验，可安装并重启' : '更新已下载，可安装并重启；当前元数据未提供 SHA256 校验值');
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '下载应用更新失败');
    } finally {
      setAction('');
    }
  }

  async function runInstall() {
    if (action) return;
    const dmgPath = downloaded?.path || info?.downloaded_dmg_path || '';
    if (!dmgPath) {
      setStatus('请先下载应用更新');
      return;
    }
    if (!window.confirm('将退出 Hermes-Yachiyo，用已下载的 DMG 覆盖当前应用，然后重新打开。继续吗？')) return;
    setAction('install');
    setStatus('正在准备安装更新，应用将退出并重新打开...');
    try {
      const result = await installAppUpdate(dmgPath);
      if (!result.success) throw new Error(result.error || '启动更新安装失败');
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '启动更新安装失败');
      setAction('');
    }
  }

  return (
    <section className="hy-route-page app-update-page">
      <header className="hy-page-header app-update-header hy-stagger">
        <div>
          <button type="button" className="page-back-link" onClick={() => navigateTo('settings')}>← 返回设置</button>
          <span className="hy-eyebrow">Update Channel · {channelLabel}</span>
          <h2>应用更新</h2>
          <p>检查 Hermes Yachiyo 桌面应用版本差距，下载 DMG，并在校验后安装重启。</p>
        </div>
        <div className="hy-action-row">
          <button type="button" className="hy-btn hy-btn-ghost" disabled={Boolean(action)} onClick={() => void runCheck()}>
            {action === 'check' ? '检查中...' : '重新检查'}
          </button>
          {changelog?.compare_url ? (
            <button type="button" className="hy-btn hy-btn-ghost" onClick={() => void openExternalUrl(changelog.compare_url || '')}>版本差异</button>
          ) : null}
        </div>
      </header>

      {status ? <div className={/失败|错误|不支持/.test(status) ? 'notice danger hy-stagger' : 'notice hy-stagger'}>{status}</div> : null}

      <section className={updateAvailable ? 'app-update-hero attention hy-stagger' : 'app-update-hero hy-stagger'}>
        <div>
          <span>{updateStatusLabel(info, check, downloaded)}</span>
          <strong>{updateAvailable ? latest?.version || latest?.tag || '发现新版本' : current?.version || '当前版本'}</strong>
          <p>{updateAvailable ? check?.reason || '可下载新的桌面应用版本。' : info?.error || check?.reason || '当前未检测到可用更新。'}</p>
        </div>
        <div className="app-update-actions">
          {downloaded?.ok ? (
            <button type="button" className="hy-btn hy-btn-primary" disabled={Boolean(action)} onClick={() => void runInstall()}>
              {action === 'install' ? '准备中...' : '安装并重启'}
            </button>
          ) : (
            <button type="button" className="hy-btn hy-btn-primary" disabled={Boolean(action) || !supported || !updateAvailable} onClick={() => void runDownload()}>
              {action === 'download' ? downloadButtonLabel(progress) : '下载更新'}
            </button>
          )}
        </div>
      </section>

      <section className="app-update-grid hy-stagger">
        {versionRows.map((row) => (
          <article className="app-update-card" key={row.label}>
            <span>{row.label}</span>
            <strong>{row.value}</strong>
            <small>{row.detail}</small>
          </article>
        ))}
      </section>

      <section className="app-update-download-panel hy-stagger">
        <div className="section-heading-row">
          <div>
            <h2>下载进度</h2>
            <p className="section-caption">{downloaded?.file_name || progress?.file_name || latest?.dmg_name || '等待下载任务'}</p>
          </div>
          <span>{downloadProgressLabel(progress, downloaded)}</span>
        </div>
        <div className="app-update-progress-track" aria-hidden>
          <span style={{ width: `${progressPercent}%` }} />
        </div>
        <div className="app-update-progress-meta">
          <span>{progress?.received_bytes ? formatByteCount(progress.received_bytes) : '0 B'}</span>
          <span>{progress?.total_bytes ? formatByteCount(progress.total_bytes) : downloaded?.path || '—'}</span>
          <span>{downloaded?.verified ? 'SHA256 已通过' : downloaded?.ok ? '未提供 SHA256' : '等待校验'}</span>
        </div>
      </section>

      {changelog ? <UpdateChangelog changelog={changelog} /> : null}
    </section>
  );
}

function UpdateChangelog({ changelog }: { changelog: ReleaseChangelog }) {
  const sections = changelog.sections?.length
    ? changelog.sections
    : [{ title: '变更摘要', items: changelog.commits || [] }];
  return (
    <section className="app-update-changelog hy-stagger">
      <div className="section-heading-row">
        <div>
          <h2>版本差异</h2>
          <p className="section-caption">
            {changelog.commit_count !== undefined ? `${changelog.commit_count} 个提交` : 'Release changelog'}
            {changelog.previous_tag || changelog.current_tag ? ` · ${changelog.previous_tag || '上一版本'} → ${changelog.current_tag || '最新版本'}` : ''}
          </p>
        </div>
        {changelog.compare_url ? <button type="button" className="hy-btn hy-btn-ghost" onClick={() => void openExternalUrl(changelog.compare_url || '')}>打开对比</button> : null}
      </div>
      {changelog.summary?.length ? (
        <ul className="app-update-summary">
          {changelog.summary.slice(0, 5).map((item) => <li key={item}>{item}</li>)}
        </ul>
      ) : null}
      <div className="app-update-change-sections">
        {sections.slice(0, 4).map((section, index) => (
          <div className="app-update-change-section" key={section.title || index}>
            <strong>{section.title || 'Changes'}</strong>
            <ul>
              {(section.items || []).slice(0, 8).map((commit) => (
                <li key={commit.commit || commit.subject}>
                  <span>{commit.subject || commit.short_commit || commit.commit}</span>
                  <small>{commit.short_commit || commit.author || ''}</small>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}

function updateVersionRows(current: AppUpdateInfo['current'], latest: LatestReleaseMetadata | undefined) {
  return [
    {
      label: '当前版本',
      value: buildLabel(current?.version, current?.build_number, current?.short_commit),
      detail: current?.branch || current?.channel || current?.built_at || '本地构建',
    },
    {
      label: '最新版本',
      value: buildLabel(latest?.version || latest?.tag, latest?.build_number || latest?.run_number, latest?.short_commit),
      detail: latest?.source_branch || latest?.branch || latest?.published_at || '等待远端元数据',
    },
    {
      label: '安装包',
      value: latest?.dmg_name || '—',
      detail: latest?.sha256 ? `SHA256 ${latest.sha256.slice(0, 12)}...` : latest?.download_url ? '可下载' : '未提供下载地址',
    },
  ];
}

function buildLabel(version?: string, buildNumber?: number, shortCommit?: string) {
  const parts = [
    version || '',
    buildNumber !== undefined ? `#${buildNumber}` : '',
    shortCommit || '',
  ].filter(Boolean);
  return parts.length ? parts.join(' / ') : '—';
}

function updateStatusLabel(
  info: AppUpdateInfo | null,
  check: AppUpdateCheckResult | null,
  download: AppUpdateDownloadResult | undefined,
) {
  if (download?.ok) return '已下载';
  if (check?.ok === false) return '检查失败';
  if (check?.update_available) return '有更新';
  if (check?.ok) return '已是最新';
  if (info?.supported === false) return info.packaged ? '不可更新' : '开发环境';
  return '检查中';
}

function downloadProgressPercent(progress: AppUpdateDownloadProgress | null, download: AppUpdateDownloadResult | undefined) {
  if (download?.ok) return 100;
  if (typeof progress?.percent === 'number') return Math.max(0, Math.min(100, progress.percent));
  if (progress?.received_bytes && progress.total_bytes) {
    return Math.max(0, Math.min(100, (progress.received_bytes / progress.total_bytes) * 100));
  }
  if (progress?.status === 'starting') return 8;
  if (progress?.status === 'verifying') return 92;
  return 0;
}

function downloadProgressLabel(progress: AppUpdateDownloadProgress | null, download: AppUpdateDownloadResult | undefined) {
  if (download?.ok) return '已下载';
  if (!progress) return '待下载';
  if (progress.status === 'verifying') return '校验中';
  if (progress.status === 'completed') return '100%';
  if (progress.status === 'failed') return progress.error || '失败';
  if (typeof progress.percent === 'number') return `${progress.percent.toFixed(progress.percent % 1 ? 1 : 0)}%`;
  if (progress.status === 'starting') return '准备下载';
  return '下载中';
}

function downloadButtonLabel(progress: AppUpdateDownloadProgress | null) {
  if (progress?.status === 'verifying') return '校验中...';
  if (typeof progress?.percent === 'number') return `下载中 ${progress.percent.toFixed(0)}%`;
  return '下载中...';
}

function formatByteCount(value: number) {
  if (!Number.isFinite(value) || value <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(size >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`;
}
