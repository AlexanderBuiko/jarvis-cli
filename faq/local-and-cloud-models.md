# Local vs cloud models

## The local (Ollama) model is very slow — should I switch to the cloud?

For interactive use, yes. Switch the main turn to the cloud instantly, no restart:

```
config set provider openrouter
```

Switch back to local with `config set provider ollama`. Local (Ollama) is free and
private but slower on modest hardware; the cloud is faster and higher-quality but
uses your `OPENROUTER_API_KEY`. Many users keep the cloud for chat and pin cheap
internal calls to local via `JARVIS_UTILITY_PROVIDER` / `JARVIS_SUBAGENT_PROVIDER`.

## Can I keep embeddings local but answers on the cloud?

Yes — they're independent. `JARVIS_EMBED_PROVIDER=ollama` keeps indexing/retrieval
local while the chat provider stays cloud. Just remember an index is tied to the
embedder it was built with (see the dimension-mismatch FAQ).

## Which local model should I use, and how do I install it?

Install Ollama, then pull the model:

```
ollama serve
ollama pull qwen2.5:7b          # chat
ollama pull nomic-embed-text    # embeddings
```

Point Jarvis at the daemon with `JARVIS_OLLAMA_URL` (default
`http://localhost:11434`) and the chat model with `JARVIS_OLLAMA_MODEL`.

## Does the deployed (Cloud Run) server use my local Ollama?

No — a cloud server can't reach a daemon on your laptop. A deployed server must use
cloud embeddings/answers, so indexes it serves should be built with a cloud
embedder. Local Ollama is for your own machine.
