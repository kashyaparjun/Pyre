defmodule PyreBridge.Application do
  @moduledoc false
  use Application

  @impl true
  def start(_type, _args) do
    connection_worker_limit = Application.get_env(:pyre_bridge, :connection_worker_limit, 256)
    execution_worker_limit = Application.get_env(:pyre_bridge, :execution_worker_limit, 256)

    children = [
      {Registry, keys: :unique, name: PyreBridge.AgentRegistry},
      {Registry, keys: :unique, name: PyreBridge.SupervisorRegistry},
      {Task.Supervisor,
       name: PyreBridge.BridgeConnectionSupervisor,
       max_children: connection_worker_limit},
      {Task.Supervisor,
       name: PyreBridge.BridgeExecutionSupervisor,
       max_children: execution_worker_limit},
      {PyreBridge.BridgeMetrics, []},
      {PyreBridge.AgentSupervisor, []},
      {PyreBridge.BridgeServer, []}
    ]

    Supervisor.start_link(children, strategy: :one_for_one, name: PyreBridge.Supervisor)
  end
end
