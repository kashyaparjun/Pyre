defmodule PyreBridge.BridgeServer do
  @moduledoc """
  Bridge listener with bounded connection workers and configurable TCP/UDS transport modes.
  """

  use GenServer
  require Logger

  alias PyreBridge.BridgeConnection
  alias PyreBridge.BridgeMetrics

  defstruct listeners: [], accept_tasks: [], tcp_port: nil, uds_path: nil, recv_timeout_ms: 5_000

  @type listener_ref :: {:tcp, port()} | {:uds, port()}
  @type state :: %__MODULE__{
          listeners: [listener_ref()],
          accept_tasks: [pid()],
          tcp_port: non_neg_integer() | nil,
          uds_path: String.t() | nil,
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

  @spec uds_path() :: String.t() | nil
  def uds_path do
    GenServer.call(__MODULE__, :uds_path)
  end

  @spec metrics() :: map()
  def metrics do
    BridgeMetrics.snapshot()
  end

  @impl true
  def init(opts) do
    transport_mode = Keyword.get(opts, :transport_mode, Application.get_env(:pyre_bridge, :transport_mode, :tcp))
    host = Keyword.get(opts, :host, Application.get_env(:pyre_bridge, :host, {127, 0, 0, 1}))
    port = Keyword.get(opts, :port, Application.get_env(:pyre_bridge, :port, 4100))

    uds_path =
      Keyword.get(opts, :uds_path, Application.get_env(:pyre_bridge, :uds_path, "/tmp/pyre_bridge.sock"))

    recv_timeout_ms =
      Keyword.get(opts, :recv_timeout_ms, Application.get_env(:pyre_bridge, :recv_timeout_ms, 5_000))

    acceptor_count =
      Keyword.get(opts, :acceptor_count, Application.get_env(:pyre_bridge, :acceptor_count, 2))

    with {:ok, listeners, tcp_port, effective_uds_path} <-
           start_listeners(transport_mode, host, port, uds_path),
         {:ok, accept_tasks} <- start_acceptors(listeners, recv_timeout_ms, acceptor_count) do
      if tcp_port != nil do
        Logger.info("Pyre bridge TCP listening on #{format_host(host)}:#{tcp_port}")
      end

      if effective_uds_path != nil do
        Logger.info("Pyre bridge UDS listening on #{effective_uds_path}")
      end

      {:ok,
       %__MODULE__{
         listeners: listeners,
         accept_tasks: accept_tasks,
         tcp_port: tcp_port,
         uds_path: effective_uds_path,
         recv_timeout_ms: recv_timeout_ms
       }}
    else
      {:error, reason} -> {:stop, reason}
    end
  end

  @impl true
  def handle_call(:port, _from, state) do
    {:reply, state.tcp_port, state}
  end

  @impl true
  def handle_call(:uds_path, _from, state) do
    {:reply, state.uds_path, state}
  end

  @impl true
  def terminate(_reason, state) do
    Enum.each(state.listeners, fn
      {_kind, listen_socket} ->
        :gen_tcp.close(listen_socket)
    end)

    if is_binary(state.uds_path) do
      File.rm(state.uds_path)
    end
  end

  defp start_listeners(:tcp, host, port, _uds_path) do
    with {:ok, tcp_socket} <- listen_tcp(host, port) do
      actual_port = extract_tcp_port(tcp_socket)
      {:ok, [{:tcp, tcp_socket}], actual_port, nil}
    end
  end

  defp start_listeners(:uds, _host, _port, uds_path) do
    with {:ok, uds_socket} <- listen_uds(uds_path) do
      {:ok, [{:uds, uds_socket}], nil, uds_path}
    end
  end

  defp start_listeners(:both, host, port, uds_path) do
    case listen_tcp(host, port) do
      {:ok, tcp_socket} ->
        case listen_uds(uds_path) do
          {:ok, uds_socket} ->
            actual_port = extract_tcp_port(tcp_socket)
            {:ok, [{:tcp, tcp_socket}, {:uds, uds_socket}], actual_port, uds_path}

          {:error, reason} ->
            :gen_tcp.close(tcp_socket)
            _ = File.rm(uds_path)
            {:error, reason}
        end

      {:error, reason} ->
        {:error, reason}
    end
  end

  defp start_listeners(other, _host, _port, _uds_path), do: {:error, {:invalid_transport_mode, other}}

  defp listen_tcp(host, port) do
    listen_opts = [:binary, {:packet, 0}, {:active, false}, {:reuseaddr, true}, {:ip, host}]
    :gen_tcp.listen(port, listen_opts)
  end

  defp listen_uds(path) do
    _ = File.rm(path)

    listen_opts = [
      :binary,
      {:packet, 0},
      {:active, false},
      {:reuseaddr, true},
      {:ifaddr, {:local, String.to_charlist(path)}}
    ]

    :gen_tcp.listen(0, listen_opts)
  end

  defp start_acceptors(listeners, recv_timeout_ms, acceptor_count) do
    task_specs =
      for {kind, socket} <- listeners,
          _ <- 1..max(acceptor_count, 1) do
        {kind, socket, recv_timeout_ms}
      end

    tasks =
      Enum.map(task_specs, fn {kind, socket, timeout_ms} ->
        {:ok, pid} = Task.start_link(fn -> accept_loop(kind, socket, timeout_ms) end)
        pid
      end)

    {:ok, tasks}
  end

  defp accept_loop(kind, listen_socket, recv_timeout_ms) do
    case :gen_tcp.accept(listen_socket) do
      {:ok, socket} ->
        case Task.Supervisor.start_child(PyreBridge.BridgeConnectionSupervisor, fn ->
               receive do
                 :serve -> BridgeConnection.serve(socket, recv_timeout_ms: recv_timeout_ms)
               end
             end) do
          {:ok, pid} ->
            :ok = :gen_tcp.controlling_process(socket, pid)
            send(pid, :serve)

          {:error, :max_children} ->
            BridgeMetrics.increment_backpressure()
            :gen_tcp.close(socket)

          {:error, reason} ->
            Logger.error("Failed to start connection worker: #{inspect(reason)}")
            :gen_tcp.close(socket)
        end

        accept_loop(kind, listen_socket, recv_timeout_ms)

      {:error, :closed} ->
        :ok

      {:error, reason} ->
        Logger.error("Bridge #{kind} accept loop stopped: #{inspect(reason)}")
        :ok
    end
  end

  defp extract_tcp_port(listen_socket) do
    {:ok, {_host, port}} = :inet.sockname(listen_socket)
    port
  end

  defp format_host({a, b, c, d}), do: "#{a}.#{b}.#{c}.#{d}"
end
