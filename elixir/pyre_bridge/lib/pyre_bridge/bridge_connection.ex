defmodule PyreBridge.BridgeConnection do
  @moduledoc """
  Handles one bridge socket connection.
  """

  alias PyreBridge.Codec
  alias PyreBridge.Framing
  alias PyreBridge.AgentServer
  alias PyreBridge.AgentSupervisor
  alias PyreBridge.CounterHandler

  @spec serve(port(), keyword()) :: :ok
  def serve(socket, opts) do
    recv_timeout_ms = Keyword.get(opts, :recv_timeout_ms, 5_000)
    handler = Keyword.get(opts, :handler, &default_handler/1)
    loop(socket, recv_timeout_ms, handler)
  end

  defp loop(socket, recv_timeout_ms, handler) do
    case Framing.read_frame(socket, recv_timeout_ms) do
      {:ok, payload} ->
        with {:ok, envelope} <- Codec.unpack_envelope(payload),
             {:ok, response_envelope} <- handler.(envelope),
             {:ok, response_payload} <- Codec.pack_envelope(response_envelope),
             :ok <- Framing.write_frame(socket, response_payload) do
          loop(socket, recv_timeout_ms, handler)
        else
          _ -> :gen_tcp.close(socket)
        end

      {:error, _reason} ->
        :gen_tcp.close(socket)
    end
  end

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
    initial = Map.get(opts, "initial", 0)
    group = Map.get(opts, "group")

    start_opts =
      [name: agent_id, handler_module: CounterHandler, args: %{initial: initial}]
      |> maybe_put_group(group)

    case AgentSupervisor.start_agent(start_opts) do
      {:ok, _pid} = ok -> ok
      {:error, {:already_started, _pid}} -> {:error, :already_started}
      {:error, reason} -> {:error, reason}
    end
  end

  defp maybe_put_parent(opts, parent) when is_binary(parent), do: Keyword.put(opts, :parent, parent)
  defp maybe_put_parent(opts, _parent), do: opts

  defp maybe_put_group(opts, group) when is_binary(group), do: Keyword.put(opts, :group, group)
  defp maybe_put_group(opts, _group), do: opts

  defp maybe_put_max_restarts(opts, max_restarts) when is_integer(max_restarts) and max_restarts > 0,
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
