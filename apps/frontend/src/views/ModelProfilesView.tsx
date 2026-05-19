import { useEffect, useMemo, useState, type FormEvent } from 'react';

import { ProviderBrandIcon } from '../components/ProviderBrandIcon';
import { UiIcon } from '../components/UiIcon';
import {
  createModelProfile,
  createModelSource,
  deleteModelProfile,
  deleteModelSource,
  fetchModelSourceModels,
  listModelProfiles,
  syncHermesProfileDefault,
  testAndSaveModelProfile,
  testModelProfile,
  updateModelProfile,
  updateModelProfileDefaults,
  updateModelSource,
  type ModelCapability,
  type ModelProfile,
  type ModelProfileDefaults,
  type ModelSource,
  type RemoteModelInfo,
} from '../lib/modelProfiles';

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

type ModelSourceView = ModelSource & {
  provider_label?: string;
};

type ModelProfileView = ModelProfile;

type ProviderPreset = {
  id: string;
  label: string;
  baseUrl: string;
  mark: string;
  note: string;
  hermesProvider?: string;
  modelHints?: string[];
};

type ModelCatalogGroup = {
  key: string;
  label: string;
  iconProvider?: string;
  models: RemoteModelInfo[];
};

const providerPresets: ProviderPreset[] = [
  {
    id: 'openrouter',
    label: 'OpenRouter',
    baseUrl: 'https://openrouter.ai/api/v1',
    mark: 'OR',
    hermesProvider: 'openrouter',
    note: 'OpenRouter 是一个 Hermes provider；下方模型供应商只作为 OpenRouter 模型分组展示。',
    modelHints: [],
  },
  {
    id: 'xiaomi',
    label: 'Xiaomi MiMo',
    baseUrl: 'https://token-plan-cn.xiaomimimo.com/v1',
    mark: 'Mi',
    hermesProvider: 'xiaomi',
    note: 'Hermes 原生 Xiaomi provider。旧的 xiaomi_mimo 源会自动映射到 xiaomi。',
    modelHints: ['mimo-v2.5-pro', 'mimo-v2.5'],
  },
  {
    id: 'deepseek',
    label: 'DeepSeek',
    baseUrl: 'https://api.deepseek.com/v1',
    mark: 'DS',
    hermesProvider: 'deepseek',
    note: 'Hermes 原生 DeepSeek provider。',
    modelHints: ['deepseek-chat', 'deepseek-reasoner'],
  },
  {
    id: 'gemini',
    label: 'Google Gemini',
    baseUrl: 'https://generativelanguage.googleapis.com/v1beta/openai',
    mark: 'G',
    hermesProvider: 'gemini',
    note: 'Hermes 原生 Gemini provider；这里使用 Gemini 的 OpenAI-compatible 端点做模型获取与测试。',
    modelHints: ['gemini-2.5-flash', 'gemini-2.5-pro'],
  },
  {
    id: 'alibaba',
    label: '阿里云百炼 / Qwen',
    baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    mark: 'Q',
    hermesProvider: 'alibaba',
    note: 'Hermes Alibaba provider；用于通义千问 / DashScope 兼容端点。',
    modelHints: ['qwen-plus', 'qwen-turbo', 'qwen-max'],
  },
  {
    id: 'kimi-coding',
    label: 'Moonshot / Kimi',
    baseUrl: 'https://api.moonshot.ai/v1',
    mark: 'K',
    hermesProvider: 'kimi-coding',
    note: 'Hermes Kimi Coding provider；Moonshot 旧源会自动映射到 kimi-coding。',
    modelHints: ['kimi-k2.5', 'kimi-k2-thinking'],
  },
  {
    id: 'zai',
    label: '智谱 GLM / Z.AI',
    baseUrl: 'https://open.bigmodel.cn/api/paas/v4',
    mark: 'GLM',
    hermesProvider: 'zai',
    note: 'Hermes Z.AI provider；智谱旧源会自动映射到 zai。',
    modelHints: ['glm-4.5-flash', 'glm-4-plus'],
  },
  {
    id: 'minimax',
    label: 'MiniMax',
    baseUrl: 'https://api.minimax.io/v1',
    mark: 'MM',
    hermesProvider: 'minimax',
    note: 'Hermes 原生 MiniMax provider。',
    modelHints: ['MiniMax-M2.7', 'MiniMax-M2.5'],
  },
  {
    id: 'stepfun',
    label: '阶跃星辰 StepFun',
    baseUrl: 'https://api.stepfun.com/v1',
    mark: 'S',
    hermesProvider: 'stepfun',
    note: 'Hermes 原生 StepFun provider。',
    modelHints: ['step-3.5-flash', 'step-2-mini'],
  },
  {
    id: 'nvidia',
    label: 'NVIDIA NIM',
    baseUrl: 'https://integrate.api.nvidia.com/v1',
    mark: 'NV',
    hermesProvider: 'nvidia',
    note: 'Hermes 原生 NVIDIA provider。',
    modelHints: ['nvidia/nemotron-3-super-120b-a12b'],
  },
  {
    id: 'xai',
    label: 'xAI',
    baseUrl: 'https://api.x.ai/v1',
    mark: 'x',
    hermesProvider: 'xai',
    note: 'Hermes 原生 xAI provider。',
    modelHints: ['grok-4', 'grok-code-fast-1'],
  },
  {
    id: 'huggingface',
    label: 'Hugging Face',
    baseUrl: 'https://router.huggingface.co/v1',
    mark: 'HF',
    hermesProvider: 'huggingface',
    note: 'Hermes 原生 Hugging Face provider。',
    modelHints: ['Qwen/Qwen3.5-35B-A3B'],
  },
  {
    id: 'lmstudio',
    label: 'LM Studio',
    baseUrl: 'http://127.0.0.1:1234/v1',
    mark: 'LM',
    hermesProvider: 'lmstudio',
    note: 'Hermes LM Studio provider，本地服务通常可使用占位 API Key。',
    modelHints: ['local-model'],
  },
  {
    id: 'openai',
    label: 'OpenAI',
    baseUrl: 'https://api.openai.com/v1',
    mark: 'AI',
    hermesProvider: 'openai',
    note: 'Hermes OpenAI provider。',
    modelHints: ['gpt-4.1-mini', 'gpt-4o-mini'],
  },
  {
    id: 'openai_compatible',
    label: '自定义 OpenAI-Compatible',
    baseUrl: 'https://api.example.com/v1',
    mark: 'API',
    hermesProvider: 'custom',
    note: '非 Hermes 原生 provider 会写入 Hermes custom；同一时间只能作为一个 custom 主模型使用。',
    modelHints: [],
  },
];

