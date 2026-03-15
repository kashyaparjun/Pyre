# Python <-> Elixir Bridge Contract

This contract defines the current cross-runtime integration target between:

- Python client: `src/pyre_agents/bridge/transport.py`
- Elixir server: `elixir/pyre_bridge/lib/pyre_bridge/bridge_server.ex`

## Transport and framing

- Transport: TCP loopback (`127.0.0.1:<port>`)
- Framing: 4-byte unsigned big-endian payload length + raw MessagePack payload

Frame format:

```text
[4 bytes length][N bytes msgpack envelope]
```

## Envelope schema

Required common fields:

- `correlation_id` (string UUID)
- `type` (string enum)

Supported `type` values:

- `execute`, `result`, `error`, `register`, `deregister`, `spawn`, `stop`, `ping`, `pong`

Type-specific required fields:

- `execute`: `agent_id`, `handler`, `state`, `message`
- `result`: `agent_id`, `state`
- `error`: `agent_id`, `error`
- `register|deregister|spawn|stop`: `agent_id`

## Compatibility behaviors

1. `ping` request -> `pong` response with same `correlation_id`.
2. `execute` request -> `result` response with:
   - same `correlation_id`
   - same `agent_id`
   - `state` echoed for the legacy execute path
   - `reply` contains either the legacy echo payload or a packed call result
3. `spawn` request may create a bridge-side agent and optionally define or join a supervisor group.
4. `stop` request stops a previously spawned bridge-side agent.
5. Group options supported by the Python integration harness:
   - `group`
   - `strategy`
   - `parent`
   - `max_restarts`
   - `within_ms`
6. Malformed frame or invalid envelope:
   - connection is closed by server
   - no response frame is guaranteed

## Cross-runtime integration test contract

Current integration test coverage (Python test suite against running Elixir server):

1. `test_elixir_ping_pong_roundtrip`
2. `test_elixir_execute_result_roundtrip`
3. `test_elixir_rejects_unknown_message_type`
4. `test_elixir_rejects_malformed_msgpack`
5. `test_elixir_supervision_one_for_all_over_bridge`
6. `test_elixir_supervision_rest_for_one_over_bridge`
7. `test_elixir_supervision_restart_intensity_terminates_group`

## Startup contract

The Elixir runtime exposes the listen port via:

- stdout structured line: `PYRE_BRIDGE_PORT=<port>`

Python integration harness will:

1. spawn Elixir runtime process
2. discover port
3. run roundtrip tests
4. terminate process
