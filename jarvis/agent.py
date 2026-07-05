"""
JarvisAgent — the central agent entity.

Owns conversation history and coordinates the full request/response pipeline.
The REPL and any other interface interact with Jarvis exclusively through this class.
"""

from pathlib import Path

from .config.manager import ConfigManager
from .llm.engine import LLMEngine
from .llm.gateway import LLMGateway
from .pipeline.invariants import InvariantChecker
from .pipeline.orchestrator import Orchestrator
from .pipeline.runner import LLMStageRunner
from .pipeline.swarm import SwarmStageRunner
from .pipeline.parallel import ParallelExecutionRunner
from .pipeline.stages import STAGE_AGENTS
from .memory.coordinator import MemoryCoordinator, COMPRESSION_INTERVAL
from .personalization.service import PersonalizationService
from .prompt_builder.builder import (
    build_system_prompt,
    build_strategy_prompt,
    build_attachments_block,
    build_rag_block,
    build_prompt_generation_request,
)
from .indexing import IndexPipeline, IndexStore, make_embedder
from .rag.cite import build_citations, idk_message, strip_trailing_citations
from .conversation.service import ConversationService
from .session.store import SessionStore
from .session.task_store import TaskStore
from .session.profile_store import ProfileStore
from .session.invariant_store import InvariantStore




# Re-exported for commands.py (thread-summary view) — the compression cadence
# now lives with the MemoryCoordinator.
_COMPRESSION_INTERVAL: int = COMPRESSION_INTERVAL

# API-call labels that count as the user-facing answer (for context-fill metric).
_ANSWER_LABELS: frozenset[str] = frozenset({"final_answer", "invariant_resolution"})


