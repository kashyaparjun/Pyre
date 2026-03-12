Application.put_env(:pyre_bridge, :port, 0)

{:ok, _pid} = Application.ensure_all_started(:pyre_bridge)
port = PyreBridge.BridgeServer.port()

IO.puts("PYRE_BRIDGE_PORT=#{port}")

Process.sleep(:infinity)
