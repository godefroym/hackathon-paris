from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from typing import Any

from mistralai import Mistral

from utils.retry import compute_backoff_seconds, is_rate_limited_error
from utils.sources import domain_to_organization, is_valid_http_url, normalized_host

from .agent_specs import AGENT_DEFINITIONS, response_format_for_model
from .schemas import AgentPool


_HTTP_URL_RE = re.compile(r"https?://[^\s)\]}>\"']+", flags=re.IGNORECASE)


@dataclass
class RuntimeConfig:
    agent_model: str
    """Fallback model used when no per-agent override is configured."""
    agent_name_prefix: str
    max_retries: int
    backoff_base_seconds: float
    backoff_max_seconds: float
    social_blacklist: list[str]
    agent_models: dict[str, str] = None  # type: ignore[assignment]
    """Per-agent model overrides keyed by agent key (e.g. ``{"editeur": "mistral-large-latest"}``).
    Lookup order: agent_models[key] → AGENT_DEFINITIONS[key]["default_model"] → agent_model.
    """

    def __post_init__(self) -> None:
        if self.agent_models is None:
            self.agent_models = {}

    def model_for(self, key: str) -> str:
        """Return the effective Mistral model for *key*, respecting override hierarchy."""
        # 1. Explicit per-agent override (e.g. from env var)
        if self.agent_models and key in self.agent_models:
            return self.agent_models[key]
        # 2. Agent-definition default (set in AGENT_DEFINITIONS[key]["default_model"])
        definition = AGENT_DEFINITIONS.get(key, {})
        if definition.get("default_model"):
            return str(definition["default_model"])
        # 3. Global fallback
        return self.agent_model


async def create_agent_async(
    *,
    client: Mistral,
    config: RuntimeConfig,
    key: str,
    handoffs: list[str] | None = None,
) -> str:
    definition = AGENT_DEFINITIONS[key]
    # Resolve the effective model for this specific agent.
    effective_model = config.model_for(key)
    completion_args = {
        "temperature": 0.0,
        "response_format": response_format_for_model(
            definition["schema_name"],
            definition["model_cls"],
        ),
    }

    max_retries = max(0, config.max_retries)
    for attempt in range(max_retries + 1):
        try:
            create_kwargs: dict[str, Any] = {
                "model": effective_model,
                "name": f"{config.agent_name_prefix}-{key}-{os.urandom(3).hex()}",
                "description": definition["description"],
                "instructions": definition["instructions"],
                "tools": definition["tools"],
                "completion_args": completion_args,
            }
            if handoffs:
                create_kwargs["handoffs"] = handoffs

            created = await client.beta.agents.create_async(
                **create_kwargs,
            )
            return str(created.id)
        except Exception as exc:
            should_retry = is_rate_limited_error(exc) and attempt < max_retries
            if not should_retry:
                raise
            wait_seconds = compute_backoff_seconds(
                attempt=attempt,
                base_seconds=config.backoff_base_seconds,
                max_seconds=config.backoff_max_seconds,
            )
            print(
                "[mistral] rate limit detected, retry "
                f"{attempt + 1}/{max_retries} in {wait_seconds:.2f}s"
            )
            await asyncio.sleep(wait_seconds)


async def create_agent_pool(
    *,
    client: Mistral,
    config: RuntimeConfig,
    keys: list[str],
) -> AgentPool:
    """Create one Mistral agent per specialist key and return a pool handle.

    All agent creation calls are dispatched **in parallel** via asyncio.gather,
    cutting startup latency from O(N) sequential round-trips to a single batch.

    Each specialist is called directly via conversations.start — no supervisor
    or handoff layer is involved, which avoids server-side orchestration errors
    and keeps latency low.
    """
    results = await asyncio.gather(
        *[create_agent_async(client=client, config=config, key=key) for key in keys],
        return_exceptions=True,
    )

    # Separate successes from failures so we can clean up on partial failure.
    specialist_ids: dict[str, str] = {}
    created_ids: list[str] = []
    first_exc: Exception | None = None

    for key, result in zip(keys, results):
        if isinstance(result, Exception):
            if first_exc is None:
                first_exc = result
        else:
            specialist_ids[key] = str(result)
            created_ids.append(str(result))
            print(f"  [pool] agent '{key}' created (id={str(result)[:16]}…)")

    if first_exc is not None:
        print(
            f"  [pool] parallel creation failed "
            f"({len(created_ids)}/{len(keys)} succeeded): {first_exc}"
        )
        for agent_id in reversed(created_ids):
            try:
                await client.beta.agents.delete_async(agent_id=agent_id)
            except Exception:
                pass
        raise first_exc

    return AgentPool(
        specialist_ids=specialist_ids,
        created_agent_ids=created_ids,
    )


