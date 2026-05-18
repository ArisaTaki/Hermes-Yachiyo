import Ai302Icon from '@lobehub/icons/es/Ai302/components/Color';
import AiHubMixIcon from '@lobehub/icons/es/AiHubMix/components/Color';
import AnthropicIcon from '@lobehub/icons/es/Anthropic/components/Mono';
import ArceeIcon from '@lobehub/icons/es/Arcee/components/Color';
import AwsIcon from '@lobehub/icons/es/Aws/components/Color';
import AzureAIIcon from '@lobehub/icons/es/AzureAI/components/Color';
import BaichuanIcon from '@lobehub/icons/es/Baichuan/components/Color';
import BaiduIcon from '@lobehub/icons/es/Baidu/components/Color';
import BailianIcon from '@lobehub/icons/es/Bailian/components/Color';
import ByteDanceIcon from '@lobehub/icons/es/ByteDance/components/Color';
import CohereIcon from '@lobehub/icons/es/Cohere/components/Color';
import DeepSeekIcon from '@lobehub/icons/es/DeepSeek/components/Color';
import DoubaoIcon from '@lobehub/icons/es/Doubao/components/Color';
import FastGPTIcon from '@lobehub/icons/es/FastGPT/components/Color';
import FireworksIcon from '@lobehub/icons/es/Fireworks/components/Color';
import GeminiIcon from '@lobehub/icons/es/Gemini/components/Color';
import GoogleIcon from '@lobehub/icons/es/Google/components/Color';
import GroqIcon from '@lobehub/icons/es/Groq/components/Mono';
import HunyuanIcon from '@lobehub/icons/es/Hunyuan/components/Color';
import IBMIcon from '@lobehub/icons/es/IBM/components/Mono';
import KimiIcon from '@lobehub/icons/es/Kimi/components/Color';
import LiquidIcon from '@lobehub/icons/es/Liquid/components/Mono';
import LmStudioIcon from '@lobehub/icons/es/LmStudio/components/Mono';
import MetaIcon from '@lobehub/icons/es/Meta/components/Color';
import MicrosoftIcon from '@lobehub/icons/es/Microsoft/components/Color';
import MinimaxIcon from '@lobehub/icons/es/Minimax/components/Color';
import MistralIcon from '@lobehub/icons/es/Mistral/components/Color';
import ModelScopeIcon from '@lobehub/icons/es/ModelScope/components/Color';
import NousResearchIcon from '@lobehub/icons/es/NousResearch/components/Mono';
import NvidiaIcon from '@lobehub/icons/es/Nvidia/components/Color';
import OllamaIcon from '@lobehub/icons/es/Ollama/components/Mono';
import OpenAIIcon from '@lobehub/icons/es/OpenAI/components/Mono';
import OpenRouterIcon from '@lobehub/icons/es/OpenRouter/components/Mono';
import PPIOIcon from '@lobehub/icons/es/PPIO/components/Color';
import PerplexityIcon from '@lobehub/icons/es/Perplexity/components/Color';
import QwenIcon from '@lobehub/icons/es/Qwen/components/Color';
import SenseNovaIcon from '@lobehub/icons/es/SenseNova/components/Color';
import SiliconCloudIcon from '@lobehub/icons/es/SiliconCloud/components/Color';
import StepfunIcon from '@lobehub/icons/es/Stepfun/components/Color';
import TencentIcon from '@lobehub/icons/es/Tencent/components/Color';
import TogetherIcon from '@lobehub/icons/es/Together/components/Color';
import VolcengineIcon from '@lobehub/icons/es/Volcengine/components/Color';
import WenxinIcon from '@lobehub/icons/es/Wenxin/components/Color';
import XAIIcon from '@lobehub/icons/es/XAI/components/Mono';
import XiaomiMiMoIcon from '@lobehub/icons/es/XiaomiMiMo/components/Mono';
import ZAIIcon from '@lobehub/icons/es/ZAI/components/Mono';
import ZhipuIcon from '@lobehub/icons/es/Zhipu/components/Color';
import type { IconType } from '@lobehub/icons/es/types';

type ProviderBrandIconProps = {
  provider: string;
  className?: string;
  size?: number;
};

type ProviderLogo =
  | {
      Icon: IconType;
      kind: 'icon';
    }
  | {
      alt: string;
      kind: 'image';
      src: string;
    };

