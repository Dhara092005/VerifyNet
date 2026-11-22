# VerifyNet v0.3

**Generate, inspect, and repair reusable network configuration templates.**

A local research prototype for an Ericsson GenAI thesis application. The current version handles standard IPv4, advanced two-interface/two-route IPv4, IPv6 static routing, VLAN-aware static routing, and OSPF configuration validation. It includes a browser interface, independent validation, a scripted walkthrough, a real AI adapter, an importable reference library, an evaluation runner, and a disposable FRRouting lab.

## What's new in v0.3

- **Router lab:** an opt-in Docker runner checks a locally passing candidate in FRRouting, with a negative control before the route is loaded, kernel route inspection, and an ICMP packet test afterward.
- **Safe lab lifecycle:** each run uses a unique ownership label, bounded commands, fixed image `quay.io/frrouting/frr:10.4.5`, no host mounts or Docker socket, and cleanup that leaves resources with unexpected ownership untouched.
- **Readiness evidence:** the UI and `python -m verifynet.router_lab --status` report whether Docker and the Linux image are available. They never claim a device test passed when Docker is unavailable.
- **Run history:** the app keeps up to 100 local summary records for comparing strategies, pass rates, repair counts, references, timing, and device-test coverage. Templates and credentials are excluded.
- **Live strategy comparison:** the Evaluation page can run a bounded three-way AI ablation on one to five development or evaluation cases after a model is connected, then export the metrics.
- **Human review:** after a generation run, label the result as correct, partially correct, incorrect, or unsafe and add an optional note. Labels are stored locally without saving templates or credentials.
- **Advanced multi-route task:** evaluate templates with two interface blocks and two static routes. The checker renders three varied multi-interface cases and verifies every address, route, and next-hop relationship.
- **Research charts and report export:** Run history now visualizes strategy pass rates and human-review labels. Each result can be exported as a thesis-ready Markdown evidence report with intent, strategy, references, attempts, and validation stages.
- **Larger evaluation set:** the offline suite now contains 60 cases: 20 development cases, 20 single-route held-out cases, and 20 multi-interface held-out cases.

The router lab requires Docker Desktop using Linux containers (or a Linux Docker host) and the pinned image pulled locally. It creates disposable no-port bridge networks, loads the candidate into FRRouting, checks kernel routes, and verifies packet delivery before cleaning up its own resources.

## What's new in v0.2

- **Reference library:** import UTF-8 `.txt` and `.md` files or paste text. Search the passages before using them in generation.
- **Traceable retrieval:** imported passages carry content fingerprints, character offsets, line locations, and optional source links. Each retrieval-based run records a fingerprint of the active corpus and the passages actually supplied.
- **Reversible reference selection:** exclude or include an imported reference without deleting it. Duplicate text is not stored twice.
- **In-app AI setup:** verify access to a chosen model and keep the API key in the running server's memory. No server restart or environment editing is required for this route.
- **58 automated tests:** includes the import, retrieval, credential-handling, HTTP, router-lab readiness, history, live-benchmark, human-review, and multi-interface flows. Real model access and real-router acceptance remain unverified until you connect your own account and provide Docker.

## Start here

On this computer, Python and the required Jinja2 package were available during development. Double-click **Start VerifyNet.cmd**. Keep its terminal open while using the application. It opens **http://127.0.0.1:8765**.

Or run from this project folder:

```powershell
python -m pip install -r requirements.txt
python app.py --open
```

