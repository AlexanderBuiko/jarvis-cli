# Неделя 6 — Локальная LLM: запуск и интеграция

**Задание ментора:** установить и запустить локальную LLM; проверить, что модель
работает локально и доступна через CLI / HTTP API; сделать ≥3 запроса разной
сложности.
**Результат:** ✅ Локальная LLM запущена, отвечает на запросы, интегрирована в Jarvis
как полноценный движок с живым переключателем cloud↔local.

Окружение: MacBook (Apple M4 Pro, 24 GB unified memory) · Ollama 0.31.1 ·
модель **qwen2.5:7b** (Q4, ~4.7 GB, контекст 32 768 токенов).

---

## 1. Установка и запуск

```bash
brew install ollama          # уже был установлен: /opt/homebrew/bin/ollama
ollama serve                 # демон на http://localhost:11434
ollama pull qwen2.5:7b       # ~4.7 GB
ollama list
# NAME          ID            SIZE     MODIFIED
# qwen2.5:7b    845dbda0ea48  4.7 GB   ...
```

## 2. Проверка: модель работает локально и доступна через CLI + HTTP

**CLI:**
```bash
$ ollama run qwen2.5:7b "In one sentence, what is a local LLM?"
A local LLM is a large language model that runs on a device or server close
to the user, potentially reducing latency and increasing privacy compared to
models accessed over the internet.
```

**HTTP — родной эндпоинт `/api/generate`:**
```bash
$ curl -s http://localhost:11434/api/generate \
    -d '{"model":"qwen2.5:7b","prompt":"Say hello in 3 languages.","stream":false}'
# → English: Hello!  ·  Spanish: Hola!  ·  French: Bonjour!
```

**HTTP — OpenAI-совместимый `/v1/chat/completions`** (именно его использует Jarvis,
поэтому форма ответа совпадает с облачным движком):
```bash
$ curl -s http://localhost:11434/v1/chat/completions -H 'Content-Type: application/json' \
    -d '{"model":"qwen2.5:7b","messages":[{"role":"user","content":"Reply with exactly: OK"}],"temperature":0}'
# content: OK | usage: {'prompt_tokens': 34, 'completion_tokens': 2, 'total_tokens': 36}
```

## 3. Три запроса разной сложности — через сам Jarvis (провайдер переключён на local)

Запросы прошли по реальному пути приложения: `config set provider ollama` →
`RoutingEngine` → `OllamaClient` → тот же `LLMGateway` и учёт стоимости, что и у
облака. Стоимость каждого вызова — **$0.00** (локальный инференс бесплатен).

| # | Тип | Запрос | Ответ | Латентность | Токены |
|---|-----|--------|-------|-------------|--------|
| 1 | Простой факт | Столица Франции? | `Paris` | 226 ms | 43 |
| 2 | Рассуждение | Средняя скорость поезда: 60 км за 45 мин | `80 km/h` (с расчётом 60 / 0.75) | 4338 ms | 237 |
| 3 | Генерация кода | Итеративный `fib(n)` на Python | корректная функция (см. ниже) | 1941 ms | 130 |

```python
def fib(n):
    if n <= 0:
        return 0
    elif n == 1:
        return 1
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b
```

Учёт стоимости (из `api_calls`):
```
1. Simple factual      model=qwen2.5:7b   total_usd=0.0
2. Reasoning           model=qwen2.5:7b   total_usd=0.0
3. Code generation     model=qwen2.5:7b   total_usd=0.0
```

---

## Как это встроено в архитектуру (цели недели)

Движок подключён через ту же абстракцию `LLMEngine`, что и облако, — поэтому агент,
оркестратор и стадии не знают, cloud перед ними или local.

- **`jarvis/ollama/client.py` — `OllamaClient`**: реализует `LLMEngine`
  (`complete` / `get_pricing → (0,0)` / `get_context_window` из `/api/show`). Ходит в
  OpenAI-совместимый `/v1/chat/completions`. Cloud-id модели (со слэшем) игнорируется
  и заменяется локальным тегом — чтобы переключение на лету не тащило облачное имя.
- **`jarvis/llm/router.py`**: `make_engine(provider)`, `RoutingEngine` (читает
  провайдера на каждом вызове → живой тумблер), `EngineRouter` (лениво строит по
  движку на провайдера, раздаёт нужный gateway по роли).
- **Живой тумблер основного вызова:** `config set provider ollama | openrouter`
  переключает основной ход прямо в сессии, без перезапуска. По умолчанию — `openrouter`
  (поведение не меняется, пока не переключишь).
- **Роли по отдельности (опционально):**
  - `JARVIS_UTILITY_PROVIDER` — проверка инвариантов, память, персонализация;
  - `JARVIS_SUBAGENT_PROVIDER` — агенты стадий (planning/execution/validation).
  Не задано → роль следует за основным тумблером. Пример из требования: держать
  основной ход в облаке, а **проверку инвариантов** гонять локально.
- **Проверка инвариантов**: сам *чек* идёт на (локальный) utility-движок, а
  *переписывание* видимого ответа остаётся на основном движке — ради качества ответа.
- **Настройки** (`.env.example`): `JARVIS_LLM_PROVIDER`, `JARVIS_UTILITY_PROVIDER`,
  `JARVIS_SUBAGENT_PROVIDER`, `JARVIS_OLLAMA_MODEL`.

## Что дальше (не входило в этот шаг)

- Сравнительный прогон local↔cloud на одних запросах (цель недели №2).
- Бонус: тумблер с маркировкой, каким движком получен каждый результат.

## Тесты

`tests/test_ollama_client.py`, `tests/test_engine_router.py`, плюс новый кейс в
`tests/test_invariant_checker.py` (чек — local, резолюция — main). Вся сеть замокана.
Полный прогон: **270 passed**.
