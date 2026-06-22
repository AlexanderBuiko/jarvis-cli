# Jarvis — Class & Sequence Diagrams (post-refactor)

Reflects the current code after the KB-alignment refactor: `JarvisAgent` as a thin
composition-root facade, `LLMGateway` as the single model chokepoint, the
`MemoryCoordinator` / `ConversationService` / `PersonalizationService` services,
and the `Orchestrator → StageRunner → StageAgent` task pipeline.

---

## Class Diagram 1 — Composition root & services

```mermaid
classDiagram
    class JarvisAgent {
        -LLMGateway _gateway
        -ConfigManager _config
        -MemoryCoordinator _memory
        -InvariantChecker _invariant_checker
        -ConversationService _conversation
        -TaskStore _tasks
        -ProfileStore _profile
        -InvariantStore _invariants
        -PersonalizationService _personalization
        -LLMStageRunner _stage_runner
        -Orchestrator _orchestrator
        -SessionStore _session
        -dict _active_task
        +chat(text) str
        +pipeline_step(extra) StageResult
        +advance_to(target) str
        +create_task/start_task/exit_task()
        +new_thread/load_thread/delete_thread()
        +propose_profile_style/apply_profile_style()
    }

    class ConversationService {
        -ThreadStore _threads
        -ThreadState _state
        +state ThreadState
        +save()
        +new_thread/load_thread/delete_thread/rename_thread()
        +reset()
    }
    class ThreadState {
        +str id
        +str name
        +list history
        +int total_tokens
        +float total_cost
        +list cost_series
        +str summary
        +int summary_covered_turns
        +str facts
        +dict topic_summaries
        +from_tuple(t)$
        +save_args() tuple
        +clear()
    }
    class MemoryCoordinator {
        -LLMGateway _gateway
        -ConfigManager _config
        +build_chat_context(...) list
        +build_task_context(msgs) list
        +route_topic(text, topics) tuple
        +run_background(...) BackgroundResult
    }
    class PersonalizationService {
        -LLMGateway _gateway
        -ProfileStore _profile
        -BehaviorLog _behavior
        -int _interactions
        +record_interaction(...)
        +maybe_nudge() str
        +propose_style() tuple
        +apply_style(s) bool
        +onboard/skip_onboarding()
    }
    class Orchestrator {
        -dict~str,StageAgent~ _agents
        -TaskStore _tasks
        -StageRunner _runner
        +step(task, extra) StageResult
    }
    class LLMStageRunner {
        -LLMGateway _gateway
        -MemoryCoordinator _memory
        -ProfileStore _profile
        -InvariantStore _invariants
        -InvariantChecker _invariant_checker
        -TaskStore _tasks
        +run(task, entry, extra) str
    }
    class InvariantChecker {
        -LLMGateway _gateway
        +validate(...) tuple
    }
    class LLMGateway {
        -LLMEngine _engine
        +complete(msgs, params, label, api_calls) Completion
        +record(i, label, completion) dict
        +get_pricing/get_context_window()
    }
    class ConfigManager {
        -dict _values
        +runtime dict
        +set/update/reset/show()
    }
    class SessionStore

    JarvisAgent *-- LLMGateway
    JarvisAgent *-- ConfigManager
    JarvisAgent *-- MemoryCoordinator
    JarvisAgent *-- InvariantChecker
    JarvisAgent *-- ConversationService
    JarvisAgent *-- PersonalizationService
    JarvisAgent *-- Orchestrator
    JarvisAgent *-- LLMStageRunner
    JarvisAgent *-- SessionStore
    ConversationService *-- ThreadState
    Orchestrator --> LLMStageRunner : runner
    LLMStageRunner --> MemoryCoordinator
    LLMStageRunner --> InvariantChecker
    LLMStageRunner --> LLMGateway
    MemoryCoordinator --> LLMGateway
    PersonalizationService --> LLMGateway
    InvariantChecker --> LLMGateway
```

---

## Class Diagram 2 — Task pipeline & FSM

