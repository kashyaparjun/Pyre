defmodule PyreBridge.WorkflowHandler do
  @moduledoc """
  Built-in coordinator/worker handler used by cross-runtime workflow tests.
  """

  @behaviour PyreBridge.AgentHandler

  alias PyreBridge.AgentServer

  @impl true
  def init(args) do
    case normalize_role(Map.get(args, :role, "worker")) do
      :coordinator ->
        {:ok, %{role: :coordinator, workers: [], rounds: 0, last_results: [], total_units: 0}}

      :worker ->
        worker_id = Map.get(args, :worker_id, "worker")
        {:ok, %{role: :worker, worker_id: worker_id, completed_tasks: [], total_units: 0}}
    end
  end

  @impl true
  def handle_call(%{role: :coordinator} = state, "register_workers", payload) do
    worker_ids =
      case Map.get(payload, "worker_ids", []) do
        ids when is_list(ids) -> Enum.filter(ids, &is_binary/1)
        _other -> []
      end

    next_state = %{state | workers: worker_ids}
    {:ok, %{workers: worker_ids}, next_state}
  end

  def handle_call(%{role: :coordinator} = state, "dispatch_batch", payload) do
    with {:ok, assignments} <- normalize_assignments(payload),
         {:ok, results} <- dispatch_assignments(assignments) do
      total_units = Enum.reduce(results, state.total_units, &(&1["units"] + &2))

      next_state = %{
        state
        | rounds: state.rounds + 1,
          last_results: results,
          total_units: total_units
      }

      reply = %{
        "round" => next_state.rounds,
        "results" => results,
        "worker_count" => length(next_state.workers)
      }

      {:ok, reply, next_state}
    end
  end

  def handle_call(%{role: :coordinator} = state, "get_status", _payload) do
    {:ok, coordinator_status(state), state}
  end

  def handle_call(%{role: :worker} = state, "run_task", payload) do
    task_id = Map.get(payload, "task_id", "task")
    units = Map.get(payload, "units", 1)
    sequence = length(state.completed_tasks) + 1

    result = %{
      "worker_id" => state.worker_id,
      "task_id" => task_id,
      "units" => units,
      "sequence" => sequence
    }

    next_state = %{
      state
      | completed_tasks: state.completed_tasks ++ [result],
        total_units: state.total_units + units
    }

    {:ok, result, next_state}
  end

  def handle_call(%{role: :worker} = state, "get_status", _payload) do
    {:ok, worker_status(state), state}
  end

  def handle_call(%{role: :worker}, "boom", _payload) do
    {:error, :boom}
  end

  def handle_call(_state, _type, _payload) do
    {:error, :unknown_call}
  end

  @impl true
  def handle_cast(state, _type, _payload) do
    {:ok, state}
  end

  defp normalize_role(role) when role in [:coordinator, "coordinator"], do: :coordinator
  defp normalize_role(_role), do: :worker

  defp normalize_assignments(payload) do
    case Map.get(payload, "assignments", []) do
      assignments when is_list(assignments) ->
        normalized =
          Enum.map(assignments, fn assignment ->
            %{
              "worker_id" => Map.get(assignment, "worker_id"),
              "task_id" => Map.get(assignment, "task_id", "task"),
              "units" => Map.get(assignment, "units", 1)
            }
          end)

        {:ok, normalized}

      _other ->
        {:error, :invalid_assignments}
    end
  end

  defp dispatch_assignments(assignments) do
    Enum.reduce_while(assignments, {:ok, []}, fn assignment, {:ok, results} ->
      worker_id = assignment["worker_id"]
      task_payload = Map.take(assignment, ["task_id", "units"])

      case AgentServer.call(worker_id, "run_task", task_payload) do
        {:ok, result} when is_map(result) ->
          {:cont, {:ok, results ++ [result]}}

        {:error, reason} ->
          {:halt, {:error, reason}}
      end
    end)
  end

  defp coordinator_status(state) do
    %{
      "role" => "coordinator",
      "workers" => state.workers,
      "rounds" => state.rounds,
      "last_results" => state.last_results,
      "total_units" => state.total_units
    }
  end

  defp worker_status(state) do
    %{
      "role" => "worker",
      "worker_id" => state.worker_id,
      "completed_tasks" => state.completed_tasks,
      "total_units" => state.total_units
    }
  end
end