Python 3.10 or newer is required. A fresh machine should use a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py --open
```

If port 8765 is occupied, use `python app.py --port 8766 --open`. Stop the server with Ctrl+C in its terminal.

## Try the first experiment

1. Leave **Scripted demo** and **Retrieval + repair** selected.
2. Click **Run walkthrough**.
3. Inspect attempt 1. The template incorrectly puts an interface address with a prefix in the route's next-hop position. The command checker rejects it.
4. Inspect attempt 2. A known reference template replaces the broken candidate and passes local checks.
5. Select **Repair diff** to inspect the actual text change.
6. Export the evidence JSON. It includes candidate templates, checker errors, parameter sets, and source references.
7. In **Evaluation**, run the 30 offline fixtures.

**Demo mode is scripted, not GenAI.** Its generation and repair results are deliberately deterministic. It is for demonstrating the workflow, not measuring a model. Retrieval still runs and checker failures are real. A pasted template can also be checked locally without calling an AI model.

## Connect live GenAI

The API adapter uses the OpenAI Responses API with a structured JSON response. It requires a model supporting Responses and structured outputs. Choose a model available to your API account; the project does not guess a model ID.

**Easiest option:** open **AI setup** in the application. Enter your API key privately there, enter a model ID, and click **Verify access & connect**. The app sends the key to OpenAI's model endpoint to verify access. This operation does not request generated content. It confirms model access, not Responses/structured-output compatibility, available inference credits, or template quality.

The field is cleared on submission. The app keeps a successfully verified connection in server memory only, never in a project file, browser storage, or API response. Failed reconnection preserves the previous connection. **Disconnect for this session** disables live AI, including environment fallback, until you connect again or restart the server. Restarting clears a connection entered in the app; any pre-existing environment configuration is available again after restart.

Then open **Template lab**, choose **Live AI**, and run a small experiment. This sends the requirement, parameters, retrieved passages, and repair feedback to the provider and can use API credits. The app deliberately keeps Demo selected until you choose Live AI.

An in-app session connection applies only to that running server. The separate command-line benchmark still needs the environment setup below.

**Alternative: environment configuration**

Set `OPENAI_API_KEY` and `VERIFYNET_MODEL` in the environment used to launch the server. Do not put a key in the repository, browser code, or chat. The app does not automatically load `.env` files.

PowerShell example, with hidden key entry:

```powershell
$verifyNetKey = Read-Host 'API key' -AsSecureString
$env:OPENAI_API_KEY = [System.Net.NetworkCredential]::new('', $verifyNetKey).Password
$env:VERIFYNET_MODEL = Read-Host 'Model ID from your API account'
python app.py --open
```

Restart the application after configuring these values. **Live AI** becomes available. The server sends the requirement, network parameters, retrieved summaries (when enabled), and candidate/error context to the provider. Up to one initial request plus three repair requests are allowed. Usage can incur API charges. `store: false` is requested; this is not a promise about all provider retention policies.

The API key remains on the server and is never returned by the status endpoint. Provider errors are shown explicitly; live failures never fall back to scripted demo results. API responses are parsed and checked independently.

**A live API call has not been verified during delivery.** Automated tests cover both connection verification and generation using mocked provider responses. A configured account is still needed to verify real model behavior.

## Import and inspect documentation

1. Open **Reference library**.
2. Choose a UTF-8 `.txt` or `.md` file, or paste a relevant passage. Add a title and, optionally, an HTTPS source link.
3. Click **Import reference**. A source URL is citation metadata; the application does not fetch it or verify that it supports the imported text.
4. Use **Try retrieval** to search and inspect the actual passages, line locations, and BM25 scores. Scores measure text relevance, not confidence or factual correctness.
5. Toggle **Include** to control whether an imported reference is available to future runs. The three built-in reference notes are always available to retrieval-based strategies. The generation-only baseline receives no documents.

Try `examples/reference-routing-notes.md` first. It is a labeled teaching note, not a vendor manual.

Imports are stored locally in `data/imported_documents.json`, excluded from Git and the distributable project ZIP. Limits: 40–150,000 characters per document, 30 documents, and 2 million characters in total. Text is normalized to LF line endings and outer whitespace is trimmed. A SHA-256 hash of that normalized text identifies exact duplicates. Passages contain at most 1,600 characters with overlapping context. Line/character locations refer to the normalized stored text. At most two passages from any one imported document are selected per search.

Imports are untrusted reference data. They are not executed, rendered as HTML, or treated as system instructions by the provider prompt. They can still be wrong or contain misleading instructions; the independent checker remains necessary, and this is not a claim of complete prompt-injection resistance. PDF extraction is not implemented yet.

Exported evidence intentionally includes the retrieved passages supplied to the model. Review that export before sharing it if your references contain private material. Importing text itself makes no external API request.

## What is actually checked?

| Stage | Evidence | Limit |
|---|---|---|
| Template syntax | Restricted Jinja2 AST and allowed variables | No loops, filters, calls, or expressions |
| Parameter rendering | Three distinct parameter sets | Finite examples, not proof for all inputs |
| Command structure | Local parser for a small FRR-style subset | Not the actual FRR parser/compiler |
| Intent agreement | Exact interface/address/route comparison | Structured input is the oracle; free-text intent is not independently understood |
| Local route model | Next hop belongs to a connected subnet | No device, neighbor, forwarding, return-path, firewall, or packet test |

The checker rejects extra commands, duplicate routes, missing routes, wrong variable substitutions, unknown variables, and hardcoded values that do not generalize to the alternate inputs. The caller's structured intent is validated first: IPv4 only, usable host addresses, a distinct directly connected next hop, and a non-overlapping remote destination.

This limited task excludes /31 and /32 interface links, overlapping/default destination routes, recursive next hops, multi-vendor syntax, and arbitrary network changes. IPv6 and VLANs are supported as separate single-interface/static-route profiles with disposable packet tests. OSPF validation and daemon/adjacency checks are active; route-learning evidence is retained when the bounded Docker topology cannot install the learned prefix. These are scope choices, not claims that FRRouting lacks these features.

The live model is asked to respect the structured intent. If the natural-language description conflicts with the form, the form is authoritative. Do not describe the prototype as understanding arbitrary network requests.

**No generated configuration is executed.** Green results mean only that the implemented local checks passed. Do not claim real-device success, complete configuration validation, or packet reachability.

## Architecture

```text
Browser workbench
      │ explicit intent + requirement
      ▼
