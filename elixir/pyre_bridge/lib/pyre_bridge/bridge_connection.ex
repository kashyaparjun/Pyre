defmodule PyreBridge.BridgeConnection do
  @moduledoc """
  Handles one bridge socket connection.
  """

  alias PyreBridge.AgentServer
  alias PyreBridge.AgentSupervisor
  alias PyreBridge.BridgeMetrics
  alias PyreBridge.Codec
  alias PyreBridge.CounterHandler
  alias PyreBridge.Framing
  alias PyreBridge.WorkflowHandler

  @spec serve(port(), keyword()) :: :ok
  def serve(socket, opts) do
    recv_timeout_ms = Keyword.get(opts, :recv_timeout_ms, 5_000)
    handler = Keyword.get(opts, :handler, &default_handler/1)
    {:ok, writer_pid} = Task.start_link(fn -> writer_loop(socket) end)

    state = %{
      socket: socket,
      recv_timeout_ms: recv_timeout_ms,
      handler: handler,
      writer_pid: writer_pid,
      max_in_flight: Application.get_env(:pyre_bridge, :max_in_flight, 0),
      max_queue_depth: Application.get_env(:pyre_bridge, :max_queue_depth, 0),
      retry_after_ms: Application.get_env(:pyre_bridge, :retry_after_ms, 10)
    }

    try do
      loop(state)
    after
      send(writer_pid, :stop)
      :gen_tcp.close(socket)
    end
  end

  defp loop(state) do
    case Framing.read_frame(state.socket, state.recv_timeout_ms) do
      {:ok, payload} ->
        case Codec.unpack_envelope(payload) do
          {:ok, envelope} ->
            _ = submit_or_backpressure(state, envelope)
            loop(state)

          {:error, _reason} ->
            :ok
        end

      {:error, :timeout} ->
        loop(state)

      {:error, _reason} ->
        :ok
    end
  end

  defp submit_or_backpressure(state, envelope) do
    queue_depth = BridgeMetrics.current_in_flight()

    cond do
      overloaded?(state.max_queue_depth, queue_depth) ->
        send_busy_response(state, envelope, queue_depth, "queue_depth_limit")

      not BridgeMetrics.try_reserve_in_flight(state.max_in_flight) ->
        send_busy_response(state, envelope, queue_depth, "in_flight_limit")

      true ->
        # Optimized: Use spawn_link instead of Task.Supervisor for lower overhead
        parent = self()

        spawn_link(fn ->
          try do
            response_envelope = execute_envelope(envelope, state.handler)
            send(state.writer_pid, {:write, response_envelope})
          after
            BridgeMetrics.release_in_flight()
          end
        end)

        state
    end
  end

  defp execute_envelope(envelope, handler) do
    case handler.(envelope) do
      {:ok, response_envelope} -> response_envelope
      {:error, reason} -> error_response(envelope.correlation_id, envelope.agent_id, reason)
    end
  end

  defp writer_loop(socket) do
    receive do
      :stop ->
        :ok

      {:write, response_envelope} ->
        _ =
          with {:ok, response_payload} <- Codec.pack_envelope(response_envelope),
               :ok <- Framing.write_frame(socket, response_payload) do
            :ok
          end

        writer_loop(socket)
    end
  end

  defp send_busy_response(state, envelope, queue_depth, busy_reason) do
    BridgeMetrics.increment_backpressure()

    busy = %{
      correlation_id: envelope.correlation_id,
      type: "error",
      agent_id: Map.get(envelope, :agent_id) || "bridge",
      error: %{type: "busy", message: "bridge is saturated"},
      queue_depth: queue_depth,
      retry_after_ms: state.retry_after_ms,
      busy_reason: busy_reason
    }

    send(state.writer_pid, {:write, busy})
    state
  end

  defp overloaded?(max_depth, depth)
       when is_integer(max_depth) and max_depth > 0 and is_integer(depth) and depth >= max_depth,
       do: true

  defp overloaded?(_max_depth, _depth), do: false

  defp default_handler(%{type: "ping", correlation_id: correlation_id}) do
    {:ok, %{correlation_id: correlation_id, type: "pong"}}
  end

  defp default_handler(%{
         type: "execute",
         correlation_id: correlation_id,
         agent_id: agent_id,
         handler: handler,
         state: state,
         message: message
       }) do
    case unpack_message_payload(message) do
      {:ok, msg_payload} ->
        case execute_agent_call(agent_id, handler, msg_payload) do
          {:ok, response} ->
            {:ok,
             %{
               correlation_id: correlation_id,
               type: "result",
               agent_id: agent_id,
               state: state,
               reply: response
             }}

          {:fallback, :legacy} ->
            {:ok,
             %{
               correlation_id: correlation_id,
               type: "result",
               agent_id: agent_id,
               state: state,
               reply: message
             }}

          {:error, reason} ->
            {:ok, error_response(correlation_id, agent_id, reason)}
        end

      {:error, :invalid_execute_payload} ->
        {:ok,
         %{
           correlation_id: correlation_id,
           type: "result",
           agent_id: agent_id,
           state: state,
           reply: message
         }}

      {:error, reason} ->
        {:ok, error_response(correlation_id, agent_id, reason)}
    end
  end

  defp default_handler(%{
         type: "spawn",
         correlation_id: correlation_id,
         agent_id: agent_id,
         message: message
       }) do
    with {:ok, opts} <- unpack_spawn_options(message),
         :ok <- ensure_group(opts),
         {:ok, _pid} <- spawn_agent(agent_id, opts) do
      {:ok,
       %{
         correlation_id: correlation_id,
         type: "result",
         agent_id: agent_id,
         state: <<>>,
         reply: <<>>
       }}
    else
      {:error, reason} ->
        {:ok, error_response(correlation_id, agent_id, reason)}
    end
  end

  defp default_handler(%{
         type: "stop",
         correlation_id: correlation_id,
         agent_id: agent_id
       }) do
    case AgentSupervisor.stop_agent(agent_id) do
      :ok ->
        {:ok,
         %{
           correlation_id: correlation_id,
           type: "result",
           agent_id: agent_id,
           state: <<>>,
           reply: <<>>
         }}

      {:error, reason} ->
        {:ok, error_response(correlation_id, agent_id, reason)}
    end
  end

  defp default_handler(%{correlation_id: correlation_id}) do
    {:ok,
     %{
       correlation_id: correlation_id,
       type: "error",
       agent_id: "bridge",
       error: %{type: "unsupported_message", message: "unsupported message type"}
     }}
  end

  defp unpack_message_payload(message) do
    with {:ok, decoded} <- Codec.unpack_payload(message),
         %{} = map <- decoded,
         type when is_binary(type) <- Map.get(map, "type"),
         %{} = payload <- Map.get(map, "payload") do
      {:ok, {type, payload}}
    else
      _ -> {:error, :invalid_execute_payload}
    end
  end

  defp execute_agent_call(agent_id, _handler, {type, payload}) do
    case AgentServer.call(agent_id, type, payload) do
      {:ok, reply} ->
        with {:ok, packed_reply} <- Codec.pack_payload(%{"reply" => reply}) do
          {:ok, :erlang.iolist_to_binary(packed_reply)}
        end

      {:error, :noproc} ->
        {:error, :noproc}

      {:error, reason} ->
        {:error, reason}
    end
  end

  defp unpack_spawn_options(nil), do: {:ok, %{}}
  defp unpack_spawn_options(<<>>), do: {:ok, %{}}

  defp unpack_spawn_options(message) do
    case Codec.unpack_payload(message) do
      {:ok, %{} = opts} -> {:ok, opts}
      {:ok, _other} -> {:error, :invalid_spawn_payload}
      {:error, reason} -> {:error, reason}
    end
  end

  defp ensure_group(%{"group" => group, "strategy" => strategy} = opts)
       when is_binary(group) and is_binary(strategy) do
    parent = Map.get(opts, "parent")
    max_restarts = Map.get(opts, "max_restarts")
    within_ms = Map.get(opts, "within_ms")

    group_opts =
      [strategy: to_strategy_atom(strategy)]
      |> maybe_put_parent(parent)
      |> maybe_put_max_restarts(max_restarts)
      |> maybe_put_max_seconds(within_ms)

    case AgentSupervisor.create_group(group, group_opts) do
      {:ok, _pid} -> :ok
      {:error, {:already_started, _pid}} -> :ok
      {:error, reason} -> {:error, reason}
    end
  end

  defp ensure_group(%{"group" => group}) when is_binary(group) do
    case AgentSupervisor.create_group(group, strategy: :one_for_one) do
      {:ok, _pid} -> :ok
      {:error, {:already_started, _pid}} -> :ok
      {:error, reason} -> {:error, reason}
    end
  end

  defp ensure_group(_opts), do: :ok

  defp spawn_agent(agent_id, opts) do
    handler_module = handler_module_for(opts)
    group = Map.get(opts, "group")

    start_opts =
      [name: agent_id, handler_module: handler_module, args: handler_args(agent_id, opts)]
      |> maybe_put_group(group)

    case AgentSupervisor.start_agent(start_opts) do
      {:ok, _pid} = ok -> ok
      {:error, {:already_started, _pid}} -> {:error, :already_started}
      {:error, reason} -> {:error, reason}
    end
  end

  defp handler_module_for(%{"handler" => "workflow"}), do: WorkflowHandler
  defp handler_module_for(_opts), do: CounterHandler

  defp handler_args(agent_id, %{"handler" => "workflow"} = opts) do
    role = Map.get(opts, "role", "worker")

    %{
      role: role,
      worker_id: Map.get(opts, "worker_id", agent_id)
    }
  end

  defp handler_args(_agent_id, opts) do
    %{initial: Map.get(opts, "initial", 0)}
  end

  defp maybe_put_parent(opts, parent) when is_binary(parent),
    do: Keyword.put(opts, :parent, parent)

  defp maybe_put_parent(opts, _parent), do: opts

  defp maybe_put_group(opts, group) when is_binary(group), do: Keyword.put(opts, :group, group)
  defp maybe_put_group(opts, _group), do: opts

  defp maybe_put_max_restarts(opts, max_restarts)
       when is_integer(max_restarts) and max_restarts > 0,
       do: Keyword.put(opts, :max_restarts, max_restarts)

  defp maybe_put_max_restarts(opts, _max_restarts), do: opts

  defp maybe_put_max_seconds(opts, within_ms) when is_integer(within_ms) and within_ms > 0 do
    seconds = max(div(within_ms, 1000), 1)
    Keyword.put(opts, :max_seconds, seconds)
  end

  defp maybe_put_max_seconds(opts, _within_ms), do: opts

  defp to_strategy_atom("one_for_one"), do: :one_for_one
  defp to_strategy_atom("one_for_all"), do: :one_for_all
  defp to_strategy_atom("rest_for_one"), do: :rest_for_one
  defp to_strategy_atom(_), do: :one_for_one

  defp error_response(correlation_id, agent_id, reason) do
    %{
      correlation_id: correlation_id,
      type: "error",
      agent_id: agent_id || "bridge",
      error: %{type: "bridge_error", message: inspect(reason)}
    }
  end
end
