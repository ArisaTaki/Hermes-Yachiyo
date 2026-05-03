export type TtsSettings = {
  enabled?: boolean;
  provider?: string;
  endpoint?: string;
  command?: string;
  voice?: string;
  timeout_seconds?: number;
  max_chars?: number;
  trigger_probability?: number;
  notification_prompt?: string;
  gsv_base_url?: string;
  gsv_gpt_weights_path?: string;
  gsv_sovits_weights_path?: string;
  gsv_ref_audio_path?: string;
  gsv_ref_audio_text?: string;
  gsv_ref_audio_language?: string;
  gsv_aux_ref_audio_path?: string;
  gsv_text_language?: string;
  gsv_top_k?: number;
  gsv_top_p?: number;
  gsv_temperature?: number;
  gsv_text_split_method?: string;
  gsv_batch_size?: number;
  gsv_batch_threshold?: number;
  gsv_split_bucket?: boolean;
  gsv_speed_factor?: number;
  gsv_fragment_interval?: number;
  gsv_streaming_mode?: boolean;
  gsv_seed?: number;
  gsv_parallel_infer?: boolean;
  gsv_repetition_penalty?: number;
  gsv_media_type?: string;
};

export type TtsForm = {
  enabled: boolean;
  provider: string;
  endpoint: string;
  command: string;
  voice: string;
  timeout_seconds: number;
  max_chars: number;
  trigger_probability: number;
  notification_prompt: string;
  gsv_base_url: string;
  gsv_gpt_weights_path: string;
  gsv_sovits_weights_path: string;
  gsv_ref_audio_path: string;
  gsv_ref_audio_text: string;
  gsv_ref_audio_language: string;
  gsv_aux_ref_audio_path: string;
  gsv_text_language: string;
  gsv_top_k: number;
  gsv_top_p: number;
  gsv_temperature: number;
  gsv_text_split_method: string;
  gsv_batch_size: number;
  gsv_batch_threshold: number;
  gsv_split_bucket: boolean;
  gsv_speed_factor: number;
  gsv_fragment_interval: number;
  gsv_streaming_mode: boolean;
  gsv_seed: number;
  gsv_parallel_infer: boolean;
  gsv_repetition_penalty: number;
  gsv_media_type: string;
};

export function emptyTtsForm(): TtsForm {
  return {
    enabled: false,
    provider: 'none',
    endpoint: '',
    command: '',
    voice: '',
    timeout_seconds: 20,
    max_chars: 80,
    trigger_probability: 0.6,
    notification_prompt: '主动提醒只输出适合语音播报的一句中文招呼或提醒，保持八千代人设，不要输出括号动作、舞台提示或表情描写，不要朗读长段分析、列表、代码、路径或调试信息。',
    gsv_base_url: 'http://127.0.0.1:9880',
    gsv_gpt_weights_path: '',
    gsv_sovits_weights_path: '',
    gsv_ref_audio_path: '',
    gsv_ref_audio_text: '',
    gsv_ref_audio_language: 'ja',
    gsv_aux_ref_audio_path: '',
    gsv_text_language: 'zh',
    gsv_top_k: 15,
    gsv_top_p: 1,
    gsv_temperature: 1,
    gsv_text_split_method: 'cut1',
    gsv_batch_size: 1,
    gsv_batch_threshold: 0.75,
    gsv_split_bucket: true,
    gsv_speed_factor: 1,
    gsv_fragment_interval: 0.3,
    gsv_streaming_mode: false,
    gsv_seed: -1,
    gsv_parallel_infer: false,
    gsv_repetition_penalty: 1.35,
    gsv_media_type: 'wav',
  };
}

export function formFromTtsSettings(settings: TtsSettings | undefined): TtsForm {
  return {
    ...emptyTtsForm(),
    ...settings,
    enabled: Boolean(settings?.enabled),
    provider: settings?.provider || 'none',
    timeout_seconds: Number(settings?.timeout_seconds || 20),
    max_chars: Number(settings?.max_chars || 80),
    trigger_probability: Number(settings?.trigger_probability ?? 0.6),
    gsv_top_k: Number(settings?.gsv_top_k || 15),
    gsv_top_p: Number(settings?.gsv_top_p ?? 1),
    gsv_temperature: Number(settings?.gsv_temperature ?? 1),
    gsv_batch_size: Number(settings?.gsv_batch_size || 1),
    gsv_batch_threshold: Number(settings?.gsv_batch_threshold ?? 0.75),
    gsv_split_bucket: settings?.gsv_split_bucket !== false,
    gsv_speed_factor: Number(settings?.gsv_speed_factor || 1),
    gsv_fragment_interval: Number(settings?.gsv_fragment_interval ?? 0.3),
    gsv_streaming_mode: Boolean(settings?.gsv_streaming_mode),
    gsv_seed: Number(settings?.gsv_seed ?? -1),
    gsv_parallel_infer: Boolean(settings?.gsv_parallel_infer),
    gsv_repetition_penalty: Number(settings?.gsv_repetition_penalty ?? 1.35),
    gsv_media_type: settings?.gsv_media_type || 'wav',
  };
}

export function ttsSettingsChanges(form: TtsForm): Record<string, string | boolean | number> {
  const provider = form.provider || 'none';
  return {
    'tts.enabled': Boolean(form.enabled && provider !== 'none'),
    'tts.provider': provider,
    'tts.endpoint': form.endpoint,
    'tts.command': form.command,
    'tts.voice': form.voice,
    'tts.timeout_seconds': Number(form.timeout_seconds),
    'tts.max_chars': Number(form.max_chars),
    'tts.notification_prompt': form.notification_prompt,
    'tts.gsv_base_url': form.gsv_base_url,
    'tts.gsv_gpt_weights_path': form.gsv_gpt_weights_path,
    'tts.gsv_sovits_weights_path': form.gsv_sovits_weights_path,
    'tts.gsv_ref_audio_path': form.gsv_ref_audio_path,
    'tts.gsv_ref_audio_text': form.gsv_ref_audio_text,
    'tts.gsv_ref_audio_language': form.gsv_ref_audio_language,
    'tts.gsv_aux_ref_audio_path': form.gsv_aux_ref_audio_path,
    'tts.gsv_text_language': form.gsv_text_language,
    'tts.gsv_top_k': Number(form.gsv_top_k),
    'tts.gsv_top_p': Number(form.gsv_top_p),
    'tts.gsv_temperature': Number(form.gsv_temperature),
    'tts.gsv_text_split_method': form.gsv_text_split_method,
    'tts.gsv_batch_size': Number(form.gsv_batch_size),
    'tts.gsv_batch_threshold': Number(form.gsv_batch_threshold),
    'tts.gsv_split_bucket': Boolean(form.gsv_split_bucket),
    'tts.gsv_speed_factor': Number(form.gsv_speed_factor),
    'tts.gsv_fragment_interval': Number(form.gsv_fragment_interval),
    'tts.gsv_streaming_mode': Boolean(form.gsv_streaming_mode),
    'tts.gsv_seed': Number(form.gsv_seed),
    'tts.gsv_parallel_infer': Boolean(form.gsv_parallel_infer),
    'tts.gsv_repetition_penalty': Number(form.gsv_repetition_penalty),
    'tts.gsv_media_type': form.gsv_media_type,
  };
}

export function ttsProviderLabel(provider: string): string {
  if (provider === 'gpt-sovits') return 'GPT-SoVITS 本地服务';
  if (provider === 'http') return 'HTTP POST';
  if (provider === 'command') return '本地命令';
  return '未选择';
}