async def delete_agent_pool(*, client: Mistral, pool: AgentPool) -> None:
    for agent_id in reversed(pool.created_agent_ids):
        try:
            await client.beta.agents.delete_async(agent_id=agent_id)
        except Exception as exc:
            print(f"⚠️ Agent deletion failed ({agent_id}): {exc}")


async def _call_with_retry(
    coro_factory,
    *,
    config: RuntimeConfig,
    label: str,
) -> Any:
    """Run an async factory (no-arg callable returning a coroutine) with rate-limit retry."""
    max_retries = max(0, config.max_retries)
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return await coro_factory()
        except Exception as exc:
            last_exc = exc
            should_retry = is_rate_limited_error(exc) and attempt < max_retries
            if not should_retry:
                raise
            wait_seconds = compute_backoff_seconds(
                attempt=attempt,
                base_seconds=config.backoff_base_seconds,
                max_seconds=config.backoff_max_seconds,
            )
            print(
                f"  [mistral] rate-limit ({label}), "
                f"retry {attempt + 1}/{max_retries} in {wait_seconds:.1f}s — "
                f"{type(exc).__name__}: {exc}"
            )
            await asyncio.sleep(wait_seconds)
    raise last_exc or RuntimeError(f"Call failed after all retries ({label})")


async def start_conversation_with_retry(
    *,
    client: Mistral,
    config: RuntimeConfig,
    agent_id: str,
    prompt: str,
) -> Any:
    """Start a Mistral conversation with automatic retry on rate-limit errors."""
    return await _call_with_retry(
        lambda: client.beta.conversations.start_async(
            agent_id=agent_id,
            inputs=prompt,
        ),
        config=config,
        label=f"agent={agent_id[:16]}… start",
    )


def _response_outputs(response: Any) -> list[dict[str, Any]]:
    """Return the outputs list from a ConversationResponse (object or plain dict)."""
    payload = response.model_dump() if hasattr(response, "model_dump") else response
    if not isinstance(payload, dict):
        return []
    outputs = payload.get("outputs", [])
    return outputs if isinstance(outputs, list) else []


def _response_conversation_id(response: Any) -> str | None:
    payload = response.model_dump() if hasattr(response, "model_dump") else response
    if not isinstance(payload, dict):
        return None
    return payload.get("conversation_id") or None


def _has_final_message_output(outputs: list[dict[str, Any]]) -> bool:
    """Return True if outputs contain a message.output with non-empty content."""
    for output in reversed(outputs):
        if not isinstance(output, dict):
            continue
        if str(output.get("type", "")) != "message.output":
            continue
        content = output.get("content")
        if isinstance(content, str) and content.strip():
            return True
        if isinstance(content, list) and any(
            isinstance(c, dict) and str(c.get("text", "")).strip()
            for c in content
        ):
            return True
    return False


def _has_web_search_execution(outputs: list[dict[str, Any]]) -> bool:
    """Return True if any tool.execution in outputs corresponds to a web_search call.

    Per Mistral docs, tool.execution has ``name`` at the top level (not inside ``info``).
    ``info`` is always an empty dict ``{}`` for the built-in web_search tool.
    """
    for output in outputs:
        if not isinstance(output, dict):
            continue
        if str(output.get("type", "")) != "tool.execution":
            continue
        # Top-level `name` is the canonical field per Mistral Conversations API docs.
        name = str(output.get("name", "")).lower()
        if "web_search" in name or "websearch" in name:
            return True
    return False


def _extract_search_queries(outputs: list[dict[str, Any]]) -> list[str]:
    """Extract the search query strings from tool.execution entries.

    Per Mistral docs, tool.execution entries have ``name`` at top level.
    The search query is in ``arguments`` as a JSON string, also at top level.
    """
    queries: list[str] = []
    for output in outputs:
        if not isinstance(output, dict):
            continue
        if str(output.get("type", "")) != "tool.execution":
            continue
        name = str(output.get("name", "")).lower()
        if "web_search" not in name and "websearch" not in name:
            continue
        args_raw = output.get("arguments", "")
        if not args_raw:
            continue
        try:
            args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
            q = str(args.get("query", "")).strip() if isinstance(args, dict) else ""
            if q:
                queries.append(q)
        except Exception:
            pass
    return queries


