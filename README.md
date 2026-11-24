# VerifyNet

VerifyNet is a research prototype for testing AI-generated network configuration templates. It was built for an Ericsson GenAI thesis project.

The application follows a simple workflow:

```text
Define network intent → Generate a template → Validate independently → Repair → Test and export evidence
```

## Live demo

The current hosted demo is available at:

<https://verifynet-hisa.onrender.com/>

The scripted demo works without an API key. Render may take a short time to wake the free service after inactivity.

## What VerifyNet supports

- Standard IPv4 interface and static-route templates
- Two-interface, two-route IPv4 templates
- IPv6 static routing
- VLAN 802.1Q static routing
- OSPF router ID, area, adjacency, learned-route, and packet checks
- Cisco IOS interface and static-route syntax
- Juniper Junos `set` command syntax
- Scripted generation, retrieval-assisted generation, and bounded repair
- Human review labels: correct, partially correct, incorrect, and unsafe
- Research history, metrics, HTML/JSON/PDF evidence export, and per-case inspection
- Docker-based FRRouting virtual-router tests on Docker-capable hosts

## How it works

1. The user enters a structured network intent.
2. VerifyNet generates or accepts a reusable configuration template.
3. A restricted template renderer rejects unsafe expressions and unknown variables.
4. The independent checker renders multiple parameter sets and compares the commands with the intent.
5. If repair is enabled, checker errors are returned to the provider for a bounded correction.
6. Optional Docker tests load the resulting configuration into disposable FRRouting containers.
7. The application records the checks, references, repairs, timing, and router evidence.

A green local result means that the implemented checks passed. It is not a guarantee of production-device acceptance.

## Run locally

Requirements:

- Python 3.10 or newer
- Jinja2 and ReportLab from `requirements.txt`
- Docker Desktop with Linux containers for virtual-router tests

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py --open
```

Open <http://127.0.0.1:8765/>.

You can also double-click `Start VerifyNet.cmd` on Windows.

## First demonstration

1. Keep **Scripted demo** selected.
2. Choose **Retrieval + repair**.
3. Click **Run walkthrough**.
4. Inspect the intentionally failing first attempt.
5. Inspect the repaired template and validation stages.
6. Export the JSON, HTML, or PDF evidence report.

## Live AI mode

Live AI is optional. It requires an OpenAI API key, a model available to the same project, and available API quota.

1. Open **AI setup**.
2. Enter the API key privately.
3. Enter the exact model ID available to the project.
4. Click **Verify access & connect**.
5. Return to **Template lab**, choose **Live AI**, and run a small experiment.

Never commit API keys. VerifyNet keeps an in-app key in server memory and excludes credentials from reports and history. HTTP 429 responses usually indicate rate limits or unavailable project quota.

## Virtual-router lab

The lab uses the official FRRouting image:

```text
quay.io/frrouting/frr:10.4.5
```

The OSPF test uses a local image built from `docker/ospf.Dockerfile` so that `ospfd` is available. Each run creates temporary labeled Docker networks and containers, checks configuration acceptance, verifies routes, tests packet delivery, and removes the resources it created.

Render hosts the web interface and reports. Docker/FRRouting tests require a Docker-capable local or private host.

## Evaluation

Run the checker benchmark:

```powershell
python -m unittest discover -s tests -v
python -m verifynet.benchmark --output reports/final-benchmark.json
```

The current offline dataset contains 100 cases:

- 40 development cases
- 60 held-out evaluation cases
- IPv4, multi-route, IPv6, VLAN, and OSPF profiles
- Valid, malformed, unsafe, incomplete, and incorrect configurations

The current regression suite contains 71 tests. The offline checker benchmark currently achieves 100/100 expected verdicts. This measures checker behavior, not real-model quality.

For a real AI comparison, use the live benchmark after connecting a model:

```powershell
python -m verifynet.benchmark --live --split development --limit 3 --output reports/development.json
python -m verifynet.benchmark --live --split evaluation --limit 3 --output reports/evaluation.json
```

The reports compare generation-only, retrieval-assisted, and retrieval-plus-repair strategies using first-pass accuracy, final accuracy, repairs, latency, references, and token usage.

## Deploy on Render

The repository includes `render.yaml`.

1. Open Render and choose **New → Blueprint**.
2. Select the `main` branch of `Dhara092005/VerifyNet`.
3. Review the `verifynet` web service.
4. Click **Apply** or **Create Blueprint**.
5. Leave `OPENAI_API_KEY` and `VERIFYNET_MODEL` empty for the scripted demo, or add them later after API quota is available.

The Render service uses `python app.py --host 0.0.0.0 --port $PORT` and checks `/api/status` for health. The `VERIFYNET_ALLOW_REMOTE` setting is enabled only by the Render blueprint; local runs remain localhost-only by default.

## Project structure

```text
app.py                    Local HTTP server and API routes
verifynet/domain.py       Intent contracts and independent checkers
verifynet/pipeline.py     Generation, retrieval, repair, and evidence
verifynet/providers.py    Scripted and OpenAI providers
verifynet/router_lab.py   Disposable FRRouting Docker tests
verifynet/benchmark.py    Offline and live evaluation runners
verifynet/reports.py      HTML evidence reports
verifynet/pdf_report.py   PDF evidence reports
web/                      Browser interface
tests/                    Automated regression tests
docker/                   OSPF FRRouting image definition
render.yaml               Render deployment configuration
```

## Security and scope

Imported references are treated as untrusted text. They are not executed as commands or trusted as system instructions. Local history stores summaries rather than templates or credentials. Do not expose a Render deployment publicly without adding appropriate authentication.

Remote live-AI connections are disabled by default. Set `VERIFYNET_ALLOW_REMOTE_AI=true` only after adding authentication and per-user credential isolation to a protected deployment. Local scripted validation and the Router Lab remain available without an AI key.

The independent checker reports bounded topology-safety findings, including overlapping interface subnets, duplicate route destinations, and obvious next-hop loops. These checks complement, but do not replace, a full network simulator such as Batfish or Containerlab.

VerifyNet is a bounded research prototype. It does not configure physical routers, understand unrestricted natural-language network requests, or guarantee production safety.

## License and references

The repository contains original prototype code and locally authored reference summaries. FRRouting documentation is available at <https://docs.frrouting.org/>. OpenAI API documentation is available at <https://developers.openai.com/api/docs/>.