Local Python HTTP server
      ├── BM25 retrieval over attributed documentation summaries
      ├── provider: scripted demo OR live OpenAI Responses API
      ├── restricted Jinja2 rendering
      ├── local command parser + independent intent checks
      └── bounded repair loop → evidence JSON
```

- `verifynet/domain.py`: contract validation, template restriction, parser, semantic checks.
- `verifynet/retrieval.py`: BM25 retrieval, document diversity, and corpus fingerprints.
- `verifynet/documents.py`: local imports, passage boundaries, provenance, and include/exclude state.
- `verifynet/settings.py`: session-only credentials and model-access verification.
- `verifynet/providers.py`: clearly separated demo and live providers.
- `verifynet/pipeline.py`: strategies, repair limits, diff history, and reports.
- `verifynet/benchmark.py`: offline fixtures and opt-in live comparisons.
- `data/knowledge.json`: short original summaries with provenance, not scraped manuals.
- `web/`: responsive browser UI, no frontend build step or external resources.
- `tests/`: checker, pipeline, provider, and local HTTP tests.

## Run verification

```powershell
python -m unittest discover -s tests -v
python -m verifynet.benchmark --output reports/checker-regression.json
```

The offline report contains **30 synthetic checker fixtures** and expected verdicts. Those verdicts are authored independently of the observed result. They are not LLM success rates. The fixtures cover six patterns; their count is not a claim of broad coverage.

## Run the actual AI experiment

After connecting a model:

```powershell
python -m verifynet.benchmark --live --split development --limit 3 --output reports/development.json
python -m verifynet.benchmark --live --split evaluation --limit 3 --output reports/evaluation.json
```

Each case is run using generation only, retrieval plus generation, and retrieval plus bounded repair. For three cases and a repair budget of two, this makes between 9 and 15 API calls. The report records real responses, input intent, retrieved sources, validation results, model ID, token usage, latency, and aggregate success rates. It does not invent dollar costs. API failures stop the command; inspect provider access and retry deliberately.

There are 10 development and 20 evaluation inputs. The split separates exact input cases, but all cases share a small task family. The current suite is a pilot, not a robust generalization benchmark. Keep the model, prompts, corpus, and retry budget fixed when comparing methods. Repeat runs for stochastic variation and report uncertainty before drawing research conclusions.

## Next milestones

1. Configure a real model and collect a small development run. Inspect its failures.
2. Complete the **version-pinned FRRouting virtual-router lab** OSPF learned-route check in a topology that exports a peer prefix through the container namespace. The custom image now includes `ospfd`; OSPF daemon readiness, configuration acceptance, Full adjacency, kernel routes, OSPF routes, and LSAs are captured. Standard IPv4, two-route IPv4, IPv6, and VLAN profiles verify packet or tagged-link delivery.
3. Expand the reference library with reviewed documentation and add PDF extraction with retained page provenance.
4. Add genuinely different held-out task families, independently reviewed expected behavior, and explicit malformed-template repair tasks.
5. Measure repair regressions, token cost, latency, and model variance; write a short experiment report and record a demo.

## Source references

- [FRRouting static route documentation](https://docs.frrouting.org/en/latest/static.html)
- [FRRouting Zebra/interface documentation](https://docs.frrouting.org/en/latest/zebra.html)
- [OpenAI structured outputs documentation](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses)
- [OpenAI model-access endpoint](https://developers.openai.com/api/reference/resources/models/methods/retrieve)

The built-in reference notes were reviewed on 29 October 2026; model-access documentation was consulted on 30 October 2026. Imported references have their own import timestamps and are not marked reviewed. Documentation versions can change; pin the router version when adding the execution lab.