async def run_agentic_conversation(
    *,
    client: Mistral,
    config: RuntimeConfig,
    agent_id: str,
    prompt: str,
    max_turns: int = 3,
    requires_search: bool = False,
) -> dict[str, Any]:
    """Run a Mistral conversation and loop via conversations.append until a
    final message.output is produced or max_turns is reached.

    When ``requires_search=True`` (web_search agents), an extra continuation
    turn is triggered if the model produced a message without first calling
    web_search — enforcing at least one search round.

    Returns a plain dict with the accumulated ``outputs`` so that the
    downstream extraction helpers (extract_json_dict_from_response,
    extract_sources_from_conversation) see the full conversation.
    """
    response = await start_conversation_with_retry(
        client=client,
        config=config,
        agent_id=agent_id,
        prompt=prompt,
    )

    accumulated_outputs: list[dict[str, Any]] = list(_response_outputs(response))
    conv_id = _response_conversation_id(response)

    for turn in range(1, max_turns):
        has_output = _has_final_message_output(accumulated_outputs)
        has_search = _has_web_search_execution(accumulated_outputs)

        if has_output and (not requires_search or has_search):
            break  # conversation is complete

        if not conv_id:
            print(f"  [agentic-loop] no conversation_id — stopping at turn {turn}")
            break

        if not has_output:
            continuation = (
                "Please continue your analysis and provide your final structured JSON response."
            )
        else:
            # Output present but web_search was skipped — force a search round.
            continuation = (
                "You MUST call web_search at least once to verify facts before finalising. "
                "Please search now and then provide your final structured JSON response."
            )

        print(
            f"  [agentic-loop] turn {turn + 1}/{max_turns} — "
            f"conv={conv_id[:16]}… "
            f"(has_output={has_output}, has_search={has_search})"
        )

        response = await _call_with_retry(
            lambda: client.beta.conversations.append_async(
                conversation_id=conv_id,
                inputs=continuation,
            ),
            config=config,
            label=f"conv={conv_id[:16]}… append turn {turn + 1}",
        )
        accumulated_outputs.extend(_response_outputs(response))

    return {"conversation_id": conv_id, "outputs": accumulated_outputs, "object": "conversation"}


def _strip_dict_keys(value: Any) -> Any:
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, inner in value.items():
            clean_key = str(key).strip()
            normalized[clean_key] = _strip_dict_keys(inner)
        return normalized
    if isinstance(value, list):
        return [_strip_dict_keys(item) for item in value]
    return value


def extract_json_dict_from_response(response: Any) -> dict[str, Any]:
    payload = response.model_dump() if hasattr(response, "model_dump") else response
    if not isinstance(payload, dict):
        return {}

    outputs = payload.get("outputs", [])
    if not isinstance(outputs, list):
        return {}

    for output in reversed(outputs):
        if not isinstance(output, dict):
            continue
        if str(output.get("type", "")) != "message.output":
            continue
        content = output.get("content")
        candidate_text = ""
        if isinstance(content, str):
            candidate_text = content
        elif isinstance(content, list):
            text_parts: list[str] = []
            for chunk in content:
                if not isinstance(chunk, dict):
                    continue
                if str(chunk.get("type", "")) == "text":
                    text_parts.append(str(chunk.get("text", "")))
            candidate_text = "".join(text_parts)

        candidate_text = candidate_text.strip()
        if not candidate_text:
            continue

        try:
            parsed = json.loads(candidate_text)
            if isinstance(parsed, dict):
                return _strip_dict_keys(parsed)
        except Exception:
            pass

        match = re.search(r"\{.*\}", candidate_text, flags=re.DOTALL)
        if not match:
            continue
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict):
                return _strip_dict_keys(parsed)
        except Exception:
            continue

    return {}


def _collect_urls_from_text(text: str, collected: list[dict[str, str]]) -> None:
    if not isinstance(text, str) or not text.strip():
        return
    for match in _HTTP_URL_RE.findall(text):
        url = str(match).rstrip(".,;:!?)]}")
        if not is_valid_http_url(url):
            continue
        collected.append(
            {
                "url": url,
                "title": "",
                "snippet": text.strip()[:480],
            }
        )


