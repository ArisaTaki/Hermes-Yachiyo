import type { CSSProperties } from 'react';

type ProviderBrandIconProps = {
  provider: string;
  className?: string;
  size?: number;
};

type ProviderLogo =
  | {
      kind: 'image';
      src: string;
    }
  | {
      kind: 'text';
      text: string;
    };

const providerBrandLogos: Record<string, ProviderLogo> = {
  '302ai': { kind: 'text', text: '302' },
  aihubmix: { kind: 'text', text: 'AIH' },
  alibaba: { kind: 'text', text: 'ALI' },
  aliyun: { kind: 'text', text: 'ALI' },
  amazon: { kind: 'text', text: 'AWS' },
  anthropic: { kind: 'text', text: 'ANT' },
  arcee: { kind: 'text', text: 'ARC' },
  arcee_ai: { kind: 'text', text: 'ARC' },
  aws: { kind: 'text', text: 'AWS' },
  azure: { kind: 'text', text: 'AZ' },
  azure_openai: { kind: 'text', text: 'AZ' },
  azure_tts: { kind: 'text', text: 'AZ' },
  baichuan: { kind: 'text', text: 'BC' },
  baidu: { kind: 'text', text: 'BD' },
  baidu_qianfan: { kind: 'text', text: 'BD' },
  bailian: { kind: 'text', text: 'BL' },
  bytedance: { kind: 'text', text: 'BD' },
  bytedance_seed: { kind: 'text', text: 'BD' },
  cohere: { kind: 'text', text: 'CO' },
  command_tts: { kind: 'text', text: 'CMD' },
  compshare: { kind: 'image', src: '/provider-icons/compshare.ico' },
  dashscope: { kind: 'text', text: 'BL' },
  deepseek: { kind: 'text', text: 'DS' },
  doubao: { kind: 'text', text: 'DB' },
  edge_tts: { kind: 'text', text: 'MS' },
  fastgpt: { kind: 'text', text: 'FG' },
  fireworks: { kind: 'text', text: 'FW' },
  fishaudio: { kind: 'text', text: 'FA' },
  fishaudio_tts: { kind: 'text', text: 'FA' },
  gemini: { kind: 'text', text: 'G' },
  gemini_tts: { kind: 'text', text: 'G' },
  genie_tts: { kind: 'text', text: 'GEN' },
  google: { kind: 'text', text: 'G' },
  google_gemini: { kind: 'text', text: 'G' },
  gpt_sovits: { kind: 'text', text: 'GSV' },
  groq: { kind: 'text', text: 'GR' },
  gsv_tts_api: { kind: 'text', text: 'GSV' },
  gsv_tts_local: { kind: 'text', text: 'GSV' },
  huggingface: { kind: 'text', text: 'HF' },
  http_tts: { kind: 'text', text: 'HTTP' },
  hunyuan: { kind: 'text', text: 'HY' },
  ibm: { kind: 'text', text: 'IBM' },
  ibm_granite: { kind: 'text', text: 'IBM' },
  kimi: { kind: 'text', text: 'KM' },
  kimi_coding: { kind: 'text', text: 'KM' },
  kimi_coding_plan: { kind: 'text', text: 'KM' },
  liquid: { kind: 'text', text: 'LIQ' },
  lm_studio: { kind: 'text', text: 'LM' },
  lmstudio: { kind: 'text', text: 'LM' },
  meta: { kind: 'text', text: 'ME' },
  meta_llama: { kind: 'text', text: 'ME' },
  microsoft: { kind: 'text', text: 'MS' },
  minimax: { kind: 'text', text: 'MM' },
  minimax_cn: { kind: 'text', text: 'MM' },
  minimax_tts: { kind: 'text', text: 'MM' },
  mimo: { kind: 'text', text: 'MI' },
  mimo_tts: { kind: 'text', text: 'MI' },
  mistral: { kind: 'text', text: 'MI' },
  mistralai: { kind: 'text', text: 'MI' },
  modelscope: { kind: 'text', text: 'MS' },
  moonshot: { kind: 'text', text: 'KM' },
  moonshotai: { kind: 'text', text: 'KM' },
  nousresearch: { kind: 'text', text: 'NR' },
  nvidia: { kind: 'text', text: 'NV' },
  ollama: { kind: 'text', text: 'OL' },
  openai: { kind: 'text', text: 'AI' },
  openai_compatible: { kind: 'text', text: 'AI' },
  openai_tts: { kind: 'text', text: 'AI' },
  openrouter: { kind: 'text', text: 'OR' },
  perplexity: { kind: 'text', text: 'PX' },
  ppio: { kind: 'text', text: 'PP' },
  qianfan: { kind: 'text', text: 'BD' },
  qwen: { kind: 'text', text: 'QW' },
  qwen_dashscope: { kind: 'text', text: 'QW' },
  sensenova: { kind: 'text', text: 'SN' },
  siliconcloud: { kind: 'text', text: 'SC' },
  siliconflow: { kind: 'text', text: 'SF' },
  stepfun: { kind: 'text', text: 'ST' },
  tencent: { kind: 'text', text: 'TC' },
  tencent_hunyuan: { kind: 'text', text: 'HY' },
  tencent_tokenhub: { kind: 'text', text: 'TC' },
  together: { kind: 'text', text: 'TG' },
  tokenpony: { kind: 'image', src: '/provider-icons/tokenpony.png' },
  volcengine: { kind: 'text', text: 'VE' },
  volcengine_doubao: { kind: 'text', text: 'DB' },
  volcengine_tts: { kind: 'text', text: 'VE' },
  wenxin: { kind: 'text', text: 'WX' },
  x_ai: { kind: 'text', text: 'X' },
  xai: { kind: 'text', text: 'X' },
  xiaomi: { kind: 'text', text: 'MI' },
  xiaomi_mimo: { kind: 'text', text: 'MI' },
  xiaomimimo: { kind: 'text', text: 'MI' },
  z_ai: { kind: 'text', text: 'Z' },
  zai: { kind: 'text', text: 'Z' },
  zhipu: { kind: 'text', text: 'ZP' },
};

function normalizeProvider(provider: string): string {
  return (provider || 'openai_compatible').trim().toLowerCase().replace(/[^a-z0-9]+/g, '_');
}

function fallbackProviderText(provider: string): string {
  const id = normalizeProvider(provider);
  const parts = id.split('_').filter(Boolean);
  const initials = parts.map((part) => part[0]).join('').slice(0, 3).toUpperCase();
  if (initials) return initials;
  return 'AI';
}

function providerLogo(provider: string): ProviderLogo {
  const id = normalizeProvider(provider);
  return providerBrandLogos[id] || { kind: 'text', text: fallbackProviderText(provider) };
}

export function ProviderBrandIcon({
  provider,
  className = 'model-provider-logo',
  size = 20,
}: ProviderBrandIconProps) {
  const logo = providerLogo(provider);
  const style = {
    '--provider-logo-size': `${size}px`,
  } as CSSProperties;

  if (logo.kind === 'image') {
    return (
      <img
        alt=""
        aria-hidden="true"
        className={`${className} model-provider-logo-img`}
        src={logo.src}
        style={style}
      />
    );
  }

  return (
    <span
      aria-hidden="true"
      className={`${className} model-provider-logo-text`}
      style={style}
    >
      {logo.text}
    </span>
  );
}
