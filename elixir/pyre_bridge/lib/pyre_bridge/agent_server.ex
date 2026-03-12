defmodule PyreBridge.AgentServer do
  @moduledoc """
  Phase 2 stateful agent process.

  Holds opaque state and delegates message handling to a handler module.
  """

  use GenServer

  defstruct [:name, :handler_module, :state]

  @type server_state :: %__MODULE__{
          name: String.t(),
          handler_module: module(),
          state: term()
        }

  @spec start_link(keyword()) :: GenServer.on_start()
  def start_link(opts) do
    name = Keyword.fetch!(opts, :name)
    GenServer.start_link(__MODULE__, opts, name: via(name))
  end

  @spec via(String.t()) :: {:via, Registry, {module(), String.t()}}
  def via(name) do
    {:via, Registry, {PyreBridge.AgentRegistry, name}}
  end

  @spec call(String.t(), String.t(), map()) :: {:ok, term()} | {:error, term()}
  def call(name, type, payload) do
    try do
      GenServer.call(via(name), {:call, type, payload})
    catch
      :exit, {:noproc, _details} -> {:error, :noproc}
      :exit, {{:handler_error, reason}, _details} -> {:error, reason}
      :exit, {:handler_error, reason} -> {:error, reason}
    end
  end

  @spec cast(String.t(), String.t(), map()) :: :ok
  def cast(name, type, payload) do
    GenServer.cast(via(name), {:cast, type, payload})
  end

  @impl true
  def init(opts) do
    handler_module = Keyword.fetch!(opts, :handler_module)
    args = Keyword.get(opts, :args, %{})
    name = Keyword.fetch!(opts, :name)

    case handler_module.init(args) do
      {:ok, initial_state} ->
        {:ok, %__MODULE__{name: name, handler_module: handler_module, state: initial_state}}

      {:error, reason} ->
        {:stop, reason}
    end
  end

  @impl true
  def handle_call({:call, type, payload}, _from, %__MODULE__{} = state) do
    case state.handler_module.handle_call(state.state, type, payload) do
      {:ok, reply, new_state} ->
        {:reply, {:ok, reply}, %{state | state: new_state}}

      {:error, reason} ->
        {:stop, {:handler_error, reason}, {:error, reason}, state}
    end
  end

  @impl true
  def handle_cast({:cast, type, payload}, %__MODULE__{} = state) do
    case state.handler_module.handle_cast(state.state, type, payload) do
      {:ok, new_state} ->
        {:noreply, %{state | state: new_state}}

      {:error, reason} ->
        {:stop, {:handler_error, reason}, state}
    end
  end
end