const ttsProviderPresets: ProviderPreset[] = [
  {
    id: 'gpt_sovits',
    label: 'GPT-SoVITS',
    baseUrl: 'http://127.0.0.1:9880',
    mark: 'GSV',
    note: '本地 GPT-SoVITS 服务，语音、参考音频和权重仍在 GPT-SoVITS 设置页管理。',
    modelHints: ['default-voice'],
  },
  {
    id: 'http_tts',
    label: 'HTTP TTS Endpoint',
    baseUrl: 'http://127.0.0.1:9880/tts',
    mark: 'HTTP',
    note: '通用 HTTP 语音合成服务，用于登记一个可复用的语音端点或 voice id。',
    modelHints: ['default'],
  },
  {
    id: 'command_tts',
    label: 'Command TTS',
    baseUrl: '',
    mark: 'CMD',
    note: '本地命令式 TTS 适配入口；这里登记 profile 名称，具体命令在语音设置链路执行。',
    modelHints: ['local-command'],
  },
];

const allProviderPresets = [...providerPresets, ...ttsProviderPresets];

const capabilityLabels: Record<ModelCapability, string> = {
  chat: '对话',
  vision: '图片转述',
  tts: '文字转语音',
};

const legacyTextProviderIds = new Set([
  '302ai',
  'aihubmix',
  'azure_openai',
  'baichuan',
  'baidu_qianfan',
  'compshare',
  'fastgpt',
  'fireworks',
  'google_gemini',
  'groq',
  'lm_studio',
  'mistral',
  'modelscope',
  'moonshot',
  'ollama',
  'perplexity',
  'ppio',
  'qwen_dashscope',
  'sensenova',
  'siliconflow',
  'tencent_hunyuan',
  'together',
  'tokenpony',
  'volcengine_doubao',
  'xiaomi_mimo',
  'zhipu',
]);

