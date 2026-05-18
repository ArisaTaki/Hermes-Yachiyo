import { useEffect, useMemo, useState, type FormEvent } from 'react';

import { ProviderBrandIcon } from '../components/ProviderBrandIcon';
import { UiIcon } from '../components/UiIcon';
import { apiGet } from '../lib/bridge';
import {
  createModelProfile,
  createModelSource,
  deleteModelProfile,
  deleteModelSource,
  fetchModelSourceModels,
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
  type RemoteModelInfo,
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

type ModelSourceView = ModelSource & {
  readonly?: boolean;
  source_kind?: 'hermes_main';
  api_key_name?: string;
  provider_label?: string;
};

type ModelProfileView = ModelProfile & {
  readonly?: boolean;
  source_kind?: 'hermes_main';
};

type HermesProviderOption = {
  id: string;
  label?: string;
  base_url?: string;
  default_model?: string;
  default_vision_model?: string;
  api_key_name?: string;
  api_key_configured?: boolean;
};

type HermesConfigSummary = {
  ok?: boolean;
  model?: {
    provider?: string;
    raw_provider?: string;
    default?: string;
    base_url?: string;
  };
  provider_options?: HermesProviderOption[];
  api_key?: {
    name?: string;
    configured?: boolean;
    display?: string;
  };
  vision?: {
    provider?: string;
    model?: string;
    base_url?: string;
    api_key_name?: string;
    api_key_configured?: boolean;
    effective_provider?: string;
    effective_model?: string;
    effective_base_url?: string;
  };
};

type ProviderPreset = {
  id: string;
  label: string;
  baseUrl: string;
  mark: string;
  note: string;
  modelHints?: string[];
};

type ModelCatalogGroup = {
  key: string;
  label: string;
  iconProvider?: string;
  models: RemoteModelInfo[];
};

const HERMES_MAIN_SOURCE_ID = 'hermes-main-source';
const HERMES_MAIN_CHAT_PROFILE_ID = 'hermes-main-chat-profile';
const HERMES_MAIN_VISION_PROFILE_ID = 'hermes-main-vision-profile';

const providerPresets: ProviderPreset[] = [
  {
    id: 'openai_compatible',
    label: 'OpenAI Compatible',
    baseUrl: 'https://api.openai.com/v1',
    mark: 'AI',
    note: '适合任意兼容 /v1/chat/completions 与 /v1/models 的网关。',
    modelHints: ['gpt-4.1-mini', 'gpt-4o-mini'],
  },
  {
    id: 'google_gemini',
    label: 'Google Gemini',
    baseUrl: 'https://generativelanguage.googleapis.com/v1beta/openai',
    mark: 'G',
    note: 'Gemini 的 OpenAI-compatible 端点，适合使用 Google AI Studio Key。',
    modelHints: ['gemini-2.5-flash', 'gemini-2.5-pro'],
  },
  {
    id: 'deepseek',
    label: 'DeepSeek',
    baseUrl: 'https://api.deepseek.com',
    mark: 'DS',
    note: 'DeepSeek 官方 OpenAI-compatible API。',
    modelHints: ['deepseek-chat', 'deepseek-reasoner'],
  },
  {
    id: 'qwen_dashscope',
    label: '阿里云百炼 / Qwen',
    baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    mark: 'Q',
    note: '阿里云百炼 DashScope 兼容模式，适合通义千问与多模态模型。',
    modelHints: ['qwen-plus', 'qwen-turbo', 'qwen-max'],
  },
  {
    id: 'moonshot',
    label: 'Moonshot / Kimi',
    baseUrl: 'https://api.moonshot.ai/v1',
    mark: 'K',
    note: 'Moonshot Kimi 官方兼容端点，适合 Kimi 与长上下文模型。',
    modelHints: ['moonshot-v1-8k', 'moonshot-v1-32k'],
  },
  {
    id: 'minimax',
    label: 'MiniMax',
    baseUrl: 'https://api.minimax.io/v1',
    mark: 'MM',
    note: 'MiniMax 国际站 OpenAI-compatible API。',
    modelHints: ['MiniMax-M2.7', 'MiniMax-Text-01'],
  },
  {
    id: 'zhipu',
    label: '智谱 GLM / BigModel',
    baseUrl: 'https://open.bigmodel.cn/api/paas/v4',
    mark: 'GLM',
    note: '智谱 GLM / BigModel OpenAI-compatible 端点。',
    modelHints: ['glm-4-flash', 'glm-4-plus'],
  },
  {
    id: 'volcengine_doubao',
    label: '火山方舟 / 豆包',
    baseUrl: 'https://ark.cn-beijing.volces.com/api/v3',
    mark: 'DB',
    note: '火山引擎方舟 OpenAI-compatible API；模型 ID 通常使用方舟 Endpoint ID。',
    modelHints: ['ep-xxxxxxxx', 'doubao-seed-1-6-flash-250715'],
  },
  {
    id: 'tencent_hunyuan',
    label: '腾讯混元',
    baseUrl: 'https://api.hunyuan.cloud.tencent.com/v1',
    mark: 'HY',
    note: '腾讯混元 OpenAI 兼容接口。',
    modelHints: ['hunyuan-turbos-latest', 'hunyuan-large-latest'],
  },
  {
    id: 'baidu_qianfan',
    label: '百度千帆 / 文心',
    baseUrl: 'https://qianfan.baidubce.com/v2',
    mark: 'BD',
    note: '百度千帆 ModelBuilder OpenAI-compatible v2 接口。',
    modelHints: ['ernie-4.0-turbo-8k', 'ernie-4.5-turbo-vl'],
  },
  {
    id: 'baichuan',
    label: '百川智能',
    baseUrl: 'https://api.baichuan-ai.com/v1',
    mark: 'BC',
    note: '百川智能 Baichuan 系列 OpenAI 风格 API。',
    modelHints: ['Baichuan4-Turbo', 'Baichuan4-Air'],
  },
  {
    id: 'stepfun',
    label: '阶跃星辰 StepFun',
    baseUrl: 'https://api.stepfun.com/v1',
    mark: 'S',
    note: '阶跃星辰 Step 系列 OpenAI-compatible API。',
    modelHints: ['step-2-mini', 'step-1-8k'],
  },
  {
    id: 'siliconflow',
    label: 'SiliconFlow',
    baseUrl: 'https://api.siliconflow.cn/v1',
    mark: 'SF',
    note: '国内常用模型聚合平台，支持 OpenAI-compatible 调用。',
    modelHints: ['Qwen/Qwen2.5-72B-Instruct', 'deepseek-ai/DeepSeek-V3'],
  },
  {
    id: 'modelscope',
    label: 'ModelScope 魔搭',
    baseUrl: 'https://api-inference.modelscope.cn/v1',
    mark: 'MS',
    note: '魔搭社区模型服务 OpenAI-compatible API。',
    modelHints: ['Qwen/Qwen2.5-7B-Instruct', 'deepseek-ai/DeepSeek-R1'],
  },
  {
    id: 'sensenova',
    label: '商汤日日新 SenseNova',
    baseUrl: 'https://api.sensenova.cn/compatible-mode/v2',
    mark: 'SN',
    note: '商汤日日新 OpenAI 接口兼容模式。',
    modelHints: ['SenseNova-6.7-Flash-Lite', 'SenseChat-5'],
  },
  {
    id: 'aihubmix',
    label: 'AIHubMix',
    baseUrl: 'https://aihubmix.com/v1',
    mark: 'AH',
    note: '国内常用聚合网关，兼容 OpenAI 请求格式。',
    modelHints: ['gpt-4o-mini', 'deepseek-chat'],
  },
  {
    id: 'ppio',
    label: 'PPIO 派欧云',
    baseUrl: 'https://api.ppinfra.com/v3/openai',
    mark: 'PP',
    note: 'PPIO 高性能模型推理服务的 OpenAI-compatible 入口。',
    modelHints: ['deepseek/deepseek-v3.1', 'qwen/qwen3-coder'],
  },
  {
    id: '302ai',
    label: '302.AI',
    baseUrl: 'https://api.302.ai/v1',
    mark: '302',
    note: '聚合式 OpenAI-compatible 转发服务。',
    modelHints: ['gpt-4o-mini', 'deepseek-chat'],
  },
  {
    id: 'tokenpony',
    label: 'TokenPony',
    baseUrl: 'https://api.tokenpony.cn/v1',
    mark: 'TP',
    note: '第三方模型聚合网关，适合统一管理多模型调用。',
    modelHints: ['gpt-4o-mini', 'deepseek-chat'],
  },
  {
    id: 'compshare',
    label: 'Compshare',
    baseUrl: 'https://api.compshare.cn/v1',
    mark: 'CS',
    note: '国内模型聚合服务，可按实际控制台地址调整 Base URL。',
    modelHints: ['deepseek-chat'],
  },
  {
    id: 'fastgpt',
    label: 'FastGPT',
    baseUrl: 'http://127.0.0.1:3000/api/v1',
    mark: 'FG',
    note: 'FastGPT 私有部署 / 知识库应用的 OpenAI-compatible 接口。',
    modelHints: ['fastgpt-app'],
  },
  {
    id: 'openrouter',
    label: 'OpenRouter',
    baseUrl: 'https://openrouter.ai/api/v1',
    mark: 'OR',
    note: '多供应商聚合路由，常用于快速接入 Claude、Gemini、DeepSeek 等模型。',
    modelHints: ['openai/gpt-4.1-mini', 'deepseek/deepseek-chat'],
  },
  {
    id: 'perplexity',
    label: 'Perplexity',
    baseUrl: 'https://api.perplexity.ai/v1',
    mark: 'P',
    note: '适合联网问答和检索增强场景的兼容 API。',
    modelHints: ['sonar', 'sonar-pro'],
  },
  {
    id: 'together',
    label: 'Together AI',
    baseUrl: 'https://api.together.xyz/v1',
    mark: 'T',
    note: '开源模型托管和推理平台，兼容 OpenAI 请求格式。',
    modelHints: ['meta-llama/Llama-3.3-70B-Instruct-Turbo'],
  },
  {
    id: 'fireworks',
    label: 'Fireworks AI',
    baseUrl: 'https://api.fireworks.ai/inference/v1',
    mark: 'FW',
    note: '模型推理与微调平台，提供 OpenAI-compatible endpoint。',
    modelHints: ['accounts/fireworks/models/llama-v3p1-70b-instruct'],
  },
  {
    id: 'mistral',
    label: 'Mistral AI',
    baseUrl: 'https://api.mistral.ai/v1',
    mark: 'M',
    note: 'Mistral 官方 API，适合 Mistral Large、Small、Codestral 等模型。',
    modelHints: ['mistral-large-latest', 'mistral-small-latest'],
  },
  {
    id: 'nvidia',
    label: 'NVIDIA NIM',
    baseUrl: 'https://integrate.api.nvidia.com/v1',
    mark: 'NV',
    note: 'NVIDIA 托管 NIM / Catalog API 的 OpenAI-compatible 入口。',
    modelHints: ['nvidia/llama-3.1-nemotron-70b-instruct'],
  },
  {
    id: 'xai',
    label: 'xAI',
    baseUrl: 'https://api.x.ai/v1',
    mark: 'x',
    note: 'xAI Grok 系列 OpenAI-compatible API。',
    modelHints: ['grok-4', 'grok-3-mini'],
  },
  {
    id: 'groq',
    label: 'Groq',
    baseUrl: 'https://api.groq.com/openai/v1',
    mark: 'GQ',
    note: '低延迟推理平台，兼容 OpenAI SDK。',
    modelHints: ['llama-3.3-70b-versatile', 'openai/gpt-oss-120b'],
  },
  {
    id: 'anthropic',
    label: 'Anthropic',
    baseUrl: 'https://api.anthropic.com/v1',
    mark: 'A',
    note: 'Claude 官方 API。当前自动测试仍以兼容接口为主，必要时可作为自定义源保存。',
    modelHints: ['claude-sonnet-4-5', 'claude-haiku-4-5'],
  },
  {
    id: 'ollama',
    label: 'Ollama',
    baseUrl: 'http://127.0.0.1:11434/v1',
    mark: 'O',
    note: '本机 Ollama OpenAI-compatible API，通常不需要 API Key。',
    modelHints: ['llama3.2', 'qwen2.5'],
  },
  {
    id: 'lm_studio',
    label: 'LM Studio',
    baseUrl: 'http://127.0.0.1:1234/v1',
    mark: 'LM',
    note: '本机 LM Studio Server，适合本地 GGUF 模型。',
    modelHints: ['local-model'],
  },
  {
    id: 'azure_openai',
    label: 'Azure OpenAI',
    baseUrl: '',
    mark: 'AZ',
    note: 'Azure OpenAI 端点由资源名和 API 版本决定，请按 Azure 控制台填写。',
    modelHints: ['gpt-4o-mini'],
  },
];

const capabilityLabels: Record<ModelCapability, string> = {
  chat: '对话',
  vision: '图片转述',
  tts: '文字转语音',
};

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

function providerPreset(provider: string): ProviderPreset {
  return providerPresets.find((item) => item.id === provider) || {
    id: provider || 'openai_compatible',
    label: provider || 'OpenAI Compatible',
    baseUrl: '',
    mark: 'AI',
    note: '自定义模型提供商源。',
  };
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

function catalogModelBadges(model: RemoteModelInfo): string[] {
  const badges: string[] = [];
  const inputModalities = new Set(model.input_modalities || []);
  const supportedParameters = new Set(model.supported_parameters || []);
  const context = formatContextLength(model.context_length);
  if (model.is_free || model.id.endsWith(':free')) badges.push('免费');
  if (inputModalities.has('image')) badges.push('视觉');
  if (inputModalities.has('file')) badges.push('文件');
  if (inputModalities.has('audio')) badges.push('音频');
  if (inputModalities.has('video')) badges.push('视频');
  if (supportedParameters.has('tools')) badges.push('工具');
  if (supportedParameters.has('structured_outputs') || supportedParameters.has('response_format')) badges.push('结构化');
  if (context) badges.push(context);
  return badges.slice(0, 5);
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
    enabled: model.enabled !== false,
  };
}

function sourceIsHermesMain(sourceId?: string): boolean {
  return sourceId === HERMES_MAIN_SOURCE_ID;
}

function providerOption(config: HermesConfigSummary | null, provider: string): HermesProviderOption | undefined {
  return config?.provider_options?.find((option) => option.id === provider);
}

function buildHermesMainSource(config: HermesConfigSummary | null): { source: ModelSourceView; profiles: ModelProfileView[] } | null {
  if (!config || config.ok === false) return null;
  const textModel = (config.model?.default || '').trim();
  const provider = (config.model?.provider || config.model?.raw_provider || 'openai_compatible').trim();
  const option = providerOption(config, provider);
  const preset = providerPreset(provider);
  const providerLabel = option?.label || preset.label || provider || 'OpenAI Compatible';
  const baseUrl = (config.model?.base_url || option?.base_url || preset.baseUrl || '').trim();
  const apiKeyName = config.api_key?.name || option?.api_key_name || 'API Key';
  const apiKeyConfigured = Boolean(config.api_key?.configured || option?.api_key_configured);
  if (!provider && !textModel && !apiKeyConfigured) return null;

  const now = '';
  const status = apiKeyConfigured && textModel ? 'available' : 'untested';
  const source: ModelSourceView = {
    source_id: HERMES_MAIN_SOURCE_ID,
    name: '本地主模型',
    provider: provider || 'openai_compatible',
    provider_label: providerLabel,
    base_url: baseUrl,
    api_key_configured: apiKeyConfigured,
    api_key_name: apiKeyName,
    enabled: true,
    readonly: true,
    source_kind: 'hermes_main',
    status,
    last_tested_at: '',
    last_error: '',
    created_at: now,
    updated_at: now,
    options: { source: 'hermes_config', api_key_name: apiKeyName, provider_label: providerLabel },
  };
  const profiles: ModelProfileView[] = [];
  if (textModel) {
    profiles.push({
      profile_id: HERMES_MAIN_CHAT_PROFILE_ID,
      source_id: HERMES_MAIN_SOURCE_ID,
      name: `主模型 / ${textModel}`,
      capability: 'chat',
      provider: provider || 'openai_compatible',
      base_url: baseUrl,
      model: textModel,
      api_key_configured: apiKeyConfigured,
      source_name: source.name,
      source_provider: source.provider,
      enabled: true,
      readonly: true,
      source_kind: 'hermes_main',
      status,
      last_tested_at: '',
      last_error: '',
      created_at: now,
      updated_at: now,
      options: { source: 'hermes_config' },
    });
  }

  const visionModel = (config.vision?.effective_model || config.vision?.model || '').trim();
  if (visionModel) {
    const visionProvider = (
      config.vision?.effective_provider
      || config.vision?.provider
      || provider
      || 'openai_compatible'
    ).trim();
    profiles.push({
      profile_id: HERMES_MAIN_VISION_PROFILE_ID,
      source_id: HERMES_MAIN_SOURCE_ID,
      name: `图片模型 / ${visionModel}`,
      capability: 'vision',
      provider: visionProvider,
      base_url: (config.vision?.effective_base_url || config.vision?.base_url || baseUrl).trim(),
      model: visionModel,
      api_key_configured: Boolean(config.vision?.api_key_configured || apiKeyConfigured),
      source_name: source.name,
      source_provider: source.provider,
      enabled: true,
      readonly: true,
      source_kind: 'hermes_main',
      status: config.vision?.api_key_configured || apiKeyConfigured ? 'available' : 'untested',
      last_tested_at: '',
      last_error: '',
      created_at: now,
      updated_at: now,
      options: { source: 'hermes_config' },
    });
  }

  source.models = profiles;
  return { source, profiles };
}

async function loadModelProfileData(): Promise<{
  sources: ModelSourceView[];
  profiles: ModelProfileView[];
  defaults: ModelProfileDefaults;
}> {
  const [profilePayload, hermesConfig] = await Promise.all([
    listModelProfiles(),
    apiGet<HermesConfigSummary>('/ui/hermes/config').catch(() => null),
  ]);
  const registrySources = (profilePayload.sources || []) as ModelSourceView[];
  const registryProfiles = (profilePayload.profiles || []) as ModelProfileView[];
  const hermesMain = buildHermesMainSource(hermesConfig);
  if (!hermesMain) {
    return {
      sources: registrySources,
      profiles: registryProfiles,
      defaults: profilePayload.defaults || {},
    };
  }
  return {
    sources: [hermesMain.source, ...registrySources],
    profiles: [...hermesMain.profiles, ...registryProfiles],
    defaults: profilePayload.defaults || {},
  };
}

function defaultModelName(source: SourceDraft, capability: ModelCapability): string {
  const preset = providerPreset(source.provider);
  if (capability === 'tts') return '';
  if (capability === 'vision') {
    if (preset.id === 'openai' || preset.id === 'openai_compatible') return 'gpt-4.1-mini';
    if (preset.id === 'google_gemini') return 'gemini-2.5-flash';
    if (preset.id === 'openrouter') return 'openai/gpt-4.1-mini';
    if (preset.id === 'minimax') return 'MiniMax-M2.7';
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
    if (!query) return modelCatalog;
    return modelCatalog
      .filter((model) => `${model.id} ${model.name || ''} ${model.owned_by || ''} ${model.provider_key || ''}`.toLowerCase().includes(query));
  }, [modelCatalog, modelCatalogQuery]);
  const modelCatalogGroups = useMemo(() => groupCatalogModels(visibleCatalogModels), [visibleCatalogModels]);

  async function refresh(nextSourceId = selectedSourceId, nextModelId = selectedModelId, capability = activeCapability) {
    const payload = await loadModelProfileData();
    const nextSources = payload.sources;
    const nextProfiles = payload.profiles;
    setSources(nextSources);
    setProfiles(nextProfiles);
    setDefaults(payload.defaults);

    const source = nextSources.find((item) => item.source_id === nextSourceId) || nextSources[0] || null;
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
      setSourceDraft(emptySourceDraft);
      setModelDraft({ ...emptyModelDraft, capability });
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
    setModelCatalog([]);
    setModelCatalogQuery('');
    setProviderMenuOpen(false);
    setStatus('');
  }

  function createNewSource() {
    if (busy) return;
    setSelectedSourceId('');
    setSelectedModelId('');
    setSourceDraft(emptySourceDraft);
    setModelDraft({ ...emptyModelDraft, capability: activeCapability });
    setModelCatalog([]);
    setModelCatalogQuery('');
    setProviderMenuOpen(false);
    setStatus('');
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
    const firstModel = profiles.find((profile) => profile.source_id === selectedSourceId && profile.capability === capability);
    setSelectedModelId(firstModel?.profile_id || '');
    setModelDraft(firstModel ? modelToDraft(firstModel) : { ...emptyModelDraft, capability, model: defaultModelName(sourceDraft, capability) });
  }

  function applyProvider(provider: string) {
    const preset = providerPreset(provider);
    setSourceDraft((current) => ({
      ...current,
      provider,
      name: current.name || preset.id,
      base_url: preset.baseUrl || current.base_url,
    }));
    setModelCatalog([]);
    setModelCatalogQuery('');
    setProviderMenuOpen(false);
  }

  async function saveSource(): Promise<ModelSource> {
    if (sourceIsHermesMain(sourceDraft.source_id)) {
      throw new Error('本地主模型请在主模型配置中修改');
    }
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

  async function fetchModelsForSource() {
    if (busy) return;
    if (sourceIsHermesMain(sourceDraft.source_id)) {
      setStatus('本地主模型来自 Hermes 主配置，不需要单独获取模型列表');
      return;
    }
    setBusy('models-fetch');
    setStatus('正在保存源并获取模型列表...');
    try {
      const saved = await saveSource();
      const result = await fetchModelSourceModels(saved.source_id);
      const models = result.models || [];
      setModelCatalog(models);
      setModelCatalogQuery('');
      setStatus(models.length ? `已获取 ${models.length} 个模型，点击模型 ID 可填入下方表单` : '已连接源，但没有读取到模型列表');
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
      name: current.name || `${sourceDraft.name}/${model.id}`,
    }));
  }

  async function saveModel(): Promise<ModelProfile> {
    if (sourceIsHermesMain(sourceDraft.source_id)) {
      throw new Error('本地主模型记录为只读快照，请新增独立提供商源后再登记模型');
    }
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
    if (!sourceDraft.source_id || sourceIsHermesMain(sourceDraft.source_id) || busy) return;
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
    if (sourceIsHermesMain(profile.source_id)) {
      setStatus('本地主模型已经由 Hermes 主配置管理，不能设为 Profile 默认项');
      return;
    }
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

  const selectedIsHermesMain = sourceIsHermesMain(selectedSourceId);
  const selectedSourceApiConfigured = Boolean(selectedSource?.api_key_configured);
  const selectedSourceProviderLabel = selectedSource?.provider_label || providerPreset(sourceDraft.provider).label;
  const sourceCountLabel = sources.length ? `${sources.length}` : '0';

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
            aria-pressed={activeCapability === capability}
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
              <h3>提供商源 <span>{sourceCountLabel}</span></h3>
              <button type="button" className="hy-btn hy-btn-primary" disabled={Boolean(busy)} onClick={createNewSource} title="新增提供商源">
                <UiIcon name="plus" />
                新增
              </button>
            </div>
            <div className="model-source-list">
              {sources.map((source) => {
                const preset = providerPreset(source.provider);
                const configured = Boolean(source.api_key_configured);
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
                      <strong>
                        {source.name}
                        {source.readonly ? <small>主</small> : null}
                      </strong>
                      <small>{source.base_url || source.provider_label || preset.label}</small>
                    </span>
                    <span className="model-source-badges">
                      <em className={`status-pill ${statusClass(source.status)}`}>{statusLabel(source.status)}</em>
                      <em className={configured ? 'model-key-pill ok' : 'model-key-pill'}>{configured ? 'API 已配置' : '未配置 API'}</em>
                    </span>
                  </button>
                );
              })}
              {!sources.length ? (
                <button type="button" className="model-source-empty-action" disabled={Boolean(busy)} onClick={createNewSource}>
                  <UiIcon name="plus" />
                  <strong>新增提供商源</strong>
                  <span>创建 OpenAI-compatible / MiniMax / OpenRouter / Ollama 等来源</span>
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
                  <p>预设会自动填入提供商 ID、Base URL 和常用模型 ID。保存 API Key 后可以直接拉取远端模型列表。</p>
                </div>
                <div className="model-preset-grid">
                  {providerPresets.map((preset) => (
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
                      <em>{preset.note}</em>
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <>
                {selectedIsHermesMain ? (
                  <section className="model-main-summary">
                    <div className="model-main-summary-header">
                      <span className={`model-source-mark ${providerIconClass(sourceDraft.provider)}`}>
                        <ProviderBrandIcon provider={sourceDraft.provider} />
                      </span>
                      <div>
                        <h3>本地主模型配置</h3>
                        <p>来自 Hermes 当前文本与图片模型设置，只读展示，不复制或暴露 API Key。</p>
                      </div>
                    </div>
                    <div className="model-main-summary-grid">
                      <span><strong>提供商</strong><em>{selectedSourceProviderLabel}</em></span>
                      <span><strong>Base URL</strong><em>{sourceDraft.base_url || '未配置'}</em></span>
                      <span><strong>密钥状态</strong><em>{selectedSourceApiConfigured ? `${selectedSource?.api_key_name || 'API Key'} 已配置` : '未配置 API Key'}</em></span>
                      <span><strong>来源</strong><em>Hermes 主配置</em></span>
                    </div>
                    <div className="agent-editor-actions">
                      <button type="button" className="hy-btn hy-btn-primary" onClick={() => navigateTo('installer')}>编辑主模型</button>
                      <button type="button" className="hy-btn hy-btn-ghost" disabled={Boolean(busy)} onClick={createNewSource}>新增独立源</button>
                    </div>
                  </section>
                ) : (
                  <form className="model-source-form" onSubmit={onSaveSource}>
                    <div className="model-source-config-head">
                      <span className={`model-source-mark ${providerIconClass(sourceDraft.provider)}`}>
                        <ProviderBrandIcon provider={sourceDraft.provider} />
                      </span>
                      <div>
                        <small>设置</small>
                        <h3>{sourceDraft.name || providerPreset(sourceDraft.provider).label}</h3>
                        <p>{sourceDraft.base_url || providerPreset(sourceDraft.provider).baseUrl || '未配置 Base URL'}</p>
                      </div>
                      <button type="submit" className="hy-btn hy-btn-primary" disabled={Boolean(busy)}>
                        {busy === 'source-save' ? '保存中...' : '保存配置'}
                      </button>
                    </div>
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
                              {providerPresets.map((preset) => (
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
                                    <small>{preset.baseUrl || '自定义 Azure Endpoint'}</small>
                                  </span>
                                </button>
                              ))}
                            </div>
                          ) : null}
                        </div>
                      </label>
                      <label>
                        <span>ID</span>
                        <input className="hy-input" value={sourceDraft.name} disabled={Boolean(busy)} onChange={(event) => setSourceDraft({ ...sourceDraft, name: event.target.value })} placeholder="例如 openrouter / moonshot-work" />
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
                      <button type="button" className="hy-btn hy-btn-ghost" disabled={Boolean(busy)} onClick={() => void fetchModelsForSource()}>{busy === 'models-fetch' ? '获取中...' : '保存并获取模型'}</button>
                      <button type="button" className="hy-btn hy-btn-primary" disabled={Boolean(busy)} onClick={() => void runSourceTest()}>{busy === 'source-test' ? '测试中...' : '保存并测试源'}</button>
                      {sourceDraft.source_id ? <button type="button" className="hy-btn hy-btn-danger" disabled={Boolean(busy)} onClick={() => void removeSource()}>删除源</button> : null}
                    </div>
                  </form>
                )}

                <section className="model-source-models">
                  <div className="model-panel-title">
                    <h3>{capabilityLabels[activeCapability]}模型</h3>
                    <span>{visibleModels.length} 个</span>
                  </div>
                  {selectedIsHermesMain ? (
                    <div className="model-inline-note">本地主模型由 Hermes 主配置管理。新增独立源后，可以为 Agent Studio / Workflow Studio 登记专用模型。</div>
                  ) : (
                    <form className="model-inline-form" onSubmit={onSaveModel}>
                      <input className="hy-input" value={modelDraft.model} disabled={Boolean(busy)} onChange={(event) => setModelDraft({ ...modelDraft, model: event.target.value })} placeholder="模型 ID，例如 gpt-4.1-mini" />
                      <input className="hy-input" value={modelDraft.name} disabled={Boolean(busy)} onChange={(event) => setModelDraft({ ...modelDraft, name: event.target.value })} placeholder="显示名称，可留空" />
                      <button type="submit" className="hy-btn hy-btn-ghost" disabled={Boolean(busy)}>{modelDraft.profile_id ? '保存模型' : '添加模型'}</button>
                      <button type="button" className="hy-btn hy-btn-primary" disabled={Boolean(busy)} onClick={() => void runModelTest()}>{busy === 'model-test' ? '测试中...' : '保存并测试'}</button>
                    </form>
                  )}

                  {!selectedIsHermesMain && (modelCatalog.length || busy === 'models-fetch') ? (
                    <div className="model-catalog-panel">
                      <div className="model-catalog-head">
                        <div>
                          <strong>远端模型列表</strong>
                          <span>
                            {modelCatalog.length
                              ? `${visibleCatalogModels.length}/${modelCatalog.length} 个模型 · ${modelCatalogGroups.length} 组`
                              : '正在获取...'}
                          </span>
                        </div>
                        <input
                          className="hy-input"
                          value={modelCatalogQuery}
                          disabled={Boolean(busy) && busy !== 'models-fetch'}
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
                                const badges = catalogModelBadges(model);
                                return (
                                  <button type="button" key={model.id} disabled={Boolean(busy)} onClick={() => applyCatalogModel(model)}>
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
                        {model.readonly ? <small>主模型</small> : defaults[model.capability] === model.profile_id ? <small>默认</small> : null}
                        {model.readonly ? (
                          <button type="button" className="hy-btn hy-btn-ghost" onClick={() => navigateTo('installer')}>编辑</button>
                        ) : (
                          <>
                            <button type="button" className="hy-btn hy-btn-ghost" disabled={Boolean(busy)} onClick={() => void setDefault(model)}>设为默认</button>
                            <button type="button" className="hy-btn hy-btn-ghost" disabled={Boolean(busy)} onClick={() => void runModelTest(model.profile_id)}>测试</button>
                            <button type="button" className="hy-btn hy-btn-danger" disabled={Boolean(busy)} onClick={() => void removeModel(model.profile_id)}>删除</button>
                          </>
                        )}
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