```mermaid
classDiagram
    class Orchestrator {
        +step(task, extra) StageResult
    }
    class StageRunner {
        <<interface>>
        +run(task, entry, extra) str
    }
    class LLMStageRunner {
        +run(task, entry, extra) str
    }
    class SwarmStageRunner {
        +run(task, entry, extra) str
    }
    class ParallelExecutionRunner {
        +run(task, entry, extra) str
    }
    class StageResult {
        +str stage
        +str text
        +StageVerdict verdict
        +str blocked
        +str advanced_to
    }
    class StageVerdict {
        +str clean_text
        +bool ready
        +bool continue_stage
        +str gate
        +str confirm_target
        +str reject_target
        +str expected_action
    }
    class StageAgent {
        <<abstract>>
        +str stage
        +system_fragment(task)* str
        +entry_message(task)* str
        +marker_protocol()* str
        +interpret(markers)* StageVerdict
        +input_ready(task) tuple
        +process(task, raw) StageVerdict
        +record(task, clean, verdict)
    }
    class ClarifierAgent
    class PlannerAgent
    class ExecutorAgent
    class ValidatorAgent
    class DoneAgent
    class TaskStore {
        +new_task/find/save/load/delete()
        +advance_stage(task, target) str
        +save_result(task, text) Path
    }
    class fsm {
        <<module>>
        +STAGES
        +ALLOWED_TRANSITIONS
        +resolve_transition(cur, tgt) str
        +default_target(stage) str
    }

    LLMStageRunner ..|> StageRunner
    SwarmStageRunner ..|> StageRunner
    ParallelExecutionRunner ..|> StageRunner
    SwarmStageRunner --> LLMStageRunner : delegates non-validation
    ParallelExecutionRunner --> SwarmStageRunner : delegates non-execution
    Orchestrator --> StageRunner : runner
    Orchestrator --> TaskStore
    Orchestrator ..> StageResult : returns
    StageResult *-- StageVerdict
    Orchestrator --> StageAgent : agents[stage]
    StageAgent <|-- ClarifierAgent
    StageAgent <|-- PlannerAgent
    StageAgent <|-- ExecutorAgent
    StageAgent <|-- ValidatorAgent
    StageAgent <|-- DoneAgent
    StageAgent ..> StageVerdict : produces
    TaskStore ..> fsm : resolve_transition()
```

### FSM state diagram (code-enforced via `ALLOWED_TRANSITIONS`)

```mermaid
stateDiagram-v2
    [*] --> clarification
    clarification --> planning
    planning --> execution : plan approved (gate)
    execution --> validation
    execution --> planning : revise plan
    validation --> done : approved (gate)
    validation --> execution : rework execution
    validation --> planning : re-plan ([[REPLAN]])
    done --> [*]
```

### Validation swarm (opt-in via `review_agents` > 1)

