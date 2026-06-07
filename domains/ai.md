# AI: building with large language models

A working vocabulary for someone building agents, RAG systems, and LLM-powered products. Focused on practitioner concepts, not academic ML.

## Tokens

LLMs don't read characters or words — they read *tokens*. A tokenizer splits text into a fixed vocabulary of subword units (usually 30K–100K of them). "ChatGPT" might be one token; "antidisestablishmentarianism" is several. Tokens are the unit of cost (you pay per token in and per token out), the unit of context window, and the unit of latency. Estimate roughly 4 characters of English per token, less for code.

## Embeddings

Every token has a learned dense vector — its *embedding* — representing its meaning in a high-dimensional space (typically 768–4096 dimensions). Embeddings are what makes "king − man + woman ≈ queen" work. Practitioner use: embed a query and a corpus, then nearest-neighbor search the corpus. That's the foundation of semantic search and RAG.

## Attention

The mechanism that lets every token in a sequence look at every other token and decide how much each one matters for its own meaning. "The animal didn't cross the street because it was too tired" — *it* refers to *the animal*; attention is what learns that link. Attention is also why context length is expensive — its memory cost grows with the square of sequence length.

## Transformers

The architecture stack that wraps attention into a usable model: alternating attention blocks and feed-forward layers, repeated many times. Modern LLMs are transformers all the way down. You rarely touch the architecture directly, but understanding the stack helps debug latency (more layers = more compute per token) and quality (attention failures show up as the model "missing" things in context).

## Context window

The maximum number of tokens a model can attend to in one request — its working memory. Older models had 4K–8K; current frontier models have 200K–1M. This is the hard ceiling on how much of a codebase, document corpus, or chat history you can fit at once. Hit it and the API errors; approach it and quality degrades subtly before that.

## Prompt engineering

The discipline of structuring the input to get reliable output. The big levers: clear system prompt (who/what/how), few-shot examples (show, don't tell), explicit output format (JSON schema, XML tags), and breaking complex tasks into steps the model can reason about. Most "the model is wrong" problems are prompt problems.

## Structured outputs

Constraining the model to return JSON conforming to a schema, instead of free text. Either via a JSON-schema parameter (`output_config.format` on Claude, `response_format` on OpenAI) or via tool-use with strict validation. This is what turns LLMs from chat assistants into reliable components of larger systems — Pydantic-validated outputs let you fail fast on malformed responses.

## Tool use

The mechanism by which an LLM can call external functions (your code, an API, a database) during its response. You declare the tools' schemas in the request; the model returns a structured tool-call object instead of text; your harness executes it and feeds the result back. This is the substrate of every modern AI agent.

## Agents

A loop: model proposes an action via tool-use → harness executes it → result goes back into the model's context → model decides the next action. The model is the planner; the harness is the executor. Where agents tend to fail: tool descriptions that aren't precise, contexts that grow unmanageably, and loops that don't have a termination condition. A reliable agent is mostly tight tools and tight evals, not a smarter prompt.

## RAG (retrieval-augmented generation)

The pattern for grounding an LLM in a specific corpus: embed the corpus, embed the query, retrieve the top-k most similar chunks, and stuff them into the prompt as context. Bypasses the need to fine-tune the model on your data and keeps the source-of-truth in your database, not in the weights. Where RAG fails: chunking strategy, retrieval that returns near-duplicates, and contexts so cluttered the model can't find the relevant bit.

## Evals

The systematic measurement of an LLM application against held-out test cases. Without evals, you can't tell if a prompt change made things better or just different. The pattern: hand-author a small set of cases with expected behavior, run the system end-to-end, score with deterministic checks plus an LLM-as-judge for fuzzy criteria. Evals matter more than prompts — a prompt without an eval is a guess.

## LLM-as-judge

Using an LLM to grade the output of another LLM (or itself) against criteria you specify. The judge prompt names the rubric, the model evaluates, and returns a structured score + rationale. Cheap, fast, and scales — but biased toward verbose outputs and self-similar style. Mitigate by writing tight rubrics, including deterministic signals the judge must weigh, and capturing the judge's reasoning so a human can audit any disputed score.

## Hallucination

The model confidently asserts something that isn't true. Usually a symptom of the model interpolating in a region of its training distribution where it doesn't actually know. Mitigations: ground in retrieved sources (RAG), require citations, force structured outputs, and run a verification step. Hallucination isn't a bug to be fixed once — it's an ambient failure mode to be designed around.
