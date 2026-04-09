defmodule PyreBridge.BridgeConnection do
  @moduledoc """
  Handles one bridge socket connection with optional request batching.
  """

  alias PyreBridge.AgentServer
  alias PyreBridge.AgentSupervisor
  alias PyreBridge.BridgeMetrics
  alias PyreBridge.Codec
  alias PyreBridge.CounterHandler
  alias PyreBridge.Framing
  alias PyreBridge.WorkflowHandler

  # Default batching configuration
  @default_batch_size 10
  @default_batch_timeout_ms 5

  @spec serve(port(), keyword()) :: :ok
  def serve(socket, opts) do
    recv_timeout_ms = Keyword.get(opts, :recv_timeout_ms, 5_000)
    handler = Keyword.get(opts, :handler, &default_handler/1)

    # Check if batching is enabled via opts or application env
    enable_batching =
      Keyword.get(
        opts,
        :enable_batching,
        Application.get_env(:pyre_bridge, :enable_batching, false)
      )

    batch_size =
      Keyword.get(
        opts,
        :batch_size,
        Application.get_env(:pyre_bridge, :batch_size, @default_batch_size)
      )

    batch_timeout_ms =
      Keyword.get(
        opts,
        :batch_timeout_ms,
        Application.get_env(:pyre_bridge, :batch_timeout_ms, @default_batch_timeout_ms)
      )

    {:ok, writer_pid} = Task.start_link(fn -> writer_loop(socket) end)

    state = %{
      socket: socket,
      recv_timeout_ms: recv_timeout_ms,
      handler: handler,
      writer_pid: writer_pid,
      max_in_flight: Application.get_env(:pyre_bridge, :max_in_flight, 0),
      max_queue_depth: Application.get_env(:pyre_bridge, :max_queue_depth, 0),
      retry_after_ms: Application.get_env(:pyre_bridge, :retry_after_ms, 10),
      # Batching configuration
      enable_batching: enable_batching,
      batch_size: batch_size,
      batch_timeout_ms: batch_timeout_ms,
      # Batching state
      batch_buffer: [],
      batch_timer: nil,
      batch_parent: self()
    }

    try do
      loop(state)
    after
      # Flush any pending batch before closing
      if state.enable_batching and state.batch_buffer != [] do
        do_flush_batch(state)
      end

      send(writer_pid, :stop)
      :gen_tcp.close(socket)
    end
  end

  # Main receive loop with batching support
  defp loop(state) do
    # Use shorter timeout if we have a pending batch
    timeout =
      if state.batch_timer != nil do
        min(state.recv_timeout_ms, state.batch_timeout_ms)
      else
        state.recv_timeout_ms
      end

    receive do
      # Handle batch flush timer
      {:flush_batch, parent_pid} when parent_pid == state.batch_parent ->
        new_state = do_flush_batch(%{state | batch_timer: nil})
        loop(new_state)

      # Handle stop signal
      :stop ->
        :ok

      # Handle other messages
      _other ->
        loop(state)
    after
      timeout ->
        # Timeout - check if we need to flush batch due to timeout
        state =
          if state.batch_timer != nil and state.batch_buffer != [] do
            # Timer expired, flush the batch
            do_flush_batch(%{state | batch_timer: nil})
          else
            state
          end

        # Read next frame
        case Framing.read_frame(state.socket, 0) do
          {:ok, payload} ->
            case Codec.unpack_envelope(payload) do
              {:ok, envelope} ->
                new_state = process_envelope(state, envelope)
                loop(new_state)

              {:error, _reason} ->
                loop(state)
            end

          {:error, :timeout} ->
            # No data available, continue loop
            loop(state)

          {:error, _reason} ->
            # Connection error, exit
            :ok
        end
    end
  end

  # Process a single envelope
  defp process_envelope(state, envelope) do
    queue_depth = BridgeMetrics.current_in_flight()

    cond do
      overloaded?(state.max_queue_depth, queue_depth) ->
        send_busy_response(state, envelope, queue_depth, "queue_depth_limit")
        state

      not BridgeMetrics.try_reserve_in_flight(state.max_in_flight) ->
        send_busy_response(state, envelope, queue_depth, "in_flight_limit")
        state

      true ->
        # Check if we should use batching
        case envelope do
          %{type: "ping", correlation_id: correlation_id} ->
            # Ping always handled immediately
            send(state.writer_pid, {:write, %{correlation_id: correlation_id, type: "pong"}})
            BridgeMetrics.release_in_flight()
            state

          _ when state.enable_batching ->
            # Add to batch buffer
            add_to_batch(state, envelope)

          _ ->
            # Batching disabled - spawn immediately
            spawn_single(state, envelope)
            state
        end
    end
  end

  # Add envelope to batch buffer
  defp add_to_batch(state, envelope) do
    new_buffer = [envelope | state.batch_buffer]

    if length(new_buffer) >= state.batch_size do
      # Batch is full - flush immediately
      new_state = %{state | batch_buffer: new_buffer}
      do_flush_batch(new_state)
    else
      # Start batch timer if not already running
      timer =
        state.batch_timer ||
          Process.send_after(
            state.batch_parent,
            {:flush_batch, state.batch_parent},
            state.batch_timeout_ms
          )

      %{state | batch_buffer: new_buffer, batch_timer: timer}
    end
  end

  # Flush the current batch
  defp do_flush_batch(%{batch_buffer: []} = state), do: %{state | batch_timer: nil}

  defp do_flush_batch(state) do
    batch = Enum.reverse(state.batch_buffer)
    batch_count = length(batch)

    # Cancel timer if running
    if state.batch_timer do
      Process.cancel_timer(state.batch_timer)
    end

    # Spawn ONE process for entire batch
    Task.Supervisor.start_child(PyreBridge.BridgeExecutionSupervisor, fn ->
      try do
        # Process all envelopes in batch
        Enum.each(batch, fn envelope ->
          response = execute_envelope(envelope, state.handler)
          send(state.writer_pid, {:write, response})
        end)

        # Release in-flight for entire batch
        for _ <- 1..batch_count do
          BridgeMetrics.release_in_flight()
        end
      catch
        _kind, _reason ->
          # On error, still release in-flight
          for _ <- 1..batch_count do
            BridgeMetrics.release_in_flight()
          end
      end
    end)

    # Clear buffer and timer
    %{state | batch_buffer: [], batch_timer: nil}
  end

  # Spawn single task (non-batched mode)
  defp spawn_single(state, envelope) do
    Task.Supervisor.start_child(PyreBridge.BridgeExecutionSupervisor, fn ->
      try do
        response = execute_envelope(envelope, state.handler)
        send(state.writer_pid, {:write, response})
      after
        BridgeMetrics.release_in_flight()
      end
    end)
  end

  defp execute_envelope(envelope, handler) do
    case handler.(envelope) do
      {:ok, response} -> response
      {:error, reason} -> error_response(envelope.correlation_id, envelope.agent_id, reason)
    end
  end

  defp writer_loop(socket) do
    receive do
      :stop ->
        :ok

      {:write, response} ->
        with {:ok, payload} <- Codec.pack_envelope(response),
             :ok <- Framing.write_frame(socket, payload) do
          :ok
        end

        writer_loop(socket)
    end
  end

  defp send_busy_response(state, envelope, queue_depth, reason) do
    BridgeMetrics.increment_backpressure()

    busy = %{
      correlation_id: Map.get(envelope, :correlation_id, "unknown"),
      type: "error",
      agent_id: Map.get(envelope, :agent_id) || "bridge",
      error: %{type: "busy", message: "bridge is saturated"},
      queue_depth: queue_depth,
      retry_after_ms: state.retry_after_ms,
      busy_reason: reason
    }

    send(state.writer_pid, {:write, busy})
    state
  end

  defp overloaded?(max_depth, depth)
       when is_integer(max_depth) and max_depth > 0 and is_integer(depth) and depth >= max_depth,
       do: true

  defp overloaded?(_max_depth, _depth), do: false

  defp default_handler(%{type: "ping", correlation_id: id}) do
    {:ok, %{correlation_id: id, type: "pong"}}
  end

  defp default_handler(%{
         type: "execute",
         correlation_id: correlation_id,
         agent_id: agent_id,
         handler: _handler,
         state: state_data,
         message: message
       }) do
    case unpack_message_payload(message) do
      {:ok, msg_payload} ->
        case execute_agent_call(agent_id, state_data, msg_payload) do
          {:ok, reply, new_state} ->
            {:ok,
             %{
               correlation_id: correlation_id,
               type: "result",
               agent_id: agent_id,
               state: :erlang.term_to_binary(new_state),
               reply: :erlang.term_to_binary(%{"reply" => reply})
             }}

          {:fallback, :legacy} ->
            {:ok,
             %{
               correlation_id: correlation_id,
               type: "result",
               agent_id: agent_id,
               state: state_data,
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
           state: state_data,
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
    try do
      decoded = :erlang.binary_to_term(message)

      if is_map(decoded) do
        type = Map.get(decoded, "type")
        payload = Map.get(decoded, "payload", %{})
        {:ok, {type, payload}}
      else
        {:error, :invalid_execute_payload}
      end
    catch
      _ -> {:error, :invalid_execute_payload}
    end
  end

  defp execute_agent_call(agent_id, _state_data, {type, payload}) do
    case AgentServer.call(agent_id, type, payload) do
      {:ok, reply} -> {:ok, reply, %{}}
      {:error, :noproc} -> {:error, :noproc}
      {:error, reason} -> {:error, reason}
    end
  end

  defp unpack_spawn_options(nil), do: {:ok, %{}}
  defp unpack_spawn_options(<<>>), do: {:ok, %{}}

  defp unpack_spawn_options(message) do
    try do
      decoded = :erlang.binary_to_term(message)
      if is_map(decoded), do: {:ok, decoded}, else: {:ok, %{}}
    catch
      _ -> {:ok, %{}}
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
    %{role: role, worker_id: Map.get(opts, "worker_id", agent_id)}
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