def extract_sources_from_conversation(
    *,
    response: Any,
    social_blacklist: list[str],
    max_sources: int = 3,
) -> list[dict[str, str]]:
    """Extract source URLs from a conversation response.

    Two complementary extraction paths, per Mistral Conversations API docs:

    1. **tool_reference chunks** inside ``message.output.content`` (list form) —
       each chunk has ``type="tool_reference"``, ``url``, ``title``, ``source``.
       Only present in free-text responses (no ``response_format`` constraint).

    2. **URL regex scan** of the raw ``message.output.content`` string —
       used when ``response_format: json_schema`` is active and content is a
       plain JSON string. In that mode the model writes URLs in its ``sources``
       field, which the regex catches.

    ``tool.execution.info`` is always ``{}`` for the built-in web_search tool
    and is never a useful source of URLs.
    """
    payload = response.model_dump() if hasattr(response, "model_dump") else response
    if not isinstance(payload, dict):
        return []
    outputs = payload.get("outputs", [])
    if not isinstance(outputs, list):
        return []

    candidates: list[dict[str, str]] = []
    for output in outputs:
        if not isinstance(output, dict):
            continue
        output_type = str(output.get("type", ""))
        if output_type != "message.output":
            continue
        content = output.get("content")
        if isinstance(content, str):
            # JSON schema mode — content is a plain JSON string.
            # URLs written into the model's `sources` field get found here.
            _collect_urls_from_text(content, candidates)
        elif isinstance(content, list):
            # Free-text mode — content is interleaved text + tool_reference chunks.
            for chunk in content:
                if not isinstance(chunk, dict):
                    continue
                chunk_type = str(chunk.get("type", ""))
                if chunk_type == "tool_reference":
                    # Per docs: {type, tool, title, url, source}
                    url = str(chunk.get("url", "")).strip()
                    if not is_valid_http_url(url):
                        continue
                    candidates.append({
                        "url": url,
                        "title": str(chunk.get("title", "")).strip(),
                        "snippet": str(chunk.get("title", "")).strip()[:480],
                    })
                elif chunk_type == "text":
                    _collect_urls_from_text(str(chunk.get("text", "")), candidates)

    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for candidate in candidates:
        url = str(candidate.get("url", "")).strip()
        if not is_valid_http_url(url) or url in seen:
            continue
        host = normalized_host(url)
        if any(host == blocked or host.endswith(f".{blocked}") for blocked in social_blacklist):
            continue
        seen.add(url)
        deduped.append(
            {
                "url": url,
                "organization": domain_to_organization(url),
                "title": str(candidate.get("title", "")).strip(),
                "snippet": str(candidate.get("snippet", "")).strip()[:480],
            }
        )
    return deduped[:max_sources]


# Keys of agents that require web_search — used to trigger the agentic loop.
_SEARCH_AGENT_KEYS: frozenset[str] = frozenset(
    key
    for key, definition in AGENT_DEFINITIONS.items()
    if any(str(t.get("type", "")) == "web_search" for t in definition.get("tools", []))
)


async def run_task(
    *,
    client: Mistral,
    config: RuntimeConfig,
    pool: AgentPool,
    specialist_key: str,
    specialist_prompt: str,
    max_turns: int = 3,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Call a specialist agent and return (parsed_json, sources).

    For agents with web_search tools, runs a proper agentic loop via
    run_agentic_conversation: it continues the conversation (up to max_turns)
    until a final message.output is produced AND at least one web_search was
    executed — enforcing real grounded research rather than training-data recall.
    """
    if specialist_key not in pool.specialist_ids:
        available = ", ".join(sorted(pool.specialist_ids.keys()))
        raise ValueError(
            f"Unknown specialist '{specialist_key}'. Available: [{available}]"
        )

    agent_id = pool.specialist_ids[specialist_key]
    requires_search = specialist_key in _SEARCH_AGENT_KEYS
    try:
        response = await run_agentic_conversation(
            client=client,
            config=config,
            agent_id=agent_id,
            prompt=specialist_prompt,
            max_turns=max_turns,
            requires_search=requires_search,
        )
    except Exception as exc:
        print(
            f"  ERROR [{specialist_key}] agent_id={agent_id[:16]}… — "
            f"{type(exc).__name__}: {exc}"
        )
        raise

    parsed = extract_json_dict_from_response(response)

    # ── Debug: search queries made ──────────────────────────────────────────
    outputs = response.get("outputs", []) if isinstance(response, dict) else []
    search_queries = _extract_search_queries(outputs)
    if search_queries:
        for q in search_queries:
            print(f"  [{specialist_key}] 🔍 searched: {q!r}")
    elif requires_search:
        print(f"  [{specialist_key}] ⚠️  no web_search call detected in outputs")

    # ── Debug: inline sources in JSON output ───────────────────────────────
    inline_sources_raw = parsed.get("sources", [])
    valid_inline: list[dict] = []
    if isinstance(inline_sources_raw, list):
        valid_inline = [
            s for s in inline_sources_raw
            if isinstance(s, dict) and is_valid_http_url(str(s.get("url", "")))
        ]
        if valid_inline:
            print(f"  [{specialist_key}] ✅ {len(valid_inline)} inline source(s) in JSON:")
            for s in valid_inline:
                print(f"    · {s.get('organization', '?')} — {s.get('url', '')}")
        elif requires_search:
            print(f"  [{specialist_key}] ⚠️  model returned no valid URLs in 'sources' field")
    # ── Debug: conversation-extracted sources (fallback) ──────────────────
    sources = extract_sources_from_conversation(
        response=response,
        social_blacklist=config.social_blacklist,
    )
    if sources:
        print(f"  [{specialist_key}] 📎 {len(sources)} source(s) from conversation outputs (fallback)")
    elif requires_search and not valid_inline:
        print(f"  [{specialist_key}] ❌ no sources found — Mistral tool.execution.info is always {{}}")

    if not parsed:
        print(
            f"  WARNING [{specialist_key}] empty JSON from agent_id={agent_id[:16]}…"
        )
    return parsed, sources