const catalogProviderMeta: Record<string, { label: string; iconProvider?: string }> = {
  aion_labs: { label: 'Aion Labs' },
  amazon: { label: 'AWS / Amazon', iconProvider: 'aws' },
  anthropic: { label: 'Anthropic', iconProvider: 'anthropic' },
  arcee_ai: { label: 'Arcee AI', iconProvider: 'arcee_ai' },
  baidu: { label: '百度千帆', iconProvider: 'baidu_qianfan' },
  bytedance_seed: { label: '字节 Seed / 豆包', iconProvider: 'bytedance_seed' },
  cohere: { label: 'Cohere', iconProvider: 'cohere' },
  deepseek: { label: 'DeepSeek', iconProvider: 'deepseek' },
  google: { label: 'Google / Gemini', iconProvider: 'google_gemini' },
  ibm_granite: { label: 'IBM Granite', iconProvider: 'ibm_granite' },
  inclusionai: { label: 'inclusionAI' },
  liquid: { label: 'Liquid', iconProvider: 'liquid' },
  meta_llama: { label: 'Meta Llama', iconProvider: 'meta_llama' },
  microsoft: { label: 'Microsoft', iconProvider: 'microsoft' },
  minimax: { label: 'MiniMax', iconProvider: 'minimax' },
  mistralai: { label: 'Mistral AI', iconProvider: 'mistral' },
  moonshotai: { label: 'Moonshot / Kimi', iconProvider: 'moonshot' },
  nousresearch: { label: 'Nous Research', iconProvider: 'nousresearch' },
  nvidia: { label: 'NVIDIA', iconProvider: 'nvidia' },
  openai: { label: 'OpenAI', iconProvider: 'openai' },
  openrouter: { label: 'OpenRouter', iconProvider: 'openrouter' },
  perplexity: { label: 'Perplexity', iconProvider: 'perplexity' },
  poolside: { label: 'Poolside' },
  qwen: { label: 'Qwen / 通义', iconProvider: 'qwen' },
  x_ai: { label: 'xAI', iconProvider: 'xai' },
  xiaomi: { label: 'Xiaomi MiMo', iconProvider: 'xiaomi_mimo' },
  z_ai: { label: 'Z.AI / 智谱', iconProvider: 'z_ai' },
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

function hermesProviderLabel(provider?: string): string {
  return provider ? `Hermes: ${provider}` : '不可用于 Hermes';
}

function runtimeProviderLabel(provider?: string): string {
  return provider ? hermesProviderLabel(provider) : 'Agent 直连';
}

function runtimePillClass(provider?: string): string {
  return provider ? 'model-key-pill model-runtime-pill is-hermes' : 'model-key-pill model-runtime-pill is-direct';
}

function presetRuntimePillClass(provider?: string): string {
  return provider ? 'model-preset-runtime model-runtime-pill is-hermes' : 'model-preset-runtime model-runtime-pill is-direct';
}

function sourceHermesProvider(source: ModelSource): string {
  return source.hermes_provider || source.runtime?.hermes_provider || '';
}

function profileHermesProvider(profile: ModelProfile): string {
  return profile.hermes_provider || profile.runtime?.hermes_provider || '';
}

function profileSelectableForHermes(profile: ModelProfile): boolean {
  return profile.status === 'available'
    && profile.enabled !== false
    && profile.can_use_as_hermes !== false
    && Boolean(profileHermesProvider(profile));
}

function providerPresetsForCapability(capability: ModelCapability): ProviderPreset[] {
  return capability === 'tts' ? ttsProviderPresets : providerPresets;
}

function providerPreset(provider: string): ProviderPreset {
  return allProviderPresets.find((item) => item.id === provider) || {
    id: provider || 'openai_compatible',
    label: provider || 'OpenAI Compatible',
    baseUrl: '',
    mark: 'AI',
    note: '自定义模型提供商源。',
  };
}

function defaultSourceDraft(capability: ModelCapability): SourceDraft {
  const preset = providerPresetsForCapability(capability)[0] || providerPresets[0];
  return {
    name: '',
    provider: preset.id,
    base_url: preset.baseUrl,
    api_key: '',
    enabled: true,
  };
}

function sourceMatchesCapability(source: ModelSourceView, capability: ModelCapability): boolean {
  const providerIds = new Set(providerPresetsForCapability(capability).map((preset) => preset.id));
  if (capability === 'tts') {
    return providerIds.has(source.provider) || Boolean(source.models?.some((model) => model.capability === 'tts'));
  }
  if (legacyTextProviderIds.has(source.provider)) return true;
  if (providerIds.has(source.provider)) return true;
  return Boolean(source.models?.some((model) => model.capability === capability));
}

function sourcesForCapability(sources: ModelSourceView[], capability: ModelCapability): ModelSourceView[] {
  return sources.filter((source) => sourceMatchesCapability(source, capability));
}

function sourceHasCapabilityModel(source: ModelSource, capability: ModelCapability): boolean {
  return Boolean(source.models?.some((model) => model.capability === capability));
}

function providerIconClass(provider: string): string {
  const safe = (provider || 'openai_compatible').toLowerCase().replace(/[^a-z0-9]+/g, '-');
  return `provider-${safe}`;
}

function normalizeCatalogProviderKey(provider?: string): string {
  return (provider || 'openrouter').trim().toLowerCase().replace(/^~/, '').replace(/[^a-z0-9]+/g, '_') || 'openrouter';
}

function catalogProviderKey(model: RemoteModelInfo): string {
  const fromId = model.id.includes('/') ? model.id.split('/', 1)[0] : '';
  return normalizeCatalogProviderKey(model.provider_key || model.owned_by || fromId);
}

function titleCatalogProvider(key: string): string {
  return key
    .split('_')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function groupCatalogModels(models: RemoteModelInfo[]): ModelCatalogGroup[] {
  const groups = new Map<string, ModelCatalogGroup>();
  for (const model of models) {
    const key = catalogProviderKey(model);
    const meta = catalogProviderMeta[key] || { label: titleCatalogProvider(key) };
    const group = groups.get(key) || {
      key,
      label: meta.label,
      iconProvider: meta.iconProvider,
      models: [],
    };
    group.models.push(model);
    groups.set(key, group);
  }
  return Array.from(groups.values()).sort((left, right) => right.models.length - left.models.length || left.label.localeCompare(right.label));
}

function formatContextLength(contextLength?: number): string {
  if (!contextLength) return '';
  if (contextLength >= 1_000_000) return `${Math.round(contextLength / 1_000_000)}M ctx`;
  if (contextLength >= 1_000) return `${Math.round(contextLength / 1_000)}K ctx`;
  return `${contextLength} ctx`;
}

function catalogPriceBadge(pricing?: RemoteModelInfo['pricing']): string {
  if (!pricing) return '';
  const prompt = Number(pricing.prompt || 0);
  const completion = Number(pricing.completion || 0);
  if (!Number.isFinite(prompt) || !Number.isFinite(completion) || (prompt <= 0 && completion <= 0)) return '';
  const promptPerMillion = prompt * 1_000_000;
  const completionPerMillion = completion * 1_000_000;
  const compact = (value: number) => value >= 1 ? value.toFixed(2).replace(/\.?0+$/, '') : value.toPrecision(2);
  return `$${compact(promptPerMillion)}/${compact(completionPerMillion)}M`;
}

function catalogModelBadges(model: RemoteModelInfo, capability: ModelCapability): string[] {
  const badges: string[] = [];
  const inputModalities = new Set((model.input_modalities || []).map((item) => item.toLowerCase()));
  const supportedParameters = new Set((model.supported_parameters || []).map((item) => item.toLowerCase()));
  const context = formatContextLength(model.context_length);
  if (model.is_free || model.id.endsWith(':free')) badges.push('免费');
  else {
    const price = catalogPriceBadge(model.pricing);
    if (price) badges.push(price);
  }
  const supportsVision = modelSupportsCapability(model, 'vision');
  if (capability === 'vision') badges.push(supportsVision ? '声明视觉' : '未声明视觉');
  else if (supportsVision || inputModalities.has('image')) badges.push('视觉');
  if (inputModalities.has('file')) badges.push('文件');
  if (inputModalities.has('audio')) badges.push('音频');
  if (inputModalities.has('video')) badges.push('视频');
  if (supportedParameters.has('tools')) badges.push('工具');
  if (supportedParameters.has('structured_outputs') || supportedParameters.has('response_format')) badges.push('结构化');
  if (context) badges.push(context);
  return badges.slice(0, 5);
}

function modelSupportsCapability(model: RemoteModelInfo, capability: ModelCapability): boolean {
  const input = (model.input_modalities || []).map((item) => item.toLowerCase());
  const output = (model.output_modalities || []).map((item) => item.toLowerCase());
  const modality = (model.modality || '').toLowerCase();
  if (capability === 'vision') {
    return input.includes('image') || /\bimage\b|vision|multimodal/.test(modality);
  }
  if (capability === 'tts') {
    return output.includes('audio') || /\baudio\b|speech|tts/.test(modality);
  }
  return !input.length || input.includes('text') || modality.includes('text');
}

function capabilityCatalogModels(models: RemoteModelInfo[], capability: ModelCapability): RemoteModelInfo[] {
  if (capability === 'tts') return [];
  if (capability === 'vision') return models;
  return models.filter((model) => modelSupportsCapability(model, capability));
}

function capabilityEmptyModelHint(capability: ModelCapability): string {
  if (capability === 'vision') return '请先获取远端模型列表，再选择模型进行真实图片测试；通过后才会保存为可用视觉模型。';
  if (capability === 'tts') return '选择 TTS 提供商后，在这里登记 voice / profile id；实际连接测试走语音设置链路。';
  return '获取远端模型列表后选择模型并测试保存；通过后会出现在设置页和 Agent Studio。';
}

function sourceToDraft(source: ModelSourceView): SourceDraft {
  return {
    source_id: source.source_id,
    name: source.name,
    provider: source.provider || 'openai_compatible',
    base_url: source.base_url || '',
    api_key: '',
    enabled: source.enabled !== false,
  };
}

function modelToDraft(model: ModelProfileView): ModelDraft {
  return {
    profile_id: model.profile_id,
    name: model.name,
    model: model.model || '',
    capability: model.capability,
    enabled: model.profile_enabled ?? (model.enabled !== false),
  };
}

async function loadModelProfileData(): Promise<{
  sources: ModelSourceView[];
  profiles: ModelProfileView[];
  defaults: ModelProfileDefaults;
}> {
  const profilePayload = await listModelProfiles();
  const registrySources = (profilePayload.sources || []) as ModelSourceView[];
  const registryProfiles = (profilePayload.profiles || []) as ModelProfileView[];
  return {
    sources: registrySources,
    profiles: registryProfiles,
    defaults: profilePayload.defaults || {},
  };
}

function defaultModelName(source: SourceDraft, capability: ModelCapability): string {
  const preset = providerPreset(source.provider);
  if (capability === 'tts') return preset.modelHints?.[0] || '';
  if (capability === 'vision') {
    if (preset.id === 'openai' || preset.id === 'openai_compatible') return 'gpt-4.1-mini';
    if (preset.id === 'gemini' || preset.id === 'google_gemini') return 'gemini-2.5-flash';
    if (preset.id === 'minimax') return 'MiniMax-M2.7';
    if (preset.id === 'xiaomi') return 'mimo-v2.5';
    return '';
  }
  if (preset.modelHints?.length) return preset.modelHints[0];
  if (preset.id === 'openai' || preset.id === 'openai_compatible') return 'gpt-4.1-mini';
  if (preset.id === 'deepseek') return 'deepseek-chat';
  if (preset.id === 'minimax') return 'MiniMax-M2.7';
  return '';
}

export function ModelProfilesView() {
  const [sources, setSources] = useState<ModelSourceView[]>([]);
  const [profiles, setProfiles] = useState<ModelProfileView[]>([]);
  const [defaults, setDefaults] = useState<ModelProfileDefaults>({});
  const [selectedSourceId, setSelectedSourceId] = useState('');
  const [selectedModelId, setSelectedModelId] = useState('');
  const [activeCapability, setActiveCapability] = useState<ModelCapability>('chat');
  const [sourceDraft, setSourceDraft] = useState<SourceDraft>(emptySourceDraft);
  const [modelDraft, setModelDraft] = useState<ModelDraft>(emptyModelDraft);
  const [modelCatalog, setModelCatalog] = useState<RemoteModelInfo[]>([]);
  const [modelCatalogQuery, setModelCatalogQuery] = useState('');
  const [providerMenuOpen, setProviderMenuOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [status, setStatus] = useState('');

  const selectedSource = useMemo(
    () => sources.find((source) => source.source_id === selectedSourceId) || null,
    [selectedSourceId, sources],
  );
  const selectedModel = useMemo(
    () => profiles.find((profile) => profile.profile_id === selectedModelId) || null,
    [profiles, selectedModelId],
  );
  const capabilitySources = useMemo(
    () => sourcesForCapability(sources, activeCapability),
    [activeCapability, sources],
  );
  const sourceModels = useMemo(
    () => profiles.filter((profile) => profile.source_id === selectedSourceId),
    [profiles, selectedSourceId],
  );
  const visibleModels = useMemo(
    () => sourceModels.filter((profile) => profile.capability === activeCapability),
    [activeCapability, sourceModels],
  );
  const visibleCatalogModels = useMemo(() => {
    const query = modelCatalogQuery.trim().toLowerCase();
    const models = capabilityCatalogModels(modelCatalog, activeCapability);
    if (!query) return models;
    return models
      .filter((model) => `${model.id} ${model.name || ''} ${model.owned_by || ''} ${model.provider_key || ''}`.toLowerCase().includes(query));
  }, [activeCapability, modelCatalog, modelCatalogQuery]);
  const modelCatalogGroups = useMemo(() => groupCatalogModels(visibleCatalogModels), [visibleCatalogModels]);

  async function refresh(nextSourceId = selectedSourceId, nextModelId = selectedModelId, capability = activeCapability) {
    const payload = await loadModelProfileData();
    const nextSources = payload.sources;
    const nextProfiles = payload.profiles;
    setSources(nextSources);
    setProfiles(nextProfiles);
    setDefaults(payload.defaults);

    const nextCapabilitySources = sourcesForCapability(nextSources, capability);
    const source = nextCapabilitySources.find((item) => item.source_id === nextSourceId) || nextCapabilitySources[0] || null;
    if (source) {
      setSelectedSourceId(source.source_id);
      setSourceDraft(sourceToDraft(source));
      const sourceProfile = nextProfiles.find((item) => item.profile_id === nextModelId && item.source_id === source.source_id)
        || nextProfiles.find((item) => item.source_id === source.source_id && item.capability === capability)
        || null;
      if (sourceProfile) {
        setSelectedModelId(sourceProfile.profile_id);
        setModelDraft(modelToDraft(sourceProfile));
      } else {
        setSelectedModelId('');
        setModelDraft({ ...emptyModelDraft, capability, model: defaultModelName(sourceToDraft(source), capability) });
      }
    } else {
      setSelectedSourceId('');
      setSelectedModelId('');
      const draft = defaultSourceDraft(capability);
      setSourceDraft(draft);
      setModelDraft({ ...emptyModelDraft, capability, model: defaultModelName(draft, capability) });
    }
  }

  useEffect(() => {
    let disposed = false;
    loadModelProfileData()
      .then((payload) => {
        if (disposed) return;
        const nextSources = payload.sources;
        const nextProfiles = payload.profiles;
        setSources(nextSources);
        setProfiles(nextProfiles);
        setDefaults(payload.defaults);
        const nextCapabilitySources = sourcesForCapability(nextSources, activeCapability);
        if (nextCapabilitySources.length) {
          const source = nextCapabilitySources[0];
          setSelectedSourceId(source.source_id);
          setSourceDraft(sourceToDraft(source));
          const firstModel = nextProfiles.find((profile) => profile.source_id === source.source_id && profile.capability === activeCapability);
          if (firstModel) {
            setSelectedModelId(firstModel.profile_id);
            setModelDraft(modelToDraft(firstModel));
          } else {
            setModelDraft({ ...emptyModelDraft, capability: activeCapability, model: defaultModelName(sourceToDraft(source), activeCapability) });
          }
        } else {
          const draft = defaultSourceDraft(activeCapability);
          setSourceDraft(draft);
          setModelDraft({ ...emptyModelDraft, capability: activeCapability, model: defaultModelName(draft, activeCapability) });
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

  function cleanDraftValue(value?: string): string {
    return (value || '').trim();
  }

  function hasUnsavedDraftChanges(): boolean {
    const sourceBaseline = selectedSource ? sourceToDraft(selectedSource) : defaultSourceDraft(activeCapability);
    const sourceDirty = cleanDraftValue(sourceDraft.name) !== cleanDraftValue(sourceBaseline.name)
      || sourceDraft.provider !== sourceBaseline.provider
      || cleanDraftValue(sourceDraft.base_url) !== cleanDraftValue(sourceBaseline.base_url)
      || sourceDraft.enabled !== sourceBaseline.enabled
      || Boolean(cleanDraftValue(sourceDraft.api_key));

    const modelBaseline = selectedModel
      ? modelToDraft(selectedModel)
      : { ...emptyModelDraft, capability: activeCapability, model: defaultModelName(sourceDraft, activeCapability) };
    const modelDirty = cleanDraftValue(modelDraft.name) !== cleanDraftValue(modelBaseline.name)
      || cleanDraftValue(modelDraft.model) !== cleanDraftValue(modelBaseline.model)
      || modelDraft.capability !== modelBaseline.capability
      || modelDraft.enabled !== modelBaseline.enabled;

    return sourceDirty || modelDirty;
  }

  function confirmDiscardDraftChanges(): boolean {
    if (!hasUnsavedDraftChanges()) return true;
    return window.confirm('当前提供商源或模型有未保存更改，是否放弃这些更改？');
  }

  function selectSource(source: ModelSource) {
    if (busy) return;
    if (source.source_id !== selectedSourceId && !confirmDiscardDraftChanges()) return;
    setSelectedSourceId(source.source_id);
    setSourceDraft(sourceToDraft(source));
    const firstModel = profiles.find((profile) => profile.source_id === source.source_id && profile.capability === activeCapability);
    setSelectedModelId(firstModel?.profile_id || '');
    setModelDraft(firstModel ? modelToDraft(firstModel) : { ...emptyModelDraft, capability: activeCapability, model: defaultModelName(sourceToDraft(source), activeCapability) });
    setModelCatalog([]);
    setModelCatalogQuery('');
    setProviderMenuOpen(false);
    setStatus('');
  }

  function createNewSource() {
    if (busy) return;
    if (!confirmDiscardDraftChanges()) return;
    const draft = defaultSourceDraft(activeCapability);
    setSelectedSourceId('');
    setSelectedModelId('');
    setSourceDraft(draft);
    setModelDraft({ ...emptyModelDraft, capability: activeCapability, model: defaultModelName(draft, activeCapability) });
    setModelCatalog([]);
    setModelCatalogQuery('');
    setProviderMenuOpen(false);
    setStatus('');
  }

  function returnToPresetList() {
    createNewSource();
  }

  function sourceDraftFromPreset(preset: ProviderPreset): SourceDraft {
    return {
      name: preset.id,
      provider: preset.id,
      base_url: preset.baseUrl,
      api_key: '',
      enabled: true,
    };
  }

  function startPresetSource(preset: ProviderPreset) {
    if (busy) return;
    const nextDraft = sourceDraftFromPreset(preset);
    setSelectedSourceId('');
    setSelectedModelId('');
    setSourceDraft(nextDraft);
    setModelDraft({ ...emptyModelDraft, capability: activeCapability, model: defaultModelName(nextDraft, activeCapability) });
    setModelCatalog([]);
    setModelCatalogQuery('');
    setProviderMenuOpen(false);
    setStatus('');
  }

  function switchCapability(capability: ModelCapability) {
    setActiveCapability(capability);
    const nextCapabilitySources = sourcesForCapability(sources, capability);
    const source = nextCapabilitySources.find((item) => item.source_id === selectedSourceId) || nextCapabilitySources[0] || null;
    if (!source) {
      const draft = defaultSourceDraft(capability);
      setSelectedSourceId('');
      setSelectedModelId('');
      setSourceDraft(draft);
      setModelDraft({ ...emptyModelDraft, capability, model: defaultModelName(draft, capability) });
      setModelCatalog([]);
      setModelCatalogQuery('');
      setProviderMenuOpen(false);
      return;
    }
    setSelectedSourceId(source.source_id);
    setSourceDraft(sourceToDraft(source));
    const firstModel = profiles.find((profile) => profile.source_id === source.source_id && profile.capability === capability);
    setSelectedModelId(firstModel?.profile_id || '');
    setModelDraft(firstModel ? modelToDraft(firstModel) : { ...emptyModelDraft, capability, model: defaultModelName(sourceToDraft(source), capability) });
    setModelCatalog([]);
    setModelCatalogQuery('');
    setProviderMenuOpen(false);
  }

  function applyProvider(provider: string) {
    const preset = providerPreset(provider);
    const nextDraft = {
      ...sourceDraft,
      provider,
      name: sourceDraft.name || preset.id,
      base_url: preset.baseUrl || sourceDraft.base_url,
    };
    setSourceDraft(nextDraft);
    setModelDraft((current) => current.profile_id || current.model
      ? current
      : { ...current, model: defaultModelName(nextDraft, current.capability) });
    setModelCatalog([]);
    setModelCatalogQuery('');
    setProviderMenuOpen(false);
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

  async function fetchModelsForSource() {
    if (busy) return;
    if (activeCapability === 'tts') {
      setStatus('TTS 提供商使用独立语音数据源，不从 OpenRouter 模型列表获取。');
      return;
    }
    setBusy('models-fetch');
    setStatus('正在保存源并获取模型列表...');
    try {
      const saved = await saveSource();
      if (saved.enabled === false) {
        setModelCatalog([]);
        setModelCatalogQuery('');
        setStatus('提供商源已暂停，状态已保存；恢复使用后才能获取模型列表或测试模型。');
        await refresh(saved.source_id, selectedModelId, activeCapability);
        return;
      }
      const result = await fetchModelSourceModels(saved.source_id);
      const models = result.models || [];
      setModelCatalog(models);
      setModelCatalogQuery('');
      const usableCount = activeCapability === 'vision'
        ? models.filter((model) => modelSupportsCapability(model, 'vision')).length
        : capabilityCatalogModels(models, activeCapability).length;
      const suffix = activeCapability === 'vision' ? ' 个远端声明视觉能力的模型' : ' 个可用模型';
      setStatus(models.length ? `已获取 ${models.length} 个模型，其中 ${usableCount}${suffix}；请选择模型后测试保存。` : '已连接源，但没有读取到模型列表');
      await refresh(saved.source_id, selectedModelId, activeCapability);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '获取模型列表失败');
    } finally {
      setBusy('');
    }
  }

  function applyCatalogModel(model: RemoteModelInfo) {
    setModelDraft((current) => ({
      ...current,
      model: model.id,
      name: `${sourceDraft.name || providerPreset(sourceDraft.provider).label}/${model.id}`,
    }));
  }

  async function saveModel(): Promise<ModelProfile> {
    const source = sourceDraft.source_id ? selectedSource : await saveSource();
    const sourceId = source?.source_id || sourceDraft.source_id || '';
    if (!sourceId) throw new Error('请先保存提供商源');
    if (!modelDraft.model.trim()) throw new Error('模型名称不能为空');
    const modelName = modelDraft.model.trim();
    const catalogMatch = modelCatalog.find((model) => model.id === modelName);
    const payload = {
      source_id: sourceId,
      name: modelDraft.name.trim() || `${sourceDraft.name}/${modelName}`,
      capability: modelDraft.capability,
      model: modelName,
      enabled: modelDraft.enabled,
      options: catalogMatch ? { remote_model: catalogMatch } : {},
    };
    if (modelDraft.profile_id) return updateModelProfile(modelDraft.profile_id, payload);
    return createModelProfile(payload);
  }

  async function testAndSaveCurrentModel(): Promise<{ ok?: boolean; success?: boolean; message?: string; profile?: ModelProfile; source?: ModelSource }> {
    const source = sourceDraft.source_id ? selectedSource : await saveSource();
    const sourceId = source?.source_id || sourceDraft.source_id || '';
    if (!sourceId) throw new Error('请先保存提供商源');
    if (sourceDraft.enabled === false || source?.enabled === false) throw new Error('提供商源已暂停，恢复使用后才能测试模型。');
    const modelName = modelDraft.model.trim();
    if (!modelName) throw new Error('模型名称不能为空');
    const catalogMatch = modelCatalog.find((model) => model.id === modelName);
    return testAndSaveModelProfile(sourceId, {
      ...(modelDraft.profile_id ? { profile_id: modelDraft.profile_id } : {}),
      name: modelDraft.name.trim() || `${sourceDraft.name}/${modelName}`,
      capability: modelDraft.capability,
      model: modelName,
      enabled: modelDraft.enabled,
      options: catalogMatch ? { remote_model: catalogMatch } : {},
    });
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
    if (sourceDraft.enabled === false) {
      setStatus('提供商源已暂停，恢复使用后才能测试模型。');
      return;
    }
    setBusy('model-test');
    setStatus(profileId ? '正在重新测试模型...' : '正在测试连接并保存模型...');
    try {
      if (profileId) {
        const model = profiles.find((item) => item.profile_id === profileId);
        if (!model) throw new Error('模型不存在');
        const test = await testModelProfile(model.profile_id);
        setStatus(test.ok || test.success ? `模型测试通过：${test.message || 'OK'}` : `模型测试失败：${test.message || '请检查配置'}`);
        await refresh(model.source_id || selectedSourceId, model.profile_id);
        return;
      }
      const test = await testAndSaveCurrentModel();
      const savedProfile = test.profile;
      setStatus(test.ok || test.success ? `模型测试通过并已保存：${test.message || 'OK'}` : `模型测试失败，未保存为可用模型：${test.message || '请检查配置'}`);
      await refresh(savedProfile?.source_id || test.source?.source_id || selectedSourceId || sourceDraft.source_id, savedProfile?.profile_id || selectedModelId);
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
    if (profile.status !== 'available') {
      setStatus('只有通过连接测试的模型才能设为默认。');
      return;
    }
    if (profile.enabled === false) {
      setStatus('提供商源或模型已暂停，不能设为默认。');
      return;
    }
    if (!profileSelectableForHermes(profile)) {
      setStatus('这个 Profile 不能映射到 Hermes 支持的 Provider，不能设为默认。');
      return;
    }
    setBusy('default');
    try {
      if (profile.capability === 'chat' || profile.capability === 'vision') {
        const sync = await syncHermesProfileDefault(profile.capability, profile.profile_id);
        if (sync.ok === false) throw new Error(sync.error || sync.message || '同步 Hermes 配置失败');
      }
      const result = await updateModelProfileDefaults({ [profile.capability]: profile.profile_id });
      setDefaults(result.defaults || {});
      setStatus(`${capabilityLabels[profile.capability]}默认模型已更新${profile.capability === 'tts' ? '' : '，并已同步到 Hermes 配置'}`);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '更新默认模型失败');
    } finally {
      setBusy('');
    }
  }

  const sourceCountLabel = capabilitySources.length ? `${capabilitySources.length}` : '0';
  const activeProviderPresets = providerPresetsForCapability(activeCapability);
  const sourceFormHelp = activeCapability === 'tts'
    ? 'TTS 使用语音服务专用来源；这里登记 provider、endpoint 和 voice/profile 名称，不复用 OpenRouter 模型目录。'
    : activeCapability === 'vision'
      ? '图片识别只应登记支持 image 输入的多模态模型；获取远端列表后会自动过滤。'
      : '默认主模型只使用 Hermes 可执行 provider；Agent Studio 可选择所有已测试通过的 Profile。OpenRouter 里的厂商是动态模型分组，不会被写成 Hermes provider。';
  const sourceDraftRuntimeProvider = selectedSource
    ? sourceHermesProvider(selectedSource)
    : (providerPreset(sourceDraft.provider).hermesProvider || sourceDraft.provider);

  return (
    <section className="hy-route-page model-profiles-page">
      <header className="hy-page-header hy-stagger">
        <div>
          <span className="hy-eyebrow">Model Providers</span>
          <h2>模型提供商</h2>
          <p>先配置模型服务商源，再在源下面登记模型；所有模型都来自服务商，不再生成本地主模型快照。</p>
        </div>
      </header>

      <div className="model-provider-tabs">
        {(['chat', 'vision', 'tts'] as ModelCapability[]).map((capability) => (
          <button
            key={capability}
            type="button"
            className={activeCapability === capability ? 'active' : ''}
            onClick={() => switchCapability(capability)}
            aria-pressed={activeCapability === capability}
          >
            {capabilityLabels[capability]}
          </button>
        ))}
      </div>

      {status ? <div className={/失败|错误|不能为空|不存在|不支持|必须/.test(status) ? 'notice danger' : 'notice'}>{status}</div> : null}

      {loading ? (
        <section className="model-provider-empty">正在读取模型提供商源...</section>
      ) : (
        <div className="model-provider-layout">
          <aside className="model-source-panel">
            <div className="model-panel-title">
              <h3>提供商源 <span>{sourceCountLabel}</span></h3>
              <button type="button" className="hy-btn hy-btn-primary" disabled={Boolean(busy)} onClick={createNewSource} title="新增提供商源">
                <UiIcon name="plus" />
                新增
              </button>
            </div>
            <div className="model-source-list">
              {capabilitySources.map((source) => {
                const preset = providerPreset(source.provider);
                const configured = Boolean(source.api_key_configured);
                const hasCapabilityModel = sourceHasCapabilityModel(source, activeCapability);
                const runtimeProvider = sourceHermesProvider(source);
                return (
                  <button
                    key={source.source_id}
                    type="button"
                    className={selectedSourceId === source.source_id ? 'active' : ''}
                    onClick={() => selectSource(source)}
                  >
                    <span className={`model-source-mark ${providerIconClass(source.provider)}`}>
                      <ProviderBrandIcon provider={source.provider} />
                    </span>
                    <span className="model-source-main">
                      <strong>{source.name}</strong>
                      <small>{source.base_url || source.provider_label || preset.label}</small>
                    </span>
                    <span className="model-source-badges">
                      <em className={source.enabled === false ? 'model-key-pill warn' : 'model-key-pill ok'}>{source.enabled === false ? '已暂停' : '正在使用'}</em>
                      {activeCapability !== 'tts' ? <em className={runtimePillClass(runtimeProvider)}>{runtimeProviderLabel(runtimeProvider)}</em> : null}
                      <em className={`status-pill ${statusClass(source.status)}`}>{statusLabel(source.status)}</em>
                      <em className={configured ? 'model-key-pill ok' : 'model-key-pill'}>{configured ? '密钥已配置' : activeCapability === 'tts' ? 'Token 可选' : '未配置 API'}</em>
                      {configured && !hasCapabilityModel ? <em className="model-key-pill warn">暂未选择模型</em> : null}
                    </span>
                  </button>
                );
              })}
              {!capabilitySources.length ? (
                <button type="button" className="model-source-empty-action" disabled={Boolean(busy)} onClick={createNewSource}>
                  <UiIcon name="plus" />
                  <strong>新增提供商源</strong>
                  <span>{activeCapability === 'tts' ? '创建 GPT-SoVITS / HTTP TTS 等语音来源' : '创建 OpenRouter / Xiaomi MiMo / MiniMax 等模型来源'}</span>
                </button>
              ) : null}
            </div>
          </aside>

          <section className="model-source-detail">
            {!selectedSourceId && !sourceDraft.name ? (
              <div className="model-preset-picker">
                <div className="model-preset-picker-head">
                  <div>
                    <span>选择预设</span>
                    <h3>添加模型提供商源</h3>
                  </div>
                  <p>{sourceFormHelp}</p>
                </div>
                <div className="model-preset-grid">
                  {activeProviderPresets.map((preset) => (
                    <button
                      type="button"
                      className="model-preset-card"
                      key={preset.id}
                      disabled={Boolean(busy)}
                      onClick={() => startPresetSource(preset)}
                    >
                      <span className={`model-source-mark ${providerIconClass(preset.id)}`}>
                        <ProviderBrandIcon provider={preset.id} />
                      </span>
                      <strong>{preset.label}</strong>
                      <small>{preset.baseUrl}</small>
                      {activeCapability !== 'tts' ? <span className={presetRuntimePillClass(preset.hermesProvider || preset.id)}>{runtimeProviderLabel(preset.hermesProvider || preset.id)}</span> : null}
                      <em>{preset.note}</em>
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <>
                <form
                  className="model-source-form"
                  onSubmit={(event) => {
                    if (activeCapability === 'tts') {
                      void onSaveSource(event);
                      return;
                    }
                    event.preventDefault();
                    void fetchModelsForSource();
                  }}
                >
                  <div className="model-source-config-head">
                    <span className={`model-source-mark ${providerIconClass(sourceDraft.provider)}`}>
                      <ProviderBrandIcon provider={sourceDraft.provider} />
                    </span>
                    <div>
                      <h3>{sourceDraft.name || providerPreset(sourceDraft.provider).label}</h3>
                      <p>{sourceDraft.base_url || providerPreset(sourceDraft.provider).baseUrl || sourceFormHelp}</p>
                    </div>
                    <div className="model-source-config-actions">
                      <span className={sourceDraft.enabled ? 'model-key-pill ok' : 'model-key-pill warn'}>{sourceDraft.enabled ? '正在使用' : '已暂停'}</span>
                      {activeCapability !== 'tts' ? <span className={runtimePillClass(sourceDraftRuntimeProvider)}>{runtimeProviderLabel(sourceDraftRuntimeProvider)}</span> : null}
                      <button type="button" className="hy-btn hy-btn-ghost" disabled={Boolean(busy)} onClick={returnToPresetList}>返回列表</button>
                      {activeCapability === 'tts' ? (
                        <button type="submit" className="hy-btn hy-btn-primary" disabled={Boolean(busy)}>
                          {busy === 'source-save' ? '保存中...' : '保存语音源'}
                        </button>
                      ) : (
                        <button type="button" className="hy-btn hy-btn-primary" disabled={Boolean(busy)} onClick={() => void fetchModelsForSource()}>
                          {busy === 'models-fetch' ? '获取中...' : sourceDraft.enabled ? '保存并获取模型列表' : '保存暂停状态'}
                        </button>
                      )}
                    </div>
                  </div>
                  <div className="model-inline-note">{sourceFormHelp}</div>
                  <div className="model-provider-grid">
                    <label className="model-provider-picker-field">
                      <span>提供商</span>
                      <div className="model-provider-picker">
                        <button
                          type="button"
                          className="model-provider-trigger"
                          disabled={Boolean(busy)}
                          aria-expanded={providerMenuOpen}
                          onClick={() => setProviderMenuOpen((open) => !open)}
                        >
                          <span className={`model-source-mark ${providerIconClass(sourceDraft.provider)}`}>
                            <ProviderBrandIcon provider={sourceDraft.provider} />
                          </span>
                          <span>{providerPreset(sourceDraft.provider).label}</span>
                          <span className="model-provider-trigger-caret" aria-hidden="true" />
                        </button>
                        {providerMenuOpen ? (
                          <div className="model-provider-menu" role="listbox">
                            {activeProviderPresets.map((preset) => (
                              <button
                                type="button"
                                key={preset.id}
                                className={sourceDraft.provider === preset.id ? 'active' : ''}
                                disabled={Boolean(busy)}
                                role="option"
                                aria-selected={sourceDraft.provider === preset.id}
                                onClick={() => applyProvider(preset.id)}
                              >
                                <span className={`model-source-mark ${providerIconClass(preset.id)}`}>
                                  <ProviderBrandIcon provider={preset.id} />
                                </span>
                                <span>
                                  <strong>{preset.label}</strong>
                                  <small>{preset.baseUrl || '本地或自定义语音端点'}</small>
                                </span>
                              </button>
                            ))}
                          </div>
                        ) : null}
                      </div>
                    </label>
                    <label>
                      <span>ID</span>
                      <input className="hy-input" value={sourceDraft.name} disabled={Boolean(busy)} onChange={(event) => setSourceDraft({ ...sourceDraft, name: event.target.value })} placeholder={activeCapability === 'tts' ? '例如 gpt-sovits-local' : '例如 openrouter / xiaomi-mimo'} />
                    </label>
                    <label>
                      <span>{activeCapability === 'tts' ? 'Endpoint' : 'Base URL'}</span>
                      <input className="hy-input" value={sourceDraft.base_url} disabled={Boolean(busy)} onChange={(event) => setSourceDraft({ ...sourceDraft, base_url: event.target.value })} placeholder={providerPreset(sourceDraft.provider).baseUrl || (activeCapability === 'tts' ? 'http://127.0.0.1:9880' : 'https://api.example.com/v1')} />
                    </label>
                    <label>
                      <span>{activeCapability === 'tts' ? 'Token / Key' : 'API Key'}</span>
                      <input className="hy-input" type="password" value={sourceDraft.api_key} disabled={Boolean(busy)} onChange={(event) => setSourceDraft({ ...sourceDraft, api_key: event.target.value })} placeholder={selectedSource?.api_key_configured ? '已配置，留空不覆盖' : '仅保存在本机后端'} />
                    </label>
                  </div>
                  <label className={sourceDraft.enabled ? 'model-profile-toggle' : 'model-profile-toggle paused'}>
                    <input type="checkbox" checked={sourceDraft.enabled} disabled={Boolean(busy)} onChange={(event) => setSourceDraft({ ...sourceDraft, enabled: event.target.checked })} />
                    <span>{sourceDraft.enabled ? '正在使用这个提供商源' : '已暂停这个提供商源'}</span>
                  </label>
                  <div className="agent-editor-actions">
                    {sourceDraft.source_id ? <button type="button" className="hy-btn hy-btn-danger" disabled={Boolean(busy)} onClick={() => void removeSource()}>删除源</button> : null}
                  </div>
                </form>

                <section className="model-source-models">
                  <div className="model-panel-title">
                    <h3>{capabilityLabels[activeCapability]}模型</h3>
                    <span>{visibleModels.length} 个</span>
                    {selectedSource?.api_key_configured && !visibleModels.length ? <em className="model-key-pill warn">暂未选择模型</em> : null}
                  </div>
                  <form
                    className="model-inline-form"
                    onSubmit={(event) => {
                      if (activeCapability === 'tts') {
                        void onSaveModel(event);
                        return;
                      }
                      event.preventDefault();
                      void runModelTest();
                    }}
                  >
                    <input
                      className="hy-input"
                      value={modelDraft.model}
                      disabled={Boolean(busy) || sourceDraft.enabled === false}
                      onChange={(event) => setModelDraft({ ...modelDraft, model: event.target.value })}
                      placeholder={activeCapability === 'tts' ? 'voice / profile id，例如 default-voice' : activeCapability === 'vision' ? '多模态模型 ID，例如 openai/gpt-4o-mini' : '模型 ID，例如 gpt-4.1-mini'}
                    />
                    <input className="hy-input" value={modelDraft.name} disabled={Boolean(busy) || sourceDraft.enabled === false} onChange={(event) => setModelDraft({ ...modelDraft, name: event.target.value })} placeholder="显示名称，可留空" />
                    {activeCapability === 'tts' ? (
                      <button type="submit" className="hy-btn hy-btn-primary" disabled={Boolean(busy)}>{modelDraft.profile_id ? '保存语音配置' : '添加语音配置'}</button>
                    ) : (
                      <button type="submit" className="hy-btn hy-btn-primary" disabled={Boolean(busy) || sourceDraft.enabled === false}>{busy === 'model-test' ? '测试中...' : '测试连接并保存'}</button>
                    )}
                  </form>

                  {activeCapability !== 'tts' && (modelCatalog.length || busy === 'models-fetch') ? (
                    <div className="model-catalog-panel">
                      <div className="model-catalog-head">
                        <div>
                          <strong>{activeCapability === 'vision' ? '远端模型列表（视觉实测为准）' : '远端模型列表'}</strong>
                          <span>
                            {modelCatalog.length
                              ? `${visibleCatalogModels.length}/${modelCatalog.length} 个模型 · ${modelCatalogGroups.length} 组`
                              : '正在获取...'}
                          </span>
                        </div>
                        <input
                          className="hy-input"
                          value={modelCatalogQuery}
                          disabled={(Boolean(busy) && busy !== 'models-fetch') || sourceDraft.enabled === false}
                          onChange={(event) => setModelCatalogQuery(event.target.value)}
                          placeholder="搜索模型 ID"
                        />
                      </div>
                      <div className="model-catalog-list grouped">
                        {modelCatalogGroups.map((group) => (
                          <section className="model-catalog-group" key={group.key}>
                            <div className="model-catalog-group-head">
                              {group.iconProvider ? (
                                <span className={`model-source-mark ${providerIconClass(group.iconProvider)}`}>
                                  <ProviderBrandIcon provider={group.iconProvider} />
                                </span>
                              ) : null}
                              <strong>{group.label}</strong>
                              <small>{group.models.length} 个</small>
                            </div>
                            <div className="model-catalog-group-items">
                              {group.models.map((model) => {
                                const badges = catalogModelBadges(model, activeCapability);
                                return (
                                  <button type="button" key={model.id} disabled={Boolean(busy) || sourceDraft.enabled === false} onClick={() => applyCatalogModel(model)}>
                                    <strong>{model.id}</strong>
                                    {model.name && model.name !== model.id ? <small>{model.name}</small> : null}
                                    {badges.length ? (
                                      <span className="model-catalog-badges">
                                        {badges.map((badge) => <em key={badge}>{badge}</em>)}
                                      </span>
                                    ) : null}
                                  </button>
                                );
                              })}
                            </div>
                          </section>
                        ))}
                        {!visibleCatalogModels.length ? <span className="model-catalog-empty">没有匹配的模型</span> : null}
                      </div>
                    </div>
                  ) : null}

                  <div className="model-table">
                    {visibleModels.map((model) => (
                      <div className={selectedModelId === model.profile_id ? 'model-row active' : 'model-row'} key={model.profile_id}>
                        <button type="button" onClick={() => { setSelectedModelId(model.profile_id); setModelDraft(modelToDraft(model)); }}>
                          <strong>{model.name}</strong>
                          <span>{sourceDraft.name}/{model.model}</span>
                        </button>
                        <em className={`status-pill ${statusClass(model.status)}`}>{statusLabel(model.status)}</em>
                        {model.capability !== 'tts' ? <em className={runtimePillClass(profileHermesProvider(model))}>{runtimeProviderLabel(profileHermesProvider(model))}</em> : null}
                        {defaults[model.capability] === model.profile_id ? <small>默认</small> : null}
                        <button type="button" className="hy-btn hy-btn-ghost" disabled={Boolean(busy) || !profileSelectableForHermes(model)} onClick={() => void setDefault(model)}>设为默认</button>
                        {model.capability !== 'tts' ? <button type="button" className="hy-btn hy-btn-ghost" disabled={Boolean(busy) || sourceDraft.enabled === false} onClick={() => void runModelTest(model.profile_id)}>重新测试</button> : null}
                        <button type="button" className="hy-btn hy-btn-danger" disabled={Boolean(busy)} onClick={() => void removeModel(model.profile_id)}>删除</button>
                      </div>
                    ))}
                    {!visibleModels.length ? (
                      <div className="model-provider-empty compact">
                        <strong>还没有{capabilityLabels[activeCapability]}模型</strong>
                        <span>{capabilityEmptyModelHint(activeCapability)}</span>
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