const providerBrandLogos: Record<string, ProviderLogo> = {
  '302ai': { Icon: Ai302Icon, kind: 'icon' },
  aihubmix: { Icon: AiHubMixIcon, kind: 'icon' },
  alibaba: { Icon: BailianIcon, kind: 'icon' },
  aliyun: { Icon: BailianIcon, kind: 'icon' },
  amazon: { Icon: AwsIcon, kind: 'icon' },
  anthropic: { Icon: AnthropicIcon, kind: 'icon' },
  arcee: { Icon: ArceeIcon, kind: 'icon' },
  arcee_ai: { Icon: ArceeIcon, kind: 'icon' },
  aws: { Icon: AwsIcon, kind: 'icon' },
  azure: { Icon: AzureAIIcon, kind: 'icon' },
  azure_openai: { Icon: AzureAIIcon, kind: 'icon' },
  baichuan: { Icon: BaichuanIcon, kind: 'icon' },
  baidu: { Icon: BaiduIcon, kind: 'icon' },
  baidu_qianfan: { Icon: WenxinIcon, kind: 'icon' },
  bailian: { Icon: BailianIcon, kind: 'icon' },
  bytedance: { Icon: ByteDanceIcon, kind: 'icon' },
  bytedance_seed: { Icon: ByteDanceIcon, kind: 'icon' },
  cohere: { Icon: CohereIcon, kind: 'icon' },
  compshare: { alt: 'Compshare', kind: 'image', src: '/provider-icons/compshare.ico' },
  dashscope: { Icon: BailianIcon, kind: 'icon' },
  deepseek: { Icon: DeepSeekIcon, kind: 'icon' },
  doubao: { Icon: DoubaoIcon, kind: 'icon' },
  fastgpt: { Icon: FastGPTIcon, kind: 'icon' },
  fireworks: { Icon: FireworksIcon, kind: 'icon' },
  gemini: { Icon: GeminiIcon, kind: 'icon' },
  google: { Icon: GoogleIcon, kind: 'icon' },
  google_gemini: { Icon: GeminiIcon, kind: 'icon' },
  groq: { Icon: GroqIcon, kind: 'icon' },
  hunyuan: { Icon: HunyuanIcon, kind: 'icon' },
  ibm: { Icon: IBMIcon, kind: 'icon' },
  ibm_granite: { Icon: IBMIcon, kind: 'icon' },
  kimi: { Icon: KimiIcon, kind: 'icon' },
  liquid: { Icon: LiquidIcon, kind: 'icon' },
  kimi_coding_plan: { Icon: KimiIcon, kind: 'icon' },
  lm_studio: { Icon: LmStudioIcon, kind: 'icon' },
  lmstudio: { Icon: LmStudioIcon, kind: 'icon' },
  minimax: { Icon: MinimaxIcon, kind: 'icon' },
  mistral: { Icon: MistralIcon, kind: 'icon' },
  mistralai: { Icon: MistralIcon, kind: 'icon' },
  mimo: { Icon: XiaomiMiMoIcon, kind: 'icon' },
  meta: { Icon: MetaIcon, kind: 'icon' },
  meta_llama: { Icon: MetaIcon, kind: 'icon' },
  microsoft: { Icon: MicrosoftIcon, kind: 'icon' },
  modelscope: { Icon: ModelScopeIcon, kind: 'icon' },
  moonshot: { Icon: KimiIcon, kind: 'icon' },
  moonshotai: { Icon: KimiIcon, kind: 'icon' },
  nvidia: { Icon: NvidiaIcon, kind: 'icon' },
  nousresearch: { Icon: NousResearchIcon, kind: 'icon' },
  ollama: { Icon: OllamaIcon, kind: 'icon' },
  openai: { Icon: OpenAIIcon, kind: 'icon' },
  openai_compatible: { Icon: OpenAIIcon, kind: 'icon' },
  openrouter: { Icon: OpenRouterIcon, kind: 'icon' },
  perplexity: { Icon: PerplexityIcon, kind: 'icon' },
  ppio: { Icon: PPIOIcon, kind: 'icon' },
  qianfan: { Icon: WenxinIcon, kind: 'icon' },
  qwen: { Icon: QwenIcon, kind: 'icon' },
  qwen_dashscope: { Icon: BailianIcon, kind: 'icon' },
  sensenova: { Icon: SenseNovaIcon, kind: 'icon' },
  siliconcloud: { Icon: SiliconCloudIcon, kind: 'icon' },
  siliconflow: { Icon: SiliconCloudIcon, kind: 'icon' },
  stepfun: { Icon: StepfunIcon, kind: 'icon' },
  tencent: { Icon: TencentIcon, kind: 'icon' },
  tencent_hunyuan: { Icon: HunyuanIcon, kind: 'icon' },
  together: { Icon: TogetherIcon, kind: 'icon' },
  tokenpony: { alt: 'TokenPony', kind: 'image', src: '/provider-icons/tokenpony.png' },
  volcengine: { Icon: VolcengineIcon, kind: 'icon' },
  volcengine_doubao: { Icon: DoubaoIcon, kind: 'icon' },
  wenxin: { Icon: WenxinIcon, kind: 'icon' },
  xai: { Icon: XAIIcon, kind: 'icon' },
  x_ai: { Icon: XAIIcon, kind: 'icon' },
  xiaomi: { Icon: XiaomiMiMoIcon, kind: 'icon' },
  xiaomi_mimo: { Icon: XiaomiMiMoIcon, kind: 'icon' },
  xiaomimimo: { Icon: XiaomiMiMoIcon, kind: 'icon' },
  zai: { Icon: ZAIIcon, kind: 'icon' },
  z_ai: { Icon: ZAIIcon, kind: 'icon' },
  zhipu: { Icon: ZhipuIcon, kind: 'icon' },
};

function normalizeProvider(provider: string): string {
  return (provider || 'openai_compatible').trim().toLowerCase().replace(/[^a-z0-9]+/g, '_');
}

function providerLogo(provider: string): ProviderLogo {
  const id = normalizeProvider(provider);
  return providerBrandLogos[id] || providerBrandLogos.openai_compatible;
}

export function ProviderBrandIcon({
  provider,
  className = 'model-provider-logo',
  size = 20,
}: ProviderBrandIconProps) {
  const logo = providerLogo(provider);

  if (logo.kind === 'image') {
    return <img alt="" aria-hidden="true" className={`${className} model-provider-logo-img`} src={logo.src} />;
  }

  const Icon = logo.Icon;
  return <Icon aria-hidden="true" className={className} focusable="false" size={size} />;
}
