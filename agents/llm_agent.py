"""Configurable LLM wrapper for local deterministic agents."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from agents.base_agent import BaseAgent


SECRET_KEYS = {"api_key", "secret", "token", "password"}


@dataclass(frozen=True)
class LLMConfig:
    """LLM 配置只保存模型选择和运行参数，密钥必须来自环境变量或外部凭证。"""

    enabled: bool
    provider: str
    model: str
    system_prompt: str = ""
    temperature: float = 0.2
    max_output_tokens: int = 4096
    merge_output: bool = True
    response: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> "LLMConfig":
        raw = dict(data or {})
        inline_secrets = sorted(key for key in raw if key.lower() in SECRET_KEYS)
        if inline_secrets:
            joined = ", ".join(inline_secrets)
            raise ValueError(f"LLM 配置不能直接写入密钥字段：{joined}。请使用环境变量或外部凭证。")
        return cls(
            enabled=bool(raw.get("enabled", False)),
            provider=str(raw.get("provider", "disabled")),
            model=str(raw.get("model", "")),
            system_prompt=str(raw.get("system_prompt", "")),
            temperature=float(raw.get("temperature", 0.2)),
            max_output_tokens=int(raw.get("max_output_tokens", 4096)),
            merge_output=bool(raw.get("merge_output", True)),
            response=dict(raw.get("response", {})),
        )


@dataclass(frozen=True)
class LLMRequest:
    """发送给 LLM 客户端的结构化请求，便于测试和审计。"""

    agent_name: str
    payload: dict[str, Any]
    fallback_output: dict[str, Any]
    config: LLMConfig


@dataclass(frozen=True)
class LLMResponse:
    """LLM 客户端返回的结构化结果。"""

    output: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)


class LLMClient(Protocol):
    """LLM 客户端协议；真实 provider 和测试 mock 都实现这个接口。"""

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Return a structured LLM response."""


class StaticLLMClient:
    """用于测试和离线演示的静态 LLM 客户端，不访问网络。"""

    def __init__(
        self,
        output: Mapping[str, Any],
        *,
        captured_requests: list[LLMRequest] | None = None,
    ) -> None:
        self.output = dict(output)
        self.captured_requests = captured_requests

    def complete(self, request: LLMRequest) -> LLMResponse:
        if self.captured_requests is not None:
            self.captured_requests.append(request)
        return LLMResponse(
            output=dict(self.output),
            metadata={
                "provider": request.config.provider,
                "model": request.config.model,
                "mode": "static",
            },
        )


class UnsupportedLLMClient:
    """明确阻止未实现 provider 静默访问外部服务。"""

    def complete(self, request: LLMRequest) -> LLMResponse:
        raise RuntimeError(
            f"LLM provider 尚未接入：{request.config.provider}。"
            "请先实现对应 LLMClient，或使用 provider=mock 进行离线验证。"
        )


def llm_client_from_config(config: LLMConfig) -> LLMClient:
    """根据配置创建 LLM 客户端；当前只内置 mock，真实 provider 后续接入。"""
    if config.provider in {"mock", "static"}:
        return StaticLLMClient(config.response)
    return UnsupportedLLMClient()


class LLMAgent(BaseAgent):
    """Wrap a deterministic agent and optionally enhance its output with LLM data."""

    def __init__(
        self,
        *,
        fallback_agent: BaseAgent,
        config: LLMConfig,
        client: LLMClient | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name or f"llm-{fallback_agent.name}")
        self.fallback_agent = fallback_agent
        self.config = config
        self.client = client or llm_client_from_config(config)

    def handle(self, payload: dict[str, Any]) -> Mapping[str, Any]:
        fallback_output = self.fallback_agent.run(payload).output
        if not self.config.enabled:
            return fallback_output

        request = LLMRequest(
            agent_name=self.fallback_agent.name,
            payload=dict(payload),
            fallback_output=dict(fallback_output),
            config=self.config,
        )
        response = self.client.complete(request)
        output = dict(fallback_output)
        if self.config.merge_output:
            output.update(response.output)
        else:
            output["llm_output"] = dict(response.output)
        output["llm"] = {
            "used": True,
            "provider": self.config.provider,
            "model": self.config.model,
        }
        return output