The `validation` stage can be run by a panel of reviewer agents instead of the
single `ValidatorAgent` turn. `SwarmStageRunner` sits on the same `StageRunner`
seam: for `validation` it fans the turn out to N independent reviewers, then a
consolidator agent (which knows the user's request) merges their opinions into one
decision; for every other stage it delegates to `LLMStageRunner` unchanged. The
reviewers never see each other's output — all opinions flow only through the
consolidator (no agent-to-agent comms). The consolidated text carries the existing
markers, so `ValidatorAgent` maps it onto the unchanged 3-way human gate
(`[[REPLAN]]` ⇒ "revise the plan" recommended). Cost is bounded: ~N+1 model calls
per validation turn, all through `LLMGateway` and all accounted onto the task.

```mermaid
flowchart TD
    O[Orchestrator.step\nstage = validation] --> S[SwarmStageRunner.run]
    S -->|review_agents == 1| B[LLMStageRunner\nsingle ValidatorAgent turn]
    S -->|review_agents > 1| P{Reviewer panel\nindependent, own invariants}
    P --> R1[Correctness]
    P --> R2[Goal fit]
    P --> R3[Completeness]
    P --> R4[Robustness]
    P --> R5[Clarity]
    R1 --> C[ConsolidatorAgent\nknows goal/plan/criteria]
    R2 --> C
    R3 --> C
    R4 --> C
    R5 --> C
    C -->|APPROVE / REWORK_EXECUTION / REVISE_PLAN| T[consolidated text\n+ marker]
    T --> V[ValidatorAgent.process\n→ 3-way gate verdict]
    B --> V
```

### Parallel execution (opt-in via `execution_agents` > 1)

The `execution` stage can run its plan steps with a pool of executor agents instead
of one step per turn. `PlannerAgent` annotates each step with `[after: …]`, parsed
into a dependency graph (`plan_deps`). `ParallelExecutionRunner` (same `StageRunner`
seam) groups the steps into topological **waves** — every step in a wave has its
dependencies satisfied — and runs the steps *within* a wave concurrently, the waves
in order. Dependent steps receive their upstream steps' outputs. It assembles the
results, accounts every call, and emits `[[READY]]` so the orchestrator advances
`execution → validation` on the normal forward edge. Off (`execution_agents == 1`),
it delegates to the sequential per-step runner unchanged.

```mermaid
flowchart TD
    O[Orchestrator.step\nstage = execution] --> X[ParallelExecutionRunner.run]
    X -->|execution_agents == 1| BX[LLMStageRunner\none step per turn]
    X -->|execution_agents > 1| W[execution_waves plan_deps]
    W --> w0[wave 0: independent steps\nrun concurrently]
    w0 --> w1[wave 1: steps whose deps\nare now done]
    w1 --> A[assemble outputs in order\n+ account calls]
    A --> RD[ExecutorAgent.process\n_exec_recorded → READY]
    RD --> AV[advance execution → validation]
    BX --> AV
```

---

## Class Diagram 3 — LLM gateway, providers & repositories

```mermaid
classDiagram
    class LLMGateway {
        -LLMEngine _engine
        +complete(...) Completion
        +record(...) dict
        +get_pricing()
        +get_context_window()
    }
    class LLMEngine {
        <<interface>>
        +complete(messages, params) Completion
        +get_pricing(model) tuple
        +get_context_window(model) int
    }
    class OpenRouterClient {
        +complete(...) Completion
        +get_pricing(...) tuple
        +get_context_window(...) int
    }
    class Completion {
        <<NamedTuple>>
        +str text
        +str finish_reason
        +dict request
        +dict response
        +float latency_ms
    }
    class accounting {
        <<module>>
        +make_call_record(i, label, completion, engine) dict
    }
    class ThreadStore
    class TaskStore
    class ProfileStore
    class InvariantStore
    class BehaviorLog
    class SessionStore

    LLMGateway --> LLMEngine
    OpenRouterClient ..|> LLMEngine
    LLMEngine ..> Completion : returns
    LLMGateway ..> accounting : make_call_record()
    ConversationService --> ThreadStore
    PersonalizationService --> ProfileStore
    PersonalizationService --> BehaviorLog
    LLMStageRunner --> TaskStore
    LLMStageRunner --> InvariantStore
    JarvisAgent --> SessionStore
```

---

## Sequence Diagram 1 — Startup & REPL input routing

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant main as __main__.main
    participant Agent as JarvisAgent
    participant REPL as run_repl (loop.py)
    participant Conv as ConversationService

    main->>main: ConfigManager(), OpenRouterClient()
    main->>Agent: JarvisAgent(client, config)
    Agent->>Agent: build gateway, memory, services
    Agent->>Conv: ConversationService()
    Conv->>Conv: load_last() or new_thread()
    main->>REPL: run_repl(agent, config)
    alt no profile yet
        REPL->>Agent: profile_exists() == False
        REPL->>User: onboarding interview
    end
    loop each input
        User->>REPL: text / command
        alt command
            REPL->>REPL: _dispatch() -> handlers
        else active task (not done)
            REPL->>REPL: _drive_task()  (Seq. 3)
        else chat
            REPL->>Agent: chat(text)  (Seq. 2)
        end
        REPL->>User: print output
    end
```

---

## Sequence Diagram 2 — Chat turn (`agent.chat`)

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Agent as JarvisAgent
    participant Conv as ConversationService
    participant Prof as ProfileStore/InvariantStore
    participant Mem as MemoryCoordinator
    participant GW as LLMGateway
    participant Eng as OpenRouterClient
    participant IC as InvariantChecker
    participant Pers as PersonalizationService

    User->>Agent: chat(user_input)
    Agent->>Conv: state (ThreadState)
    Agent->>Prof: read_active() profile + invariants
    Agent->>Agent: build_system_prompt(...)
    Agent->>Agent: build_attachments_block(state.attachments)
    opt context_strategy == topics
        Agent->>Mem: route_topic(input, topic_summaries)
        Mem->>GW: complete(label=topic_routing)
        GW->>Eng: complete()
    end
    Agent->>Mem: build_chat_context(history, summary, facts, ...)
    Agent->>GW: complete(messages, label=final_answer)
    GW->>Eng: complete()
    Eng-->>GW: Completion
    GW-->>Agent: Completion (+ api_call record)
    opt invariants defined
        Agent->>IC: validate(invariants, messages, reply, ...)
        IC->>GW: complete(label=invariant_check)
        alt violation
            IC->>GW: complete(label=invariant_resolution)
        end
        IC-->>Agent: (final_text, notice)
    end
    Agent->>Conv: state.history.append(user, assistant)
    Agent->>Mem: run_background(history, summary, facts, ...)
    opt background work (compression / facts / topic summary)
        Mem->>GW: complete(label=context_compression / facts_extraction / ...)
    end
    Agent->>Pers: record_interaction(...)
    Agent->>Pers: maybe_nudge()
    Agent->>Conv: save() -> ThreadStore
    Agent->>Agent: session.add(...)
    Agent-->>User: response + notices
```

---

## Sequence Diagram 3 — Task pipeline turn with gates (`task run`)

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant REPL as _drive_task (loop.py)
    participant Agent as JarvisAgent
    participant Orch as Orchestrator
    participant SA as StageAgent (current stage)
    participant Run as LLMStageRunner
    participant GW as LLMGateway
    participant IC as InvariantChecker
    participant TS as TaskStore

    User->>REPL: task run / message
    loop until gate or done
        REPL->>Agent: pipeline_step(extra)
        Agent->>Orch: step(task, extra)
        Orch->>SA: input_ready(task)
        alt input contract not met
            Orch-->>Agent: StageResult(blocked)
        else ready
            Orch->>SA: entry_message + marker_protocol
            Orch->>Run: run(task, entry, markers)
            Run->>Run: build_system_prompt + WM block + build_task_context
            Run->>GW: complete(label=stage_turn)
            opt invariants
                Run->>IC: validate(...)
            end
            Run->>TS: save(task transcript)
            Run-->>Orch: raw assistant text
            Orch->>SA: process(raw) -> parse markers, interpret
            SA-->>Orch: StageVerdict
            Orch->>TS: save(task)
            alt verdict.ready (no gate)
                Orch->>TS: advance_stage(task, next) -> resolve_transition
            end
            Orch-->>Agent: StageResult
        end
        Agent-->>REPL: StageResult
        alt gate == APPROVAL
            REPL->>User: Confirm / Reject
            REPL->>Agent: advance_to(confirm_target | reject_target)
            Agent->>TS: advance_stage(...)
        else gate == QUESTION
            REPL->>User: ask free-text
            Note over REPL: answer becomes next extra
        else stage == done
            REPL->>Agent: save_task_result(deliverable)
            Agent->>TS: save_result(...)
            REPL->>Agent: finish_active_task(summary, deliverable)
            Agent->>Conv: attach(result) + exit task
        end
    end
    REPL-->>User: stage output / final deliverable path
```
