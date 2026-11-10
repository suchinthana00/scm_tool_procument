# Supply Chain Procurement Tools

Open-source, deterministic procurement planning tools designed for AI agents.
The same business logic is available through separate **MCP** and **A2A**
adapters, so an agent can use tools directly or collaborate with the planner as
another agent.

> **Scope:** This starter is advisory and read-only. It does not create purchase
> orders, modify inventory, contact suppliers, or make award decisions.

## Capabilities

| Capability | What it does | Human decision still required |
|---|---|---|
| `compare_supplier_quotes` | Checks MOQ and budget eligibility, then ranks comparable quotes using explicit weights for price (35%), lead time (20%), quality (25%), and on-time delivery (20%). | Validate quote terms, supplier due diligence, and award approval. |
| `calculate_reorder_plan` | Calculates inventory position, reorder point, days of supply, and a suggested top-up quantity using demand, lead time, safety stock, and review-period inputs. | Validate forecasts, seasonality, pack sizes, and the replenishment decision. |
| `draft_rfq` | Creates a reusable RFQ subject and body with the supplier response fields to request. | Review and send through approved procurement channels. |

Quote ranking uses min-max normalization for price and lead time among eligible
offers, with the displayed weights applied to all four score components. Quotes
must use the same currency. An offer above the supplied budget or with an MOQ
above the requested quantity is excluded. If nothing is eligible, no supplier
is recommended. This is a transparent planning heuristic, not a sourcing policy
or supplier award.

The reorder point is `ceil(daily demand × (lead time + safety stock))`. The
target stock adds the review period, and the suggested quantity tops inventory
position (on-hand plus on-order) up to that target when at or below the reorder
point. Zero forecast demand never triggers an order.

## Architecture

```text
MCP clients ──> protocols/mcp ─┐
                               ├──> procurement_agent.service (shared logic)
A2A agents ───> protocols/a2a ─┘
```

Protocol adapters are optional dependencies and are kept in separate modules.
The core service has no runtime dependencies, databases, credentials, or
external integrations. A2A requests are explicit JSON skill envelopes; the
adapter does not invoke an LLM or infer purchasing decisions from free-form
text.

## Install

Python 3.11 or newer is required. In PowerShell from the project directory:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[all,dev]"
```

Install only the adapter you need with `.[mcp]` or `.[a2a]`. No API keys are
required.

## MCP server

Run the default stdio server:

```powershell
.\.venv\Scripts\python.exe -m procurement_agent.protocols.mcp.server
```

Configure an MCP host to launch that command from the cloned repository. For
example, a VS Code `.vscode/mcp.json` entry:

```json
{
  "servers": {
    "procurement-tools": {
      "type": "stdio",
      "command": "C:\\path\\to\\repository\\.venv\\Scripts\\python.exe",
      "args": ["-m", "procurement_agent.protocols.mcp.server"],
      "cwd": "C:\\path\\to\\repository"
    }
  }
}
```

The server exposes three tools matching the capability names above and a
`procurement://capabilities` resource. `compare_supplier_quotes` accepts
`quotes_json`, a JSON array with this shape:

```json
[
  {
    "supplier_name": "Northwind Components",
    "unit_price": 12.5,
    "currency": "USD",
    "lead_time_days": 8,
    "quality_score": 96,
    "on_time_rate": 94,
    "minimum_order_quantity": 1
  }
]
```

For Streamable HTTP on a local development machine:

```powershell
.\.venv\Scripts\python.exe -m procurement_agent.protocols.mcp.server --transport streamable-http
```

Do not expose an unauthenticated development server to an untrusted network.
Use your deployment platform's authentication, authorization, TLS, and network
controls before remote use.

## A2A agent

Run the A2A JSON-RPC adapter:

```powershell
.\.venv\Scripts\python.exe -m procurement_agent.protocols.a2a.server
```

The server listens on `http://127.0.0.1:9000` by default and publishes its
Agent Card at `/.well-known/agent-card.json`. Configure another local bind
address or port with `PROCUREMENT_A2A_HOST` and `PROCUREMENT_A2A_PORT`.

Send a text message containing a JSON envelope to the advertised A2A JSON-RPC
interface. The envelope shape is:

```json
{
  "skill": "calculate_reorder_plan",
  "input": {
    "on_hand_units": 120,
    "on_order_units": 20,
    "average_daily_demand": 15,
    "lead_time_days": 6,
    "safety_stock_days": 3,
    "review_period_days": 7
  }
}
```

Use the discovered Agent Card and the A2A SDK/client in your agent framework to
send the envelope as a user message. The completed A2A task artifact contains a
JSON result (or a clear validation error and the supported skill names).

## Use the core directly

The shared service can also be called without either protocol adapter:

```python
from procurement_agent.service import calculate_reorder_plan

plan = calculate_reorder_plan(
    on_hand_units=120,
    on_order_units=20,
    average_daily_demand=15,
    lead_time_days=6,
    safety_stock_days=3,
)
```

Invalid or incomplete input raises `ProcurementInputError` with a field-specific
message.

## Test

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## Protocol references and examples

- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) —
  typed tool functions, resources, and standard stdio / Streamable HTTP
  transports.
- [MCP server guide](https://modelcontextprotocol.io/docs/develop/build-server).
- [A2A Python SDK](https://github.com/a2aproject/a2a-python) and its
  [Hello World sample](https://github.com/a2aproject/a2a-samples/tree/main/samples/python/agents/helloworld)
  — Agent Card discovery, request handler, task executor, and JSON-RPC routes.
- [A2A protocol](https://a2a-protocol.org/latest/specification/) — agent-to-agent
  task collaboration. A2A complements MCP: MCP connects an agent to tools;
  A2A lets agents communicate with other agents.
- A retail procurement example,
  [Retail-Supply-Chain-MCP-ADK-Agentic-AI](https://github.com/Kaaleedass/Retail-Supply-Chain-MCP-ADK-Agentic-AI),
  informed the decision to keep domain logic reusable and protocol adapters
  separate; this project intentionally starts without a database or LLM.

## Production considerations

This repository is a small, auditable starter, not a complete procurement
system. Before production use, connect it to approved data sources, define
organization-specific sourcing and inventory policies, authenticate callers,
enforce tenant and role authorization, log/audit tool requests, and require
human approvals for commitments. Do not treat model-generated input or these
heuristic outputs as authoritative procurement records.

## License

MIT. See [LICENSE](LICENSE).
