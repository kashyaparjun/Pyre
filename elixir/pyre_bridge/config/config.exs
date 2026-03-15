import Config

parse_int = fn env_name, default ->
  case System.get_env(env_name) do
    nil -> default
    value -> String.to_integer(value)
  end
end

parse_ip = fn env_name, default ->
  case System.get_env(env_name) do
    nil ->
      default

    value ->
      case :inet.parse_address(String.to_charlist(value)) do
        {:ok, address} -> address
        {:error, _reason} -> raise "invalid #{env_name}: #{inspect(value)}"
      end
  end
end

parse_transport_mode = fn env_name, default ->
  case System.get_env(env_name) do
    nil ->
      default

    "tcp" ->
      :tcp

    "uds" ->
      :uds

    "both" ->
      :both

    value ->
      raise "invalid #{env_name}: #{inspect(value)}"
  end
end

parse_bool = fn env_name, default ->
  case System.get_env(env_name) do
    nil ->
      default

    value ->
      case String.downcase(value) do
        "1" -> true
        "true" -> true
        "yes" -> true
        "on" -> true
        "0" -> false
        "false" -> false
        "no" -> false
        "off" -> false
        other -> raise "invalid #{env_name}: #{inspect(other)}"
      end
  end
end

perf_mode = parse_bool.("PYRE_BRIDGE_PERF_MODE", false)

acceptor_default = if perf_mode, do: 8, else: 2
connection_workers_default = if perf_mode, do: 2048, else: 256
execution_workers_default = if perf_mode, do: 2048, else: 256
max_in_flight_default = if perf_mode, do: 2048, else: 0
max_queue_depth_default = if perf_mode, do: 4096, else: 0
retry_after_ms_default = if perf_mode, do: 5, else: 10

config :pyre_bridge,
  transport: :tcp,
  perf_mode: perf_mode,
  transport_mode: parse_transport_mode.("PYRE_BRIDGE_TRANSPORT_MODE", :tcp),
  host: parse_ip.("PYRE_BRIDGE_HOST", {127, 0, 0, 1}),
  port: parse_int.("PYRE_BRIDGE_PORT", 4100),
  uds_path: System.get_env("PYRE_BRIDGE_UDS_PATH", "/tmp/pyre_bridge.sock"),
  recv_timeout_ms: parse_int.("PYRE_BRIDGE_RECV_TIMEOUT_MS", 5_000),
  acceptor_count: parse_int.("PYRE_BRIDGE_ACCEPTOR_COUNT", acceptor_default),
  connection_worker_limit:
    parse_int.("PYRE_BRIDGE_CONNECTION_WORKER_LIMIT", connection_workers_default),
  execution_worker_limit:
    parse_int.("PYRE_BRIDGE_EXECUTION_WORKER_LIMIT", execution_workers_default),
  max_in_flight: parse_int.("PYRE_BRIDGE_MAX_IN_FLIGHT", max_in_flight_default),
  max_queue_depth: parse_int.("PYRE_BRIDGE_MAX_QUEUE_DEPTH", max_queue_depth_default),
  retry_after_ms: parse_int.("PYRE_BRIDGE_RETRY_AFTER_MS", retry_after_ms_default),
  group_max_restarts: parse_int.("PYRE_BRIDGE_GROUP_MAX_RESTARTS", 3),
  group_max_seconds: parse_int.("PYRE_BRIDGE_GROUP_MAX_SECONDS", 5)
