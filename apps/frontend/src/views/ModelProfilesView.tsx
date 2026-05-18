import { useEffect, useMemo, useState, type FormEvent } from 'react';

import {
  createModelProfile,
  createModelSource,
  deleteModelProfile,
  deleteModelSource,
  listModelProfiles,
  testModelProfile,
  testModelSource,
  updateModelProfile,
  updateModelProfileDefaults,
  updateModelSource,
  type ModelCapability,
  type ModelProfile,
  type ModelProfileDefaults,
  type ModelSource,
} from '../lib/modelProfiles';
import { navigateTo } from '../lib/view';

type SourceDraft = {
  source_id?: string;
  name: string;
  provider: string;
  base_url: string;
  api_key: string;
  enabled: boolean;
};

type ModelDraft = {
  profile_id?: string;
  name: string;
  model: string;
  capability: ModelCapability;
  enabled: boolean;
};

const providerPresets = [
  { id: 'openai_compatible', label: 'OpenAI Compatible', baseUrl: 'https://api.openai.com/v1', mark: '◎' },
  { id: 'google_gemini', label: 'Google Gemini', baseUrl: 'https://generativelanguage.googleapis.com/v1beta/openai', mark: '◆' },
  { id: 'anthropic', label: 'Anthropic', baseUrl: 'https://api.anthropic.com/v1', mark: 'AI' },
  { id: 'kimi_coding_plan', label: 'Kimi Coding Plan', baseUrl: 'https://api.moonshot.cn/v1', mark: 'K' },
  { id: 'moonshot', label: 'Moonshot', baseUrl: 'https://api.moonshot.cn/v1', mark: 'K' },
  { id: 'minimax', label: 'MiniMax', baseUrl: 'https://api.minimax.chat/v1', mark: '〽' },
  { id: 'xai', label: 'xAI', baseUrl: 'https://api.x.ai/v1', mark: 'x' },
  { id: 'deepseek', label: 'DeepSeek', baseUrl: 'https://api.deepseek.com/v1', mark: 'DS' },
  { id: 'zhipu', label: 'Zhipu', baseUrl: 'https://open.bigmodel.cn/api/paas/v4', mark: '✺' },
  { id: 'aihubmix', label: 'AIHubMix', baseUrl: 'https://aihubmix.com/v1', mark: '☻' },
  { id: 'openrouter', label: 'OpenRouter', baseUrl: 'https://openrouter.ai/api/v1', mark: 'OR' },
  { id: 'nvidia', label: 'NVIDIA', baseUrl: 'https://integrate.api.nvidia.com/v1', mark: 'NV' },
  { id: 'azure_openai', label: 'Azure OpenAI', baseUrl: '', mark: 'A' },
  { id: 'ollama', label: 'Ollama', baseUrl: 'http://127.0.0.1:11434/v1', mark: 'O' },
  { id: 'lm_studio', label: 'LM Studio', baseUrl: 'http://127.0.0.1:1234/v1', mark: 'LM' },
  { id: 'groq', label: 'Groq', baseUrl: 'https://api.groq.com/openai/v1', mark: 'G' },
  { id: '302ai', label: '302.AI', baseUrl: 'https://api.302.ai/v1', mark: '302' },
  { id: 'siliconflow', label: 'SiliconFlow', baseUrl: 'https://api.siliconflow.cn/v1', mark: 'SF' },
  { id: 'ppio', label: 'PPIO', baseUrl: 'https://api.ppinfra.com/v3/openai', mark: 'P' },
  { id: 'tokenpony', label: 'TokenPony', baseUrl: '', mark: 'TP' },
  { id: 'compshare', label: 'Compshare', baseUrl: '', mark: 'CS' },
];

const capabilityLabels: Record<ModelCapability, string> = {
  chat: '对话',
  vision: '图片转述',
  tts: '文字转语音',
};

const emptySourceDraft: SourceDraft = {
  name: '',
  provider: 'openai_compatible',
  base_url: 'https://api.openai.com/v1',
  api_key: '',
  enabled: true,
};

const emptyModelDraft: ModelDraft = {
  name: '',
  model: '',
  capability: 'chat',
  enabled: true,
};

function statusLabel(status?: string): string {
  if (status === 'available') return '可用';
  if (status === 'failed') return '失败';
  return '未测试';
}

function statusClass(status?: string): string {
  if (status === 'available') return 'ok';
  if (status === 'failed') return 'warn';
  return '';
}

function providerPreset(provider: string) {
  return providerPresets.find((item) => item.id === provider) || providerPresets[0];
}

