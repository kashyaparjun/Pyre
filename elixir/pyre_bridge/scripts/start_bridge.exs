Application.put_env(:pyre_bridge, :port, 0)

{:ok, _pid} = Application.ensure_all_started(:pyre_bridge)
port = PyreBridge.BridgeServer.port()
uds_path = PyreBridge.BridgeServer.uds_path()

if is_integer(port), do: IO.puts("PYRE_BRIDGE_PORT=#{port}")
if is_binary(uds_path), do: IO.puts("PYRE_BRIDGE_UDS_PATH=#{uds_path}")

Process.sleep(:infinity)
