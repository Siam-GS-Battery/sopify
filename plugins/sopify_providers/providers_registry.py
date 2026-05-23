"""Single source of truth for AI provider metadata.

Used by the web dashboard's API key upload UI and the `sopify env` CLI to
describe which providers are supported, what env var holds each key,
which (if any) sbx secret service maps to the provider, and the expected
key prefix for basic sanity checks.

Adding a new provider is a one-line change here — `web_server.py` and
`ApiKeyUploadCard.tsx` both consume this list dynamically.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    env_var: str
    sbx_service: Optional[str]  # None when sbx has no service for this provider
    key_prefix: str             # empty string = no prefix check
    docs_url: Optional[str] = None


# Ordered for UI display. sbx_service mirrors `sbx secret set --help`:
#   anthropic, aws, cursor, droid, github, google, groq, mistral, nebius,
#   openai, xai
#
# Providers that AI traffic flows to but sbx doesn't manage credentials for
# (openrouter, novita, huggingface) get sbx_service=None — their keys still
# live in ~/.hermes/.env and travel through the AI traffic carve-out in
# no_proxy (see sbx_launcher._AI_NO_PROXY).
PROVIDERS: tuple[Provider, ...] = (
    Provider("anthropic",   "Anthropic",         "ANTHROPIC_API_KEY",  "anthropic", "sk-ant-",
             "https://console.anthropic.com/settings/keys"),
    Provider("openai",      "OpenAI",            "OPENAI_API_KEY",     "openai",    "sk-",
             "https://platform.openai.com/api-keys"),
    Provider("xai",         "xAI (Grok)",        "XAI_API_KEY",        "xai",       "xai-",
             "https://console.x.ai"),
    Provider("google",      "Google (Gemini)",   "GEMINI_API_KEY",     "google",    "",
             "https://aistudio.google.com/app/apikey"),
    Provider("groq",        "Groq",              "GROQ_API_KEY",       "groq",      "gsk_",
             "https://console.groq.com/keys"),
    Provider("mistral",     "Mistral",           "MISTRAL_API_KEY",    "mistral",   "",
             "https://console.mistral.ai/api-keys/"),
    Provider("nebius",      "Nebius",            "NEBIUS_API_KEY",     "nebius",    "",
             "https://studio.nebius.com"),
    Provider("openrouter",  "OpenRouter",        "OPENROUTER_API_KEY", None,        "sk-or-",
             "https://openrouter.ai/keys"),
    Provider("novita",      "Novita",            "NOVITA_API_KEY",     None,        "",
             "https://novita.ai/dashboard/key"),
    Provider("huggingface", "Hugging Face",      "HUGGINGFACE_TOKEN",  None,        "hf_",
             "https://huggingface.co/settings/tokens"),
)


def by_id(provider_id: str) -> Optional[Provider]:
    for p in PROVIDERS:
        if p.id == provider_id:
            return p
    return None