function sourceToDraft(source: ModelSource): SourceDraft {
  return {
    source_id: source.source_id,
    name: source.name,
    provider: source.provider || 'openai_compatible',
    base_url: source.base_url || '',
    api_key: '',
    enabled: source.enabled !== false,
  };
}

function modelToDraft(model: ModelProfile): ModelDraft {
  return {
    profile_id: model.profile_id,
    name: model.name,
    model: model.model || '',
    capability: model.capability,
    enabled: model.enabled !== false,
  };
}

function defaultModelName(source: SourceDraft, capability: ModelCapability): string {
  const preset = providerPreset(source.provider);
  if (capability === 'vision') {
    if (preset.id === 'openai_compatible') return 'gpt-4.1-mini';
    if (preset.id === 'minimax') return 'MiniMax-M2.7';
    return '';
  }
  if (capability === 'tts') return '';
  if (preset.id === 'openai_compatible') return 'gpt-4.1-mini';
  if (preset.id === 'anthropic') return 'claude-sonnet-4-5';
  if (preset.id === 'deepseek') return 'deepseek-chat';
  if (preset.id === 'minimax') return 'MiniMax-M2.7';
  return '';
}

export function ModelProfilesView() {
  const [sources, setSources] = useState<ModelSource[]>([]);
  const [profiles, setProfiles] = useState<ModelProfile[]>([]);
  const [defaults, setDefaults] = useState<ModelProfileDefaults>({});
  const [selectedSourceId, setSelectedSourceId] = useState('');
  const [selectedModelId, setSelectedModelId] = useState('');
  const [activeCapability, setActiveCapability] = useState<ModelCapability>('chat');
  const [sourceDraft, setSourceDraft] = useState<SourceDraft>(emptySourceDraft);
  const [modelDraft, setModelDraft] = useState<ModelDraft>(emptyModelDraft);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [status, setStatus] = useState('');

  const selectedSource = useMemo(
    () => sources.find((source) => source.source_id === selectedSourceId) || null,
    [selectedSourceId, sources],
  );
  const sourceModels = useMemo(
    () => profiles.filter((profile) => profile.source_id === selectedSourceId),
    [profiles, selectedSourceId],
  );
  const visibleModels = useMemo(
    () => sourceModels.filter((profile) => profile.capability === activeCapability),
    [activeCapability, sourceModels],
  );

  async function refresh(nextSourceId = selectedSourceId, nextModelId = selectedModelId) {
    const payload = await listModelProfiles();
    const nextSources = payload.sources || [];
    const nextProfiles = payload.profiles || [];
    setSources(nextSources);
    setProfiles(nextProfiles);
    setDefaults(payload.defaults || {});

    const source = nextSources.find((item) => item.source_id === nextSourceId) || nextSources[0] || null;
    if (source) {
      setSelectedSourceId(source.source_id);
      setSourceDraft(sourceToDraft(source));
      const sourceProfile = nextProfiles.find((item) => item.profile_id === nextModelId && item.source_id === source.source_id)
        || nextProfiles.find((item) => item.source_id === source.source_id && item.capability === activeCapability)
        || null;
      if (sourceProfile) {
        setSelectedModelId(sourceProfile.profile_id);
        setModelDraft(modelToDraft(sourceProfile));
      } else {
        setSelectedModelId('');
        setModelDraft({ ...emptyModelDraft, capability: activeCapability, model: defaultModelName(sourceToDraft(source), activeCapability) });
      }
    } else {
      setSelectedSourceId('');
      setSelectedModelId('');
      setSourceDraft(emptySourceDraft);
      setModelDraft({ ...emptyModelDraft, capability: activeCapability });
    }
  }

  useEffect(() => {
    let disposed = false;
    listModelProfiles()
      .then((payload) => {
        if (disposed) return;
        const nextSources = payload.sources || [];
        const nextProfiles = payload.profiles || [];
        setSources(nextSources);
        setProfiles(nextProfiles);
        setDefaults(payload.defaults || {});
        if (nextSources.length) {
          const source = nextSources[0];
          setSelectedSourceId(source.source_id);
          setSourceDraft(sourceToDraft(source));
          const firstModel = nextProfiles.find((profile) => profile.source_id === source.source_id && profile.capability === activeCapability);
          if (firstModel) {
            setSelectedModelId(firstModel.profile_id);
            setModelDraft(modelToDraft(firstModel));
          } else {
            setModelDraft({ ...emptyModelDraft, capability: activeCapability, model: defaultModelName(sourceToDraft(source), activeCapability) });
          }
        }
      })
      .catch((err) => {
        if (!disposed) setStatus(err instanceof Error ? err.message : '读取模型提供商源失败');
      })
      .finally(() => {
        if (!disposed) setLoading(false);
      });
    return () => {
      disposed = true;
    };
  }, []);

  function selectSource(source: ModelSource) {
    if (busy) return;
    setSelectedSourceId(source.source_id);
    setSourceDraft(sourceToDraft(source));
    const firstModel = profiles.find((profile) => profile.source_id === source.source_id && profile.capability === activeCapability);
    setSelectedModelId(firstModel?.profile_id || '');
    setModelDraft(firstModel ? modelToDraft(firstModel) : { ...emptyModelDraft, capability: activeCapability, model: defaultModelName(sourceToDraft(source), activeCapability) });
    setStatus('');
  }

  function createNewSource() {
    if (busy) return;
    setSelectedSourceId('');
    setSelectedModelId('');
    setSourceDraft(emptySourceDraft);
    setModelDraft({ ...emptyModelDraft, capability: activeCapability });
    setStatus('');
  }

  function switchCapability(capability: ModelCapability) {
    setActiveCapability(capability);
    const firstModel = profiles.find((profile) => profile.source_id === selectedSourceId && profile.capability === capability);
    setSelectedModelId(firstModel?.profile_id || '');
    setModelDraft(firstModel ? modelToDraft(firstModel) : { ...emptyModelDraft, capability, model: defaultModelName(sourceDraft, capability) });
  }

  function applyProvider(provider: string) {
    const preset = providerPreset(provider);
    setSourceDraft((current) => ({
      ...current,
      provider,
      name: current.name || preset.label,
      base_url: preset.baseUrl || current.base_url,
    }));
  }

  async function saveSource(): Promise<ModelSource> {
    if (!sourceDraft.name.trim()) throw new Error('提供商源名称不能为空');
    const payload = {
      name: sourceDraft.name.trim(),
      provider: sourceDraft.provider,
      base_url: sourceDraft.base_url.trim(),
      api_key: sourceDraft.api_key.trim(),
      enabled: sourceDraft.enabled,
    };
    if (sourceDraft.source_id) return updateModelSource(sourceDraft.source_id, payload);
    return createModelSource(payload);
  }

  async function onSaveSource(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy('source-save');
    setStatus('正在保存提供商源...');
    try {
      const saved = await saveSource();
      setStatus('提供商源已保存');
      await refresh(saved.source_id, selectedModelId);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '保存提供商源失败');
    } finally {
      setBusy('');
    }
  }

  async function runSourceTest() {
    if (busy) return;
    setBusy('source-test');
    setStatus('正在保存并测试提供商源...');
    try {
      const saved = await saveSource();
      const test = await testModelSource(saved.source_id, modelDraft.model);
      setStatus(test.ok || test.success ? `源测试通过：${test.message || 'OK'}` : `源测试失败：${test.message || '请检查配置'}`);
      await refresh(saved.source_id, selectedModelId);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '测试提供商源失败');
    } finally {
      setBusy('');
    }
  }

  async function saveModel(): Promise<ModelProfile> {
    const source = sourceDraft.source_id ? selectedSource : await saveSource();
    const sourceId = source?.source_id || sourceDraft.source_id || '';
    if (!sourceId) throw new Error('请先保存提供商源');
    if (!modelDraft.model.trim()) throw new Error('模型名称不能为空');
    const modelName = modelDraft.model.trim();
    const payload = {
      source_id: sourceId,
      name: modelDraft.name.trim() || `${sourceDraft.name}/${modelName}`,
      capability: modelDraft.capability,
      model: modelName,
      enabled: modelDraft.enabled,
    };
    if (modelDraft.profile_id) return updateModelProfile(modelDraft.profile_id, payload);
    return createModelProfile(payload);
  }

  async function onSaveModel(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy('model-save');
    setStatus('正在保存模型...');
    try {
      const saved = await saveModel();
      setStatus('模型已保存');
      await refresh(saved.source_id || selectedSourceId, saved.profile_id);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '保存模型失败');
    } finally {
      setBusy('');
    }
  }

  async function runModelTest(profileId?: string) {
    if (busy) return;
    setBusy('model-test');
    setStatus('正在保存并测试模型...');
    try {
      const model = profileId ? profiles.find((item) => item.profile_id === profileId) : await saveModel();
      if (!model) throw new Error('模型不存在');
      const test = await testModelProfile(model.profile_id);
      setStatus(test.ok || test.success ? `模型测试通过：${test.message || 'OK'}` : `模型测试失败：${test.message || '请检查配置'}`);
      await refresh(model.source_id || selectedSourceId, model.profile_id);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '测试模型失败');
    } finally {
      setBusy('');
    }
  }

  async function removeModel(profileId: string) {
    if (busy) return;
    setBusy('model-delete');
    try {
      await deleteModelProfile(profileId);
      setStatus('模型已删除');
      await refresh(selectedSourceId, '');
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '删除模型失败');
    } finally {
      setBusy('');
    }
  }

  async function removeSource() {
    if (!sourceDraft.source_id || busy) return;
    setBusy('source-delete');
    try {
      await deleteModelSource(sourceDraft.source_id);
      setStatus('提供商源已删除');
      await refresh('', '');
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '删除提供商源失败');
    } finally {
      setBusy('');
    }
  }

  async function setDefault(profile: ModelProfile) {
    if (busy) return;
    setBusy('default');
    try {
      const result = await updateModelProfileDefaults({ [profile.capability]: profile.profile_id });
      setDefaults(result.defaults || {});
      setStatus(`${capabilityLabels[profile.capability]}默认模型已更新`);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '更新默认模型失败');
    } finally {
      setBusy('');
    }
  }

  return (
    <section className="hy-route-page model-profiles-page">
      <header className="hy-page-header hy-stagger">
        <div>
          <span className="hy-eyebrow">Model Providers</span>
          <h2>模型提供商</h2>
          <p>先配置模型商源，再在源下面登记模型；Agent、图片识别和 TTS 都引用这里的模型。</p>
        </div>
        <button type="button" className="hy-btn hy-btn-ghost" onClick={() => navigateTo('settings')}>返回设置</button>
      </header>

      <div className="model-provider-tabs">
        {(['chat', 'vision', 'tts'] as ModelCapability[]).map((capability) => (
          <button
            key={capability}
            type="button"
            className={activeCapability === capability ? 'active' : ''}
            onClick={() => switchCapability(capability)}
          >
            {capabilityLabels[capability]}
          </button>
        ))}
      </div>

      {status ? <div className={/失败|错误|不能为空|不存在/.test(status) ? 'notice danger' : 'notice'}>{status}</div> : null}

      {loading ? (
        <section className="model-provider-empty">正在读取模型提供商源...</section>
      ) : (
        <div className="model-provider-layout">
          <aside className="model-source-panel">
            <div className="model-panel-title">
              <h3>提供商源 <span>{sources.length}</span></h3>
              <button type="button" className="hy-btn hy-btn-ghost" disabled={Boolean(busy)} onClick={createNewSource}>新增</button>
            </div>
            <div className="model-source-list">
              {sources.map((source) => {
                const preset = providerPreset(source.provider);
                return (
                  <button
                    key={source.source_id}
                    type="button"
                    className={selectedSourceId === source.source_id ? 'active' : ''}
                    onClick={() => selectSource(source)}
                  >
                    <span className="model-source-mark">{preset.mark}</span>
                    <strong>{source.name}</strong>
                    <small>{source.base_url || preset.label}</small>
                    <em className={`status-pill ${statusClass(source.status)}`}>{statusLabel(source.status)}</em>
                  </button>
                );
              })}
              {!sources.length ? <p className="muted">还没有提供商源。点击新增开始配置。</p> : null}
            </div>
          </aside>

          <section className="model-source-detail">
            {!selectedSourceId && !sourceDraft.name ? (
              <div className="model-provider-empty">
                <strong>请选择一个提供商源</strong>
                <span>或点击左侧新增，创建 OpenAI-compatible / MiniMax / OpenRouter / Ollama 等模型商源。</span>
              </div>
            ) : (
              <>
                <form className="model-source-form" onSubmit={onSaveSource}>
                  <div className="model-panel-title">
                    <h3>{sourceDraft.source_id ? '提供商源设置' : '新增提供商源'}</h3>
                    <span>{sourceDraft.source_id || '未保存'}</span>
                  </div>
                  <div className="model-provider-grid">
                    <label>
                      <span>提供商</span>
                      <select className="hy-select" value={sourceDraft.provider} disabled={Boolean(busy)} onChange={(event) => applyProvider(event.target.value)}>
                        {providerPresets.map((preset) => (
                          <option key={preset.id} value={preset.id}>{preset.label}</option>
                        ))}
                      </select>
                    </label>
                    <label>
                      <span>源名称</span>
                      <input className="hy-input" value={sourceDraft.name} disabled={Boolean(busy)} onChange={(event) => setSourceDraft({ ...sourceDraft, name: event.target.value })} placeholder="例如 minimax / OpenRouter 工作号" />
                    </label>
                    <label>
                      <span>Base URL</span>
                      <input className="hy-input" value={sourceDraft.base_url} disabled={Boolean(busy)} onChange={(event) => setSourceDraft({ ...sourceDraft, base_url: event.target.value })} placeholder={providerPreset(sourceDraft.provider).baseUrl || 'https://api.example.com/v1'} />
                    </label>
                    <label>
                      <span>API Key</span>
                      <input className="hy-input" type="password" value={sourceDraft.api_key} disabled={Boolean(busy)} onChange={(event) => setSourceDraft({ ...sourceDraft, api_key: event.target.value })} placeholder={selectedSource?.api_key_configured ? '已配置，留空不覆盖' : '仅保存在本机后端'} />
                    </label>
                  </div>
                  <label className="model-profile-toggle">
                    <input type="checkbox" checked={sourceDraft.enabled} disabled={Boolean(busy)} onChange={(event) => setSourceDraft({ ...sourceDraft, enabled: event.target.checked })} />
                    <span>启用这个提供商源</span>
                  </label>
                  <div className="agent-editor-actions">
                    <button type="submit" className="hy-btn hy-btn-ghost" disabled={Boolean(busy)}>{busy === 'source-save' ? '保存中...' : '保存源'}</button>
                    <button type="button" className="primary-action" disabled={Boolean(busy)} onClick={() => void runSourceTest()}>{busy === 'source-test' ? '测试中...' : '保存并测试源'}</button>
                    {sourceDraft.source_id ? <button type="button" className="hy-btn hy-btn-danger" disabled={Boolean(busy)} onClick={() => void removeSource()}>删除源</button> : null}
                  </div>
                </form>

                <section className="model-source-models">
                  <div className="model-panel-title">
                    <h3>{capabilityLabels[activeCapability]}模型</h3>
                    <span>{visibleModels.length} 个</span>
                  </div>
                  <form className="model-inline-form" onSubmit={onSaveModel}>
                    <input className="hy-input" value={modelDraft.model} disabled={Boolean(busy)} onChange={(event) => setModelDraft({ ...modelDraft, model: event.target.value })} placeholder="模型 ID，例如 gpt-4.1-mini" />
                    <input className="hy-input" value={modelDraft.name} disabled={Boolean(busy)} onChange={(event) => setModelDraft({ ...modelDraft, name: event.target.value })} placeholder="显示名称，可留空" />
                    <button type="submit" className="hy-btn hy-btn-ghost" disabled={Boolean(busy)}>{modelDraft.profile_id ? '保存模型' : '添加模型'}</button>
                    <button type="button" className="primary-action" disabled={Boolean(busy)} onClick={() => void runModelTest()}>{busy === 'model-test' ? '测试中...' : '保存并测试'}</button>
                  </form>

                  <div className="model-table">
                    {visibleModels.map((model) => (
                      <div className={selectedModelId === model.profile_id ? 'model-row active' : 'model-row'} key={model.profile_id}>
                        <button type="button" onClick={() => { setSelectedModelId(model.profile_id); setModelDraft(modelToDraft(model)); }}>
                          <strong>{model.name}</strong>
                          <span>{sourceDraft.name}/{model.model}</span>
                        </button>
                        <em className={`status-pill ${statusClass(model.status)}`}>{statusLabel(model.status)}</em>
                        {defaults[model.capability] === model.profile_id ? <small>默认</small> : null}
                        <button type="button" className="hy-btn hy-btn-ghost" disabled={Boolean(busy)} onClick={() => void setDefault(model)}>设为默认</button>
                        <button type="button" className="hy-btn hy-btn-ghost" disabled={Boolean(busy)} onClick={() => void runModelTest(model.profile_id)}>测试</button>
                        <button type="button" className="hy-btn hy-btn-danger" disabled={Boolean(busy)} onClick={() => void removeModel(model.profile_id)}>删除</button>
                      </div>
                    ))}
                    {!visibleModels.length ? (
                      <div className="model-provider-empty compact">
                        <strong>还没有{capabilityLabels[activeCapability]}模型</strong>
                        <span>在上方输入模型 ID 后添加。默认模型会被 Agent Studio 和 Workflow Studio 引用。</span>
                      </div>
                    ) : null}
                  </div>
                </section>
              </>
            )}
          </section>
        </div>
      )}
    </section>
  );
}

