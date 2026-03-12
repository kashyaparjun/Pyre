defmodule PyreBridge.AgentSupervisor do
  @moduledoc """
  Root supervisor for Phase 3 agent groups and agent processes.
  """

  use Supervisor

  alias PyreBridge.AgentGroupSupervisor
  alias PyreBridge.AgentServer

  @spec start_link(keyword()) :: Supervisor.on_start()
  def start_link(opts) do
    Supervisor.start_link(__MODULE__, opts, name: __MODULE__)
  end

  @spec create_group(String.t(), keyword()) :: Supervisor.on_start_child()
  def create_group(name, opts \\ []) when is_binary(name) do
    strategy = Keyword.get(opts, :strategy, :one_for_one)
    parent = Keyword.get(opts, :parent)
    max_restarts = Keyword.get(opts, :max_restarts, 3)
    max_seconds = Keyword.get(opts, :max_seconds, 5)

    child_spec = %{
      id: {AgentGroupSupervisor, name},
      start:
        {AgentGroupSupervisor, :start_link,
         [[
            name: name,
            strategy: strategy,
            max_restarts: max_restarts,
            max_seconds: max_seconds
          ]]},
      restart: :temporary,
      type: :supervisor
    }

    Supervisor.start_child(parent_supervisor(parent), child_spec)
  end

  @spec start_agent(keyword()) :: Supervisor.on_start_child()
  def start_agent(opts) do
    group = Keyword.get(opts, :group)

    child_spec = %{
      id: {AgentServer, Keyword.fetch!(opts, :name)},
      start: {AgentServer, :start_link, [opts]},
      restart: :permanent,
      type: :worker
    }

    Supervisor.start_child(parent_supervisor(group), child_spec)
  end

  @spec stop_agent(String.t()) :: :ok | {:error, :not_found}
  def stop_agent(name) when is_binary(name) do
    case Registry.lookup(PyreBridge.AgentRegistry, name) do
      [{pid, _value}] ->
        GenServer.stop(pid, :normal)
        :ok

      [] ->
        {:error, :not_found}
    end
  end

  @impl true
  def init(_opts) do
    Supervisor.init([], strategy: :one_for_one)
  end

  defp parent_supervisor(nil), do: __MODULE__

  defp parent_supervisor(name) do
    case Registry.lookup(PyreBridge.SupervisorRegistry, name) do
      [{pid, _value}] -> pid
      [] -> raise ArgumentError, "supervisor group '#{name}' not found"
    end
  end
end
