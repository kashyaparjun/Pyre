defmodule PyreBridge.BridgeConnectionBackpressureTest do
  use ExUnit.Case, async: false

  alias PyreBridge.BridgeConnection
  alias PyreBridge.Codec
  alias PyreBridge.Framing

  test "returns busy error with additive flow-control fields when saturated" do
    previous_max_in_flight = Application.get_env(:pyre_bridge, :max_in_flight)
    previous_max_queue_depth = Application.get_env(:pyre_bridge, :max_queue_depth)
    previous_retry_after_ms = Application.get_env(:pyre_bridge, :retry_after_ms)

    on_exit(fn ->
      Application.put_env(:pyre_bridge, :max_in_flight, previous_max_in_flight)
      Application.put_env(:pyre_bridge, :max_queue_depth, previous_max_queue_depth)
      Application.put_env(:pyre_bridge, :retry_after_ms, previous_retry_after_ms)
    end)

    Application.put_env(:pyre_bridge, :max_in_flight, 1)
    Application.put_env(:pyre_bridge, :max_queue_depth, 0)
    Application.put_env(:pyre_bridge, :retry_after_ms, 25)

    {:ok, listen_socket} =
      :gen_tcp.listen(0, [:binary, {:packet, 0}, {:active, false}, {:reuseaddr, true}, {:ip, {127, 0, 0, 1}}])

    {:ok, {{127, 0, 0, 1}, port}} = :inet.sockname(listen_socket)

    server_task =
      Task.async(fn ->
        {:ok, server_socket} = :gen_tcp.accept(listen_socket)
        :ok = :gen_tcp.close(listen_socket)

        handler = fn %{type: "ping", correlation_id: correlation_id} ->
          Process.sleep(75)
          {:ok, %{correlation_id: correlation_id, type: "pong"}}
        end

        BridgeConnection.serve(server_socket, recv_timeout_ms: 25, handler: handler)
      end)

    {:ok, client_socket} =
      :gen_tcp.connect({127, 0, 0, 1}, port, [:binary, {:packet, 0}, {:active, false}])

    corr1 = "123e4567-e89b-12d3-a456-426614174000"
    corr2 = "223e4567-e89b-12d3-a456-426614174000"

    :ok = write_envelope(client_socket, %{correlation_id: corr1, type: "ping"})
    :ok = write_envelope(client_socket, %{correlation_id: corr2, type: "ping"})

    resp_a = read_envelope(client_socket)
    resp_b = read_envelope(client_socket)

    by_id = %{resp_a.correlation_id => resp_a, resp_b.correlation_id => resp_b}

    assert by_id[corr1].type == "pong"
    assert by_id[corr2].type == "error"
    assert by_id[corr2].error["type"] == "busy"
    assert by_id[corr2].retry_after_ms == 25
    assert is_integer(by_id[corr2].queue_depth)
    assert by_id[corr2].queue_depth >= 1
    assert is_binary(by_id[corr2].busy_reason)

    :ok = :gen_tcp.close(client_socket)
    assert :ok = Task.await(server_task, 1_000)
  end

  defp write_envelope(socket, envelope) do
    with {:ok, payload} <- Codec.pack_envelope(envelope),
         :ok <- Framing.write_frame(socket, payload) do
      :ok
    end
  end

  defp read_envelope(socket) do
    {:ok, payload} = Framing.read_frame(socket, 1_000)
    {:ok, envelope} = Codec.unpack_envelope(payload)
    envelope
  end
end