class JarvisAgent:
    """
    Conversational agent that maintains history across turns.

    Each call to chat() appends the user turn and assistant response to the
    conversation history, which is included in every subsequent API request so
    the model retains full context of the dialogue.

    Conversation history is organized into named threads. On startup the most
    recently used thread is auto-resumed. New threads can be created and existing
    threads loaded via the history commands.

    Context strategy (set via config context_strategy) controls how history is
    presented to the model. It may only be changed on an empty thread.

      none          — full history sent verbatim (default)
      compression   — rolling summary replaces older turns
      sliding_window — only the most recent N turns are sent
      sticky_facts  — a structured facts block is prepended to full history
      topics        — automatic topic routing; context is scoped to the active topic
    """

    def __init__(
        self,
        client: LLMEngine,
        config_manager: ConfigManager,
        tool_provider=None,
    ) -> None:
        # Every model call in the app flows through the single gateway (accounting,
        # and later retries/caching live there). Nothing below touches the engine
        # directly any more. The optional tool_provider (an MCPToolProvider) makes
        # MCP tools available on tool-enabled calls (chat answers + stage turns).
        self._tool_provider = tool_provider
        self._gateway = LLMGateway(client, tool_provider=tool_provider)
        self._config = config_manager
        self._memory = MemoryCoordinator(self._gateway, config_manager)
        self._invariant_checker = InvariantChecker(self._gateway)
        # The active chat thread and its lifecycle live in ConversationService;
        # this agent reads/writes self._conversation.state.
        self._conversation = ConversationService()
        self._tasks = TaskStore()
        self._profile = ProfileStore()
        self._invariants = InvariantStore()
        self._personalization = PersonalizationService(self._gateway, config_manager, self._profile)
        # The orchestrator drives the task FSM through a StageRunner; it no longer
        # depends on this agent (the old run_turn callback is gone).
        self._stage_runner = LLMStageRunner(
            self._gateway, config_manager, self._memory,
            self._profile, self._invariants, self._invariant_checker, self._tasks,
        )
        # Stage runners are layered onto the base seam, each overriding one stage and
        # delegating the rest, so the FSM and the rest of the app are untouched:
        #   • SwarmStageRunner — opt-in reviewer swarm on `validation` (review_agents>1)
        #   • ParallelExecutionRunner — opt-in parallel `execution` (execution_agents>1)
        # Both default to the original single-turn behaviour and token cost.
        self._stage_runner = SwarmStageRunner(
            self._gateway, config_manager, self._stage_runner, self._tasks,
        )
        self._stage_runner = ParallelExecutionRunner(
            self._gateway, config_manager, self._stage_runner, self._tasks,
        )
        self._orchestrator = Orchestrator(STAGE_AGENTS, self._tasks, self._stage_runner)

        # Working-memory task linked to the active thread (None when unlinked).
        self._active_task: dict | None = None

        # Cross-encoder rerankers are expensive to construct (model load), so cache
        # one per rerank kind for reuse across turns. Populated lazily.
        self._reranker_cache: dict[str, object] = {}

        # Prompt tokens from the most recent API call — represents how much of
        # the context window is currently in use (system + full history + last user msg).
        self._last_context_tokens: int = 0

        self._session = SessionStore()
        # Tasks are standalone workspaces entered via `task start`/`task new`; they
        # are not tied to threads, so the session starts in chat mode (no task).

    # ── Public API ────────────────────────────────────────────────────────────

    def chat(self, user_input: str) -> str:
        """Send a message and return the assistant's response (with any notices)."""
        response_text, notices = self._run_turn(user_input)
        return "\n\n".join([response_text] + notices)

    def _run_turn(self, user_input: str, *, extra_system: str | None = None) -> tuple[str, list[str]]:
        """Core request/response cycle. Returns (response_text, notices).

        Builds the full message list as [system] + working-memory + history +
        [current turn], runs the completion (+ invariant check), appends the
        turn to history, runs context-strategy background work, and persists.
        """
        params = self._config.runtime
        strategy = params.get("context_strategy", "none")
        api_calls: list[dict] = []
        generated_prompt: str | None = None
        st = self._conversation.state  # the active thread's mutable state

        # Personalisation + invariants go into every system prompt, alongside any
        # active task's stage instructions.
        profile = self._profile.read_active()
        invariants = self._invariants.read_active()
        system_prompt = build_system_prompt(
            params, self._active_task, profile, invariants
        )
        # Orchestrator-driven stage runs add their marker protocol here, so it is
        # present only on autorun and never pollutes free-form chat replies.
        if extra_system:
            system_prompt = f"{system_prompt}\n\n{extra_system}"

        if params.get("solution_strategy") == "prompt_generation":
            # Two-stage pipeline: stage 1 generates an optimised prompt for the
            # task; stage 2 sends that prompt as the actual user message.
            stage1_messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": build_prompt_generation_request(user_input)},
            ]
            stage1_params = {"model": params["model"]} if "model" in params else {}
            stage1 = self._gateway.complete(
                stage1_messages, stage1_params,
                label="prompt_generation_stage1", api_calls=api_calls,
            )
            generated_prompt = stage1.text.strip()
            final_user_message = generated_prompt
        else:
            final_user_message = build_strategy_prompt(params, user_input)

        # Topics strategy: classify the message into a topic before context assembly
        # so context can be scoped to the relevant topic's history.
        active_topic: str | None = None
        if strategy == "topics":
            active_topic, routing_record = self._memory.route_topic(user_input, st.topic_summaries)
            api_calls.append(routing_record)

        # system + attached task results + context-strategy history + user turn.
        # Threads and tasks are independent: a chat turn never carries a live task's
        # state. Finished task results only enter a thread when explicitly attached
        # (`task attach`, or automatically when a task completes), injected here.
        attach_block = build_attachments_block(st.attachments)

        # Retrieval-augmented generation: when enabled, retrieve chunks from the
        # configured local index and inject them ahead of history (the same slot
        # as attachments) so the answer is grounded in the knowledge base and
        # cites it. Failures (no index, embedder down) degrade to a normal answer
        # with a notice rather than breaking the turn.
        rag_block: list[dict] = []
        rag_notice: str | None = None
        rag_results: list[dict] = []
        idk_response: str | None = None
        if params.get("rag"):
            rag_block, rag_results, idk_response, rag_notice, _rag_info = self._rag_decide(
                user_input, params
            )

        invariant_notice: str | None = None
        if idk_response is not None:
            # Strict mode + weak context: deterministic "I don't know" — skip the
            # model entirely (no cost). Still recorded as a normal turn below.
            response_text = idk_response
            finish_reason = "stop"
        else:
            messages = (
                [{"role": "system", "content": system_prompt}]
                + attach_block
                + rag_block
                + self._memory.build_chat_context(
                    st.history,
                    active_topic=active_topic,
                    summary=st.summary,
                    summary_covered_turns=st.summary_covered_turns,
                    facts=st.facts,
                    topic_summaries=st.topic_summaries,
                )
                + [{"role": "user", "content": final_user_message}]
            )

            completion = self._gateway.complete(
                messages, params, label="final_answer", api_calls=api_calls, use_tools=True
            )
            response_text = completion.text.strip()
            finish_reason = completion.finish_reason

            # Invariant validation (the "requirements linter"): when invariants are
            # defined, check the reply in code and rework it once on a violation.
            if invariants:
                response_text, invariant_notice, completion = self._invariant_checker.validate(
                    invariants, messages, response_text, completion, params, api_calls
                )
                finish_reason = completion.finish_reason

            # Mandatory citations: append verbatim Sources + Quotes for the chunks
            # the grounded answer used (hybrid — the model marked them with [n]).
            if rag_results and params.get("rag_cite", True):
                appendix = build_citations(rag_results, response_text, user_input)
                if appendix:
                    body = strip_trailing_citations(response_text)
                    response_text = f"{body}\n\n{appendix}"

        # Persist user/assistant turn; tag with topic when the topics strategy is active.
        user_msg: dict = {"role": "user", "content": user_input}
        asst_msg: dict = {"role": "assistant", "content": response_text}
        if active_topic:
            user_msg["topic"] = active_topic
            asst_msg["topic"] = active_topic
        st.history.append(user_msg)
        st.history.append(asst_msg)

        # Context-strategy background work (compression / facts / topic summaries).
        bg = self._memory.run_background(
            history=st.history,
            active_topic=active_topic,
            summary=st.summary,
            summary_covered_turns=st.summary_covered_turns,
            facts=st.facts,
            topic_summaries=st.topic_summaries,
        )
        if bg.summary is not None:
            st.summary = bg.summary
        if bg.summary_covered_turns is not None:
            st.summary_covered_turns = bg.summary_covered_turns
        if bg.facts is not None:
            st.facts = bg.facts
        if bg.topic_summary is not None:
            topic_name, topic_summary = bg.topic_summary
            st.topic_summaries[topic_name] = topic_summary
        extra_notice = bg.notice
        if bg.record:
            api_calls.append(bg.record)

        # Behaviour log (global, separate from chat threads): record this
        # interaction's shape so the profile refiner can learn style preferences.
        self._personalization.record_interaction(
            user_input=user_input,
            response_chars=len(response_text),
            solution_strategy=params.get("solution_strategy", "direct"),
            context_strategy=strategy,
            had_task=self._active_task is not None,
        )
        profile_notice = self._personalization.maybe_nudge()

        # Accounting: every LLM call this turn is billed; the last answer-type
        # call reflects the shown response and its context-window fill. A strict
        # "I don't know" turn makes no LLM call (api_calls empty) → zero cost.
        native_ctx: int | None = None
        if api_calls:
            answer_calls = [c for c in api_calls if c["label"] in _ANSWER_LABELS]
            last_usage = (answer_calls or api_calls)[-1]["response"].get("usage") or {}
            # native_tokens_total is the model-side count after chat-template expansion;
            # falls back to total_tokens when the provider does not return native counts.
            native_ctx = last_usage.get("native_tokens_total") or last_usage.get("total_tokens") or None
        self._last_context_tokens = native_ctx or 0

        billing_tokens = sum((c["response"].get("usage") or {}).get("total_tokens") or 0 for c in api_calls)
        turn_cost = sum((c.get("cost") or {}).get("total_usd") or 0.0 for c in api_calls)
        st.total_tokens += billing_tokens
        st.total_cost += turn_cost
        turn_index = len(st.history) // 2
        # native_ctx stored as 4th element so the context chart can use persisted data.
        st.cost_series.append([turn_index, turn_cost, st.total_cost, native_ctx])

        self._conversation.save()

        self._session.add(
            user_input=user_input,
            config_snapshot=dict(params),
            response=response_text,
            finish_reason=finish_reason,
            api_calls=api_calls,
            generated_prompt=generated_prompt,
        )

        notices = [n for n in (rag_notice, invariant_notice, extra_notice, profile_notice) if n]
        return response_text, notices

    def _rag_results(
        self, query: str, index_name: str | None, k: int
    ) -> tuple[list[dict], str | None]:
        """Retrieve top-k chunks for a question. Returns (results, error).

        The query is embedded with the index's own provider/model (from its
        header) so it matches how the index was built. ``error`` is a short reason
        string when retrieval can't run (no index name, index missing, embedder
        unreachable); callers decide whether to degrade or raise.
        """
        if not index_name:
            return [], "no rag_index is set"
        try:
            store = IndexStore()
            header = store.load_header(index_name)
            if header is None:
                return [], f"index '{index_name}' not found"
            embedder = make_embedder(header.get("provider"), header.get("model"))
            return IndexPipeline(embedder, store).search(index_name, query, k), None
        except Exception as exc:  # noqa: BLE001 — caller degrades or reports
            return [], f"retrieval failed ({exc})"

    def _reranker(self, kind: str) -> tuple[object | None, str | None]:
        """Return a cached reranker for ``kind`` (or None), plus an error string.

        Constructing a cross-encoder loads a model, so instances are cached per
        kind. A failure (e.g. sentence-transformers not installed) returns
        (None, message) and the caller degrades to the un-reranked order.
        """
        if kind in ("off", None, ""):
            return None, None
        if kind in self._reranker_cache:
            return self._reranker_cache[kind], None
        try:
            from .rag.enhance import make_reranker
            reranker = make_reranker(kind)
        except Exception as exc:  # noqa: BLE001 — degrade, don't crash retrieval
            return None, f"reranker '{kind}' unavailable ({exc})"
        self._reranker_cache[kind] = reranker
        return reranker, None

    def _retrieve_enhanced(
        self, question: str, index_name: str | None, params: dict
    ) -> tuple[list[dict], list[dict], str | None, dict]:
        """Full retrieval with the second stage. Returns (raw, enhanced, error, info).

        ``raw`` is the first-stage top-K (before filtering); ``enhanced`` is after
        query rewrite (applied to the search), relevance filter, and optional
        cross-encoder rerank. ``info`` carries the rewritten query, the rerank
        kind, and any degradation notes (for notices and the eval).
        """
        from .rag.enhance import enhance_results, rewrite_query

        info: dict = {"rewritten": None, "rerank": params.get("rag_rerank", "off"), "notes": []}
        search_query = question
        if params.get("rag_rewrite"):
            try:
                search_query = rewrite_query(self._gateway, question, params) or question
                info["rewritten"] = search_query
            except Exception as exc:  # noqa: BLE001 — rewrite is best-effort
                info["notes"].append(f"query rewrite failed ({exc})")

        k = int(params.get("rag_k", 5))
        raw, error = self._rag_results(search_query, index_name, k)
        if error:
            return [], [], error, info

        reranker, rerank_err = self._reranker(params.get("rag_rerank", "off"))
        if rerank_err:
            info["notes"].append(rerank_err)
        enhanced = enhance_results(
            raw,
            min_score=params.get("rag_min_score"),
            top_n=params.get("rag_top_n"),
            reranker=reranker,
            question=search_query,
        )
        return raw, enhanced, None, info

    def _rag_decide(
        self, question: str, params: dict
    ) -> tuple[list[dict], list[dict], str | None, str | None, dict]:
        """Decide how a RAG turn is handled. Returns
        ``(rag_block, results, idk_text, notice, info)``.

        - retrieval error / no index → answer without grounding (block empty).
        - **strong** context (best cosine ≥ ``rag_idk_threshold``) → grounded block
          + the chunks to cite.
        - **weak** context: strict mode (``rag_strict``) → ``idk_text`` set (the
          deterministic "I don't know"); augmented (default) → answer without
          grounding. This is what stops the gate from hijacking off-topic chat.
        """
        index_name = params.get("rag_index")
        raw, enhanced, error, info = self._retrieve_enhanced(question, index_name, params)
        if error:
            if not index_name:
                return [], [], None, "RAG is on but no rag_index is set — answering without it. Set one: config set rag_index <name>", info
            return [], [], None, f"RAG: {error} — answering without it.", info

        threshold = params.get("rag_idk_threshold") or 0.0
        best = max((r.get("score", 0.0) for r in enhanced), default=0.0)
        if not enhanced or best < threshold:
            if params.get("rag_strict"):
                idk = idk_message(question, best, threshold)
                return [], [], idk, f"RAG: weak context (best {best:.2f} < {threshold:.2f}) — I don't know (strict).", info
            reason = "no matching chunks" if not enhanced else f"best match {best:.2f} < {threshold:.2f}"
            return [], [], None, (
                f"RAG: nothing relevant enough in '{index_name}' ({reason}) — "
                "answered from general knowledge (no sources)."
            ), info

        # Strong context → ground and cite.
        sources: list[str] = []
        for r in enhanced:
            fn = r["metadata"].get("filename", "?")
            if fn not in sources:
                sources.append(fn)
        detail = ""
        if len(enhanced) != len(raw):
            detail += f" (filtered {len(raw)}→{len(enhanced)})"
        if info.get("rewritten"):
            detail += f" [rewritten: {info['rewritten']}]"
        if info.get("rerank") not in ("off", None):
            detail += f" [rerank: {info['rerank']}]"
        notice = (
            f"RAG: grounded in {len(enhanced)} chunk(s) from '{index_name}' — "
            f"{', '.join(sources)}{detail}"
        )
        for note in info.get("notes", []):
            notice += f"\n  · {note}"
        return build_rag_block(enhanced), enhanced, None, notice, info

    def grounded_answer(
        self, question: str, index_name: str | None = None, k: int | None = None
    ) -> dict:
        """One-shot grounded answer with mandatory citations, or the strict IDK /
        augmented un-grounded fallback. Returns a dict with keys: text, grounded,
        idk, results, notice. Used by `rag ask`, `compare_rag`, and the eval."""
        params = dict(self._config.runtime)
        if k is not None:
            params["rag_k"] = k
        if index_name is not None:
            params["rag_index"] = index_name
        block, results, idk_text, notice, _info = self._rag_decide(question, params)
        if idk_text is not None:
            return {"text": idk_text, "grounded": False, "idk": True, "results": [], "notice": notice}
        if block:
            answer = self.answer(question, context_blocks=block)
            if params.get("rag_cite", True):
                appendix = build_citations(results, answer, question)
                if appendix:
                    answer = f"{strip_trailing_citations(answer)}\n\n{appendix}"
            return {"text": answer, "grounded": True, "idk": False, "results": results, "notice": notice}
        return {"text": self.answer(question), "grounded": False, "idk": False, "results": [], "notice": notice}

    # ── One-shot A/B answering (no thread mutation) ─────────────────────────────

    def answer(self, question: str, *, context_blocks: list[dict] | None = None) -> str:
        """Answer a question once, outside any thread (history is not touched).

        Used by the with/without-RAG comparison so both modes are identical except
        for the injected ``context_blocks``. Intentionally skips solution-strategy
        wrapping and the invariant rework loop to keep the A/B clean and cheap.
        """
        params = self._config.runtime
        profile = self._profile.read_active()
        invariants = self._invariants.read_active()
        system_prompt = build_system_prompt(params, None, profile, invariants)
        messages = (
            [{"role": "system", "content": system_prompt}]
            + (context_blocks or [])
            + [{"role": "user", "content": question}]
        )
        return self._gateway.complete(messages, params, label="rag_compare").text.strip()

    def judge_quote_support(self, answer: str, quotes: str) -> bool:
        """LLM judge: are the answer's claims supported by its cited quotes?

        Used by the eval's meaning-match check (one model call). Delegates to
        jarvis.rag.judge, running through this agent's gateway and model."""
        from .rag.judge import judge_supported
        return judge_supported(
            self._gateway, answer, quotes, model=self._config.runtime.get("model")
        )

    def rag_search(self, question: str, index_name: str | None, k: int = 5) -> list[dict]:
        """Public retrieval seam: top-k scored chunks for a question (raises on error)."""
        results, error = self._rag_results(question, index_name, k)
        if error:
            raise RuntimeError(error)
        return results

    def _params_with_k(self, k: int | None) -> dict:
        params = dict(self._config.runtime)
        if k is not None:
            params["rag_k"] = k
        return params

    def rag_retrieve(
        self, question: str, index_name: str | None, k: int | None = None
    ) -> tuple[list[dict], list[dict], str | None]:
        """Public: (raw, enhanced, error) — first-stage top-K vs after the second
        stage (filter/rerank). Used by the eval to measure precision before/after.
        Second-stage settings come from the active config."""
        raw, enhanced, error, _info = self._retrieve_enhanced(
            question, index_name, self._params_with_k(k)
        )
        return raw, enhanced, error

    def rag_retrieve_detailed(
        self, question: str, index_name: str | None, k: int | None = None
    ) -> tuple[list[dict], list[dict], str | None, dict]:
        """Like ``rag_retrieve`` but also returns the ``info`` dict (rewritten
        query, rerank kind, degradation notes) — for the `rag ask` display."""
        return self._retrieve_enhanced(question, index_name, self._params_with_k(k))

    def compare_rag(
        self, question: str, index_name: str | None, k: int = 5
    ) -> tuple[str, str | None, list[dict], str | None]:
        """Answer a question both ways. Returns (plain, grounded, results, error).

        ``plain`` is the model's un-grounded answer. ``grounded`` is the composed
        RAG answer (with mandatory Sources + Quotes when it grounds, or the strict
        IDK / augmented fallback). ``results`` are the chunks it cited.
        """
        plain = self.answer(question)
        g = self.grounded_answer(question, index_name=index_name, k=k)
        return plain, g["text"], g["results"], None

    def reset_history(self) -> None:
        """Clear the active thread's messages (thread record is preserved)."""
        self._conversation.reset()
        self._last_context_tokens = 0

    def new_thread(self, name: str | None = None) -> str:
        """Start a new empty thread. Returns the new thread name."""
        self._last_context_tokens = 0
        return self._conversation.new_thread(name)

    def load_thread(self, query: str) -> bool:
        """Switch to an existing thread by name or id prefix. True on success."""
        ok = self._conversation.load_thread(query)
        if ok:
            self._last_context_tokens = 0  # unknown until the next API call
        return ok

    def delete_thread(self, query: str) -> str:
        """Delete a thread by name or id prefix, auto-switching if it was active."""
        message = self._conversation.delete_thread(query)
        self._last_context_tokens = 0
        return message

    def rename_thread(self, new_name: str) -> str:
        """Rename the active thread. Returns the new name."""
        return self._conversation.rename_thread(new_name)

    def list_threads(self) -> list[dict]:
        """Return all threads sorted by last-used time (newest first)."""
        return self._conversation.list_threads()

    @property
    def thread_name(self) -> str:
        return self._conversation.state.name

    @property
    def thread_id(self) -> str:
        return self._conversation.state.id

    @property
    def history(self) -> list[dict]:
        """A copy of the current conversation history (alternating user/assistant turns)."""
        return list(self._conversation.state.history)

    @property
    def last_context_tokens(self) -> int:
        """total_tokens from the most recent API call — current context window fill.

        Uses total_tokens (prompt + completion) because the current completion
        becomes part of the history sent on the next turn.
        """
        return self._last_context_tokens

    @property
    def thread_total_tokens(self) -> int:
        """Cumulative total tokens billed across all turns in this thread."""
        return self._conversation.state.total_tokens

    @property
    def thread_total_cost(self) -> float:
        return self._conversation.state.total_cost

    @property
    def cost_series(self) -> list:
        """Per-turn cost series: list of [turn_index, request_cost_usd, cumulative_cost_usd]."""
        return list(self._conversation.state.cost_series)

    @property
    def summary(self) -> str | None:
        """Current rolling summary text, or None if no compression has occurred."""
        return self._conversation.state.summary

    @property
    def summary_covered_turns(self) -> int:
        """Number of turns currently captured by the rolling summary."""
        return self._conversation.state.summary_covered_turns

    @property
    def facts(self) -> str | None:
        """Current sticky facts text, or None if no facts have been extracted."""
        return self._conversation.state.facts

    @property
    def topic_summaries(self) -> dict[str, str]:
        """Current per-topic summaries dict. Empty if the topics strategy has not run."""
        return dict(self._conversation.state.topic_summaries)

    # ── Working memory (tasks) ─────────────────────────────────────────────────

    @property
    def active_task(self) -> dict | None:
        """The task workspace currently entered (independent of threads), or None."""
        return dict(self._active_task) if self._active_task else None

    def create_task(self, name: str | None = None) -> dict:
        """Create a standalone task workspace and enter it."""
        task = self._tasks.new_task(name)
        self._active_task = task
        return task

    def start_task(self, query: str) -> dict | None:
        """Enter an existing task workspace (independent of the current thread)."""
        task = self._tasks.find(query)
        if task is None:
            return None
        self._active_task = task
        return task

    def exit_task(self) -> str | None:
        """Leave the current task workspace, returning to chat. The task is preserved."""
        if self._active_task is None:
            return None
        name = self._active_task["name"]
        self._active_task = None
        return name

    def delete_task(self, query: str) -> str | None:
        """Delete a task file and detach its result from every thread.

        A finished task's deliverable can be pinned into any thread's context
        (`task attach`, or automatically on completion). Deleting the task must also
        remove those attachments, so its result can't linger as a dangling pin on the
        active thread or any thread on disk.
        """
        task = self._tasks.find(query)
        if task is None:
            return None
        self._tasks.delete(task["id"])
        self._conversation.purge_attachment(task["id"])
        if self._active_task and self._active_task["id"] == task["id"]:
            self._active_task = None
        return task["name"]

    def list_tasks(self) -> list[dict]:
        return self._tasks.list_all()

    def pipeline_step(self, extra_instruction: str = ""):
        """Run one turn of the active task's pipeline via the orchestrator.

        Returns a StageResult (or None when there is no active task). The
        interactive driver loops this, handling gates (questions and Confirm/
        Reject approvals) between calls. extra_instruction carries a user's
        answer or rework feedback into the next turn's entry message.
        """
        if self._active_task is None:
            return None
        return self._orchestrator.step(self._active_task, extra_instruction)

    def save_task_result(self, text: str):
        """Persist the active task's final deliverable to a file artifact. Returns the path."""
        if self._active_task is None:
            return None
        return self._tasks.save_result(self._active_task, text)

    def advance_to(self, target: str) -> str | None:
        """Move the active task to target (code-enforced). A no-op if already there.

        Used by the driver to apply an approval decision: Confirm advances to the
        gate's confirm_target; Reject moves to its reject_target (which may be the
        current stage, i.e. rework in place).
        """
        if self._active_task is None:
            return None
        if self._active_task["stage"] == target:
            return target  # rework in place — stay in the stage
        # advance_stage enforces ALLOWED_TRANSITIONS and raises on an illegal jump.
        # In normal flow the target always comes from the stage verdict (so it is
        # valid), but guard the user-reachable path so a bad target surfaces as a
        # clean None rather than crashing the REPL — the FSM stays where it was.
        try:
            return self._tasks.advance_stage(self._active_task, target)
        except ValueError:
            return None

    # ── Task ↔ thread attachments ───────────────────────────────────────────────

    def attach_task(self, query: str) -> str | None:
        """Pin a finished task's result to the active thread as reference context.

        Returns the task name, or None if the task is unknown or has no result yet.
        """
        task = self._tasks.find(query)
        if task is None:
            return None
        summary, content = self._task_deliverable(task)
        if content is None:
            return None
        self._conversation.attach(task["id"], task["name"], summary, content)
        return task["name"]

    def detach_task(self, query: str) -> str | None:
        """Remove a task's result from the active thread. Returns its name, or None."""
        return self._conversation.detach(query)

    def list_attachments(self) -> list[dict]:
        """Task results currently attached to the active thread."""
        return self._conversation.attachments()

    def finish_active_task(self, summary: str, deliverable: str) -> str | None:
        """On completion: attach the deliverable to the active thread and exit the task.

        This is what makes a finished task enrich the thread it was worked from,
        while keeping the two surfaces otherwise independent. Returns the task name.
        """
        task = self._active_task
        if task is None:
            return None
        self._conversation.attach(task["id"], task["name"], summary, deliverable)
        self._active_task = None
        return task["name"]

    @staticmethod
    def _task_deliverable(task: dict) -> tuple[str, str | None]:
        """Best available (summary, deliverable) for a task: result file, else done output."""
        path = task.get("result_path")
        if path and Path(path).exists():
            try:
                content = Path(path).read_text(encoding="utf-8")
            except OSError:
                content = None
            if content:
                first = next((ln.strip() for ln in content.splitlines() if ln.strip()), task["name"])
                return first[:200], content
        done = (task.get("stage_outputs") or {}).get("done")
        if done:
            first = next((ln.strip() for ln in done.splitlines() if ln.strip()), task["name"])
            return first[:200], done
        return task["name"], None

    # ── Invariants (single global hard-rule file) ───────────────────────────────

    def read_invariants(self) -> str | None:
        return self._invariants.read()

    def invariants_exist(self) -> bool:
        return self._invariants.exists()

    def init_invariants(self) -> bool:
        """Scaffold invariants.md from the template if missing. True if created."""
        return self._invariants.init()

    def invariants_path(self):
        """Filesystem path of invariants.md (for editing in $EDITOR)."""
        return self._invariants.path_for()

    # ── Profile (system-managed: onboarding + personalisation) ───────────────────
    # Thin facade over PersonalizationService so the REPL keeps a stable surface.

    def profile_exists(self) -> bool:
        return self._personalization.exists()

    def read_profile(self) -> str | None:
        return self._personalization.read()

    def onboard_profile(self, style: str, constraints: str, context: str) -> None:
        """Write profile.md from the onboarding interview answers."""
        self._personalization.onboard(style, constraints, context)

    def skip_onboarding(self) -> None:
        """Write a minimal default profile when the user skips the interview."""
        self._personalization.skip_onboarding()

    def propose_profile_style(self) -> tuple[str | None, str | None, str | None]:
        """Propose a new Style section from recent behaviour (see PersonalizationService)."""
        return self._personalization.propose_style()

    def apply_profile_style(self, new_style: str) -> bool:
        """Overwrite only the Style section of profile.md with new_style."""
        return self._personalization.apply_style(new_style)

    def get_context_window(self, model_id: str) -> int | None:
        return self._gateway.get_context_window(model_id)

    @property
    def session(self) -> SessionStore:
        return self._session

    @property
    def tool_provider(self):
        """The live MCPToolProvider, or None when MCP tools aren't enabled."""
        return self._tool_provider
