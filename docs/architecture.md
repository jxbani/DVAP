# Architecture

Thirteen containers (fourteen with the local model) on one internal Docker network. Everything is simulated; nothing talks to
real equipment or, apart from the gateway, to anything outside the lab.

```mermaid
flowchart TB
  user(["You, on 127.0.0.1"])
  gateway["gateway<br/>reverse proxy, the only published service"]

  subgraph lab["Lab: internal Docker network, no internet"]
    subgraph ui["UIs"]
      scoreboard["scoreboard :8090"]
      hmi["hmi :8080"]
      cmms["cmms :8081<br/>tickets, untrusted"]
    end
    subgraph agents["Agents"]
      agent["agent-operator<br/>the victim LLM agent"]
      ollama["ollama<br/>local LLM"]
      vendor["vendor-analytics<br/>third-party MCP"]
      planner["maintenance-planner<br/>second agent"]
    end
    subgraph proc["Plant"]
      mcp["mcp-plant<br/>MCP tools + SafeEnvelope"]
      plc["plc<br/>Modbus/TCP + OPC UA"]
      sim["plant-sim<br/>10 Hz physics"]
      hist["historian"]
      bus[("bus<br/>Valkey (Redis)")]
      sandbox["sandbox<br/>hardened"]
    end
  end

  user --> gateway --> ui
  agent --> ollama
  agent -->|MCP| vendor
  agent -->|MCP| mcp
  mcp --> plc
  mcp --> cmms
  mcp --> hist
  mcp --> sandbox
  planner --> bus
  mcp --> bus
  plc <--> sim
  hmi --> sim
```

The agent touches the plant **only** through the MCP tools in `mcp-plant`. SafeEnvelope, when
enabled, sits inside `mcp-plant` between those tools and the PLC. The HMI and scoreboard also read
the historian and the bus; the historian polls the PLC.

## Services

| Service | What it is | Attack surface it teaches |
|---|---|---|
| `plant-sim` | Physics of the water-treatment process (tank level, inflow pump, drain valve, chlorine dosing and concentration) at 10 Hz, deterministic per seed | the physical consequences |
| `plc` | Virtual PLC: control logic and safety interlocks, exposed over Modbus/TCP and OPC UA ([register map](REGISTER_MAP.md)) | unauthenticated industrial protocols, writable string registers (C01b, C05) |
| `hmi` | Operator dashboard: live values, alarms, incident banner, the agent's activity, SafeEnvelope decisions | |
| `historian` | Time-series log of process values with a query API ([details](historian-and-hmi.md)) | forged sensor history (C08) |
| `cmms` | Maintenance tickets; anyone can file one ([details](cmms-and-memory.md)) | prompt injection through tickets (C01, C02, C03, C06) |
| `agent-operator` | The victim LLM agent: a small tool-calling loop over MCP ([details](agent-and-mcp.md)) | goal hijack, misleading approvals (C09) |
| `mcp-plant` | MCP server with the operator's tools, plus the agent's memory and scheduler | tool misuse, memory poisoning, rogue scheduled tasks (C02, C06, C10) |
| `vendor-analytics` | A "third-party" MCP server whose tool description changes after approval | supply chain, rug-pull (C04) |
| `maintenance-planner` | A second agent that posts work orders on the bus | inter-agent spoofing (C07) |
| `bus` | Valkey (Redis-compatible), unauthenticated | spoofed messages (C07) |
| `sandbox` | Runs the agent's diagnostics; hardened and confined | command injection (C05) |
| `scoreboard` | Challenges, per-challenge resets, flags, scoring | |
| `gateway` | nginx reverse proxy: the only service that publishes ports, on 127.0.0.1 | |
| `ollama` | The local model (only in `ollama` mode) | |

## Networks and containment

```mermaid
flowchart LR
  host(["host: 127.0.0.1:8080, :8081, :8090"]) --> gw["gateway"]
  subgraph edge["edge network (has a route out)"]
    gw
    pull["ollama-pull<br/>one-shot model download"]
  end
  subgraph plant["plant network: internal, no route out"]
    uis["hmi, cmms, scoreboard"]
    rest["every other lab service"]
  end
  gw --> uis
```

- Only the gateway publishes ports, and only on `127.0.0.1`. The UIs it forwards to are on the
  internal `plant` network with no route out, like every vulnerable service.
- The model download runs in a separate one-shot container that the lab never talks to.
- In `api` mode, and only then, the agent also joins `edge` to reach its provider.

The full containment list and how it was verified: [Lab safety](LAB_SAFETY.md).

## One agent cycle

```mermaid
sequenceDiagram
  participant A as agent-operator
  participant M as mcp-plant
  participant G as SafeEnvelope (if on)
  participant P as plc
  A->>M: read_process_values, read_alarms, read_device_strings, list_tickets, read_work_orders
  M-->>A: plant snapshot (tickets, strings and work orders are untrusted)
  A->>A: the model decides: read a ticket, call a tool, or write a shift log
  A->>M: set_setpoint(tag, value) + the context ids that led to it
  M->>G: check invariants, forecast, provenance, privilege
  G-->>M: allow / deny / review
  M->>P: Modbus write (only if allowed)
```

Every 30 seconds the agent reads the plant and acts. A supervisor can also message it, and decide
on the engineering actions it asks approval for, through its internal API (`/chat`, `/approvals`,
`/approve`); in C09 the scoreboard plays a busy human who approves anything labelled routine.
