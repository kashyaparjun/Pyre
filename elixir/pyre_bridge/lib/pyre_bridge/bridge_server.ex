defmodule PyreBridge.BridgeServer do
  @moduledoc """
  TCP bridge listener (Phase 1 spike).

  Note: target production transport is Unix domain sockets; this spike uses TCP
  loopback for rapid cross-runtime validation.
  """

  use GenServer
  require Logger

  alias PyreBridge.BridgeConnection

  defstruct listen_socket: nil, accept_task: nil, port: nil, recv_timeout_ms: 5_000

  @type state :: %__MODULE__{
          listen_socket: port() | nil,
          accept_task: pid() | nil,
          port: non_neg_integer() | nil,
          recv_timeout_ms: non_neg_integer()
        }

  @spec start_link(keyword()) :: GenServer.on_start()
  def start_link(opts) do
    GenServer.start_link(__MODULE__, opts, name: __MODULE__)
  end

  @spec port() :: non_neg_integer() | nil
  def port do
    GenServer.call(__MODULE__, :port)
  end

  @impl true
  def init(opts) do
    host = Keyword.get(opts, :host, Application.get_env(:pyre_bridge, :host, {127, 0, 0, 1}))
    port = Keyword.get(opts, :port, Application.get_env(:pyre_bridge, :port, 4100))

    recv_timeout_ms =
      Keyword.get(opts, :recv_timeout_ms, Application.get_env(:pyre_bridge, :recv_timeout_ms, 5_000))

    listen_opts = [:binary, {:packet, 0}, {:active, false}, {:reuseaddr, true}, {:ip, host}]

    case :gen_tcp.listen(port, listen_opts) do
      {:ok, listen_socket} ->
        actual_port = extract_port(listen_socket)
        accept_task = Task.start_link(fn -> accept_loop(listen_socket, recv_timeout_ms) end)
        Logger.info("Pyre bridge listening on #{format_host(host)}:#{actual_port}")

        {:ok,
         %__MODULE__{
           listen_socket: listen_socket,
           accept_task: elem(accept_task, 1),
           port: actual_port,
           recv_timeout_ms: recv_timeout_ms
         }}

      {:error, reason} ->
        {:stop, reason}
    end
  end

  @impl true
  def handle_call(:port, _from, state) do
    {:reply, state.port, state}
  end

  @impl true
  def terminate(_reason, state) do
    if is_port(state.listen_socket) do
      :gen_tcp.close(state.listen_socket)
    end
  end

  defp accept_loop(listen_socket, recv_timeout_ms) do
    case :gen_tcp.accept(listen_socket) do
      {:ok, socket} ->
        {:ok, pid} =
          Task.start_link(fn ->
            receive do
              :serve -> BridgeConnection.serve(socket, recv_timeout_ms: recv_timeout_ms)
            end
          end)

        :ok = :gen_tcp.controlling_process(socket, pid)
        send(pid, :serve)
        accept_loop(listen_socket, recv_timeout_ms)

      {:error, :closed} ->
        :ok

      {:error, reason} ->
        Logger.error("Bridge accept loop stopped: #{inspect(reason)}")
        :ok
    end
  end

  defp extract_port(listen_socket) do
    {:ok, {_host, port}} = :inet.sockname(listen_socket)
    port
  end

  defp format_host({a, b, c, d}), do: "#{a}.#{b}.#{c}.#{d}"
end
