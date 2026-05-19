"""Provider adapter metadata shared by Model Profile and Hermes config code.

Yachiyo keeps user-facing source names separate from the provider identifier
that Hermes CLI can actually execute.  OpenRouter model vendors are only
catalog groups; the executable provider remains ``openrouter``.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

HERMES_RUNTIME_PROVIDER_IDS = {
    "ai-gateway",
    "alibaba",
    "alibaba-coding-plan",
    "anthropic",
    "arcee",
    "azure-foundry",
    "bedrock",
    "custom",
    "deepseek",
    "gemini",
    "gmi",
    "huggingface",
    "kimi-coding",
    "kimi-coding-cn",
    "lmstudio",
    "minimax",
    "minimax-cn",
    "moonshot",
    "nvidia",
    "nous",
    "openai",
    "openai-codex",
    "openrouter",
    "opencode-go",
    "opencode-zen",
    "stepfun",
    "tencent-tokenhub",
    "xai",
    "xiaomi",
    "zai",
}

HERMES_PROVIDER_LABELS = {
    "ai-gateway": "Vercel AI Gateway",
    "alibaba": "Alibaba DashScope",
    "alibaba-coding-plan": "Alibaba Coding Plan",
    "anthropic": "Anthropic",
    "arcee": "Arcee",
    "azure-foundry": "Azure Foundry",
    "bedrock": "AWS Bedrock",
    "custom": "Hermes Custom",
    "deepseek": "DeepSeek",
    "gemini": "Google Gemini",
    "gmi": "GMI",
    "huggingface": "Hugging Face",
    "kimi-coding": "Kimi Coding",
    "kimi-coding-cn": "Kimi CN",
    "lmstudio": "LM Studio",
    "minimax": "MiniMax",
    "minimax-cn": "MiniMax CN",
    "moonshot": "Moonshot",
    "nvidia": "NVIDIA",
    "nous": "Nous",
    "openai": "OpenAI",
    "openai-codex": "OpenAI Codex",
    "openrouter": "OpenRouter",
    "opencode-go": "OpenCode Go",
    "opencode-zen": "OpenCode Zen",
    "stepfun": "StepFun",
    "tencent-tokenhub": "Tencent TokenHub",
    "xai": "xAI",
    "xiaomi": "Xiaomi MiMo",
    "zai": "Z.AI",
}

HERMES_PROVIDER_API_KEY_NAMES = {
    "ai-gateway": ("AI_GATEWAY_API_KEY",),
    "alibaba": ("DASHSCOPE_API_KEY", "ALIBABA_CODING_PLAN_API_KEY"),
    "alibaba-coding-plan": ("ALIBABA_CODING_PLAN_API_KEY", "DASHSCOPE_API_KEY"),
    "anthropic": ("ANTHROPIC_API_KEY", "ANTHROPIC_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"),
    "arcee": ("ARCEEAI_API_KEY",),
    "azure-foundry": ("AZURE_FOUNDRY_API_KEY",),
    "bedrock": ("AWS_PROFILE", "AWS_REGION"),
    "custom": ("CUSTOM_API_KEY",),
    "deepseek": ("DEEPSEEK_API_KEY",),
    "gemini": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    "gmi": ("GMI_API_KEY",),
    "huggingface": ("HF_TOKEN",),
    "kimi-coding": ("KIMI_API_KEY", "KIMI_CODING_API_KEY"),
    "kimi-coding-cn": ("KIMI_CN_API_KEY", "KIMI_API_KEY"),
    "lmstudio": ("LM_API_KEY",),
    "minimax": ("MINIMAX_API_KEY",),
    "minimax-cn": ("MINIMAX_CN_API_KEY", "MINIMAX_API_KEY"),
    "moonshot": ("KIMI_API_KEY", "KIMI_CODING_API_KEY"),
    "nvidia": ("NVIDIA_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "openrouter": ("OPENROUTER_API_KEY", "OPENAI_API_KEY"),
    "opencode-go": ("OPENCODE_GO_API_KEY",),
    "opencode-zen": ("OPENCODE_ZEN_API_KEY",),
    "stepfun": ("STEPFUN_API_KEY",),
    "tencent-tokenhub": ("TENCENT_TOKENHUB_API_KEY",),
    "xai": ("XAI_API_KEY",),
    "xiaomi": ("XIAOMI_API_KEY",),
    "zai": ("GLM_API_KEY", "ZAI_API_KEY", "Z_AI_API_KEY"),
}

HERMES_PROVIDER_ALIASES = {
    "302ai": "custom",
    "aihubmix": "custom",
    "azure_openai": "azure-foundry",
    "baidu_qianfan": "custom",
    "dashscope": "alibaba",
    "google": "gemini",
    "google-ai": "gemini",
    "google-ai-studio": "gemini",
    "google_gemini": "gemini",
    "kimi": "kimi-coding",
    "kimi_coding_plan": "kimi-coding",
    "lm_studio": "lmstudio",
    "mimo": "xiaomi",
    "moonshot": "kimi-coding",
    "openai-compatible": "custom",
    "qwen_dashscope": "alibaba",
    "tencent_hunyuan": "tencent-tokenhub",
    "x-ai": "xai",
    "xiaomi_mimo": "xiaomi",
    "z-ai": "zai",
    "z_ai": "zai",
    "zhipu": "zai",
}

HERMES_PROVIDER_HOST_HINTS: tuple[tuple[str, str], ...] = (
    ("openrouter.ai", "openrouter"),
    ("api.openai.com", "openai"),
    ("api.anthropic.com", "anthropic"),
    ("generativelanguage.googleapis.com", "gemini"),
    ("dashscope.aliyuncs.com", "alibaba"),
    ("dashscope-intl.aliyuncs.com", "alibaba"),
    ("api.xiaomimimo.com", "xiaomi"),
    ("token-plan-cn.xiaomimimo.com", "xiaomi"),
    ("api.deepseek.com", "deepseek"),
    ("api.x.ai", "xai"),
    ("api.moonshot.ai", "kimi-coding"),
    ("api.moonshot.cn", "kimi-coding-cn"),
    ("api.kimi.com", "kimi-coding"),
    ("api.z.ai", "zai"),
    ("open.bigmodel.cn", "zai"),
    ("api.minimax.io", "minimax"),
    ("api.minimaxi.com", "minimax-cn"),
    ("api.stepfun.com", "stepfun"),
    ("integrate.api.nvidia.com", "nvidia"),
    ("router.huggingface.co", "huggingface"),
)

OPENROUTER_MODEL_PREFIXES = (
    "anthropic/",
    "openai/",
    "google/",
    "deepseek/",
    "x-ai/",
    "meta-llama/",
    "mistralai/",
    "qwen/",
    "minimax/",
    "xiaomi/",
    "z-ai/",
)

AUTO_PROVIDER_VALUES = {"", "auto", "main", "openai_compatible", "openai-compatible"}


def normalize_provider_id(provider: str) -> str:
    return (provider or "").strip().lower()


def provider_api_key_names(provider: str) -> tuple[str, ...]:
    normalized = normalize_provider_id(provider)
    return HERMES_PROVIDER_API_KEY_NAMES.get(
        normalized,
        (f"{normalized.upper().replace('-', '_').replace('.', '_')}_API_KEY",) if normalized else (),
    )


def infer_hermes_provider(provider: str, base_url: str = "", model: str = "") -> str:
    normalized = normalize_provider_id(provider)
    if normalized and normalized not in AUTO_PROVIDER_VALUES:
        return HERMES_PROVIDER_ALIASES.get(normalized, normalized)

    host = (urlparse(base_url or "").hostname or "").lower()
    for suffix, provider_id in HERMES_PROVIDER_HOST_HINTS:
        if host == suffix or host.endswith(f".{suffix}"):
            return provider_id

    model_id = (model or "").strip().lower()
    if any(model_id.startswith(prefix) for prefix in OPENROUTER_MODEL_PREFIXES):
        return "openrouter"
    return ""


def resolve_provider_adapter(provider: str, base_url: str = "", model: str = "") -> dict[str, Any]:
    source_provider = (provider or "openai_compatible").strip()
    normalized = normalize_provider_id(source_provider)
    inferred = infer_hermes_provider(source_provider, base_url, model)

    if inferred in HERMES_RUNTIME_PROVIDER_IDS:
        hermes_provider = inferred
    elif normalized in AUTO_PROVIDER_VALUES:
        hermes_provider = "custom"
    elif base_url:
        hermes_provider = "custom"
    else:
        hermes_provider = ""

    can_use_as_hermes = bool(hermes_provider in HERMES_RUNTIME_PROVIDER_IDS)
    api_key_names = provider_api_key_names(hermes_provider) if hermes_provider else ()
    return {
        "source_provider": source_provider,
        "hermes_provider": hermes_provider,
        "hermes_provider_label": HERMES_PROVIDER_LABELS.get(hermes_provider, hermes_provider),
        "api_key_name": api_key_names[0] if api_key_names else "",
        "api_key_names": list(api_key_names),
        "runtime_scope": "hermes" if can_use_as_hermes else "unsupported",
        "can_use_as_hermes": can_use_as_hermes,
        "note": "写入 Hermes custom provider" if hermes_provider == "custom" else "",
    }
