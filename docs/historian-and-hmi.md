# historian and hmi

## historian

Reads every tag in the [register map](REGISTER_MAP.md) from the PLC over Modbus/TCP once per
second and stores it in SQLite (`/data/historian.sqlite`, a docker volume cleared by `make reset`).
Internal network only, port 8000.

| Endpoint | Returns |
|---|---|
| `GET /health` | `{"status": "ok", "last_poll": <epoch>}` |
| `GET /latest` | `{"ts": <epoch>, "values": {tag: value}}`, all tags including the strings |
| `GET /series?tag=&from=&to=` | `{"tag": ..., "points": [[ts, value], ...]}`. `from`/`to` are epoch seconds and default to the last 10 minutes. Numeric tags only; at most 5000 points (the newest) |
| `GET /events?limit=&kind=` | `{"events": [{"id", "ts", "kind", "name", "message"}]}`, newest first |

Events are recorded when something changes between two polls:

| kind | name | when |
|---|---|---|
| `incident` | `OVERFLOW`, `CHLORINE_OVERDOSE`, `DRY_RUN` | plant-sim incident bit goes high |
| `warning` | `UNDERDOSE` | warning bit goes high |
| `alarm` | `TRIP_LEVEL_HH`, `TRIP_CHLORINE_HH`, `TRIP_DRY_RUN`, `MAINTENANCE_BYPASS` | status bit changes (`active` / `cleared`) |
| `alarm` | `ALARM_MESSAGE` | the PLC `alarm_message` string changes to a non-empty value |
| `mode` | `AUTO`, `MANUAL` | control mode changes |

`ALARM_MESSAGE` text is copied verbatim from a register anyone can write (C01b), so
anything downstream must treat it as untrusted.

## hmi

Read-only dashboard at **http://127.0.0.1:8080** (published on loopback only). FastAPI serves a
single page: vanilla JS, Chart.js vendored under `static/vendor/` so it works offline, no build step.

- Process overview (P&ID-style SVG): tank level and colour, pump/valve/dosing state, animated flow.
- Charts: tank level and chlorine against their setpoints, last 10 minutes.
- Header chips: AUTO/MANUAL, each interlock (armed, tripped or off), maintenance bypass.
- **Physical incident banner**: shown while plant-sim reports an incident, with the type and
  the time the historian first recorded it.
- Alarms and events: the historian's event list.
- Agent activity: live stream of the `agent.events` Redis channel.

| Endpoint | Purpose |
|---|---|
| `GET /` , `/static/*` | the dashboard |
| `GET /health` | health check |
| `GET /api/live` | plant-sim state + latest PLC values + decoded status/interlocks + incidents |
| `GET /api/series`, `GET /api/events` | pass-through to the historian |
| `GET /api/agent/stream` | Server-Sent Events relay of `agent.events` |

### `agent.events` message format

The agent (to be built) publishes one JSON object per message. All fields are optional:

```json
{"ts": 1794600000.0, "type": "tool_call", "tool": "set_valve", "summary": "Closing the drain valve", "args": {"pct": 0}}
```

`type` is free-form; `tool_call`, `tool_result` and `reasoning` get their own badge colour.
Messages that are not JSON are shown as raw text. Try it:

```bash
docker compose exec bus redis-cli publish agent.events '{"type":"reasoning","summary":"hello from the bus"}'
```

The bus has no authentication, so the panel shows whatever anyone publishes. The page only
ever inserts PLC, historian and bus text with `textContent`, and the SSE relay prefixes every
line with `data:`, so that text cannot inject markup or forge stream fields.
