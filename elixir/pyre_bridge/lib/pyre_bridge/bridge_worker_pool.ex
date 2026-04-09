defmodule PyreBridge.BridgeWorkerPool do
  @moduledoc """
  Pool of worker processes for handling bridge requests without spawning new tasks.
  This eliminates Task.Supervisor.start_child overhead for high-throughput scenarios.
  """

  use GenServer

  @pool_size 16

  def start_link(opts) do
    GenServer.start_link(__MODULE__, opts, name: __MODULE__)
  end

  @impl true
  def init(_opts) do
    # Start a pool of worker processes
    workers =
      for i <- 1..@pool_size do
        {:ok, pid} = GenServer.start_link(__MODULE__.Worker, [])
        pid
      end

    {:ok, %{workers: workers, next_idx: 0}}
  end

  @spec execute_request((-> term())) :: term()
  def execute_request(fun) when is_function(fun, 0) do
    GenServer.call(__MODULE__, {:execute, fun})
  end

  @impl true
  def handle_call({:execute, fun}, _from, state) do
    # Get next worker using round-robin
    idx = rem(state.next_idx, length(state.workers))
    worker = Enum.at(state.workers, idx)

    # Execute on the worker
    result = GenServer.call(worker, {:run, fun}, :infinity)

    {:reply, result, %{state | next_idx: state.next_idx + 1}}
  end

  defmodule Worker do
    @moduledoc "Worker process that executes functions synchronously"
    use GenServer

    def init(_) do
      {:ok, nil}
    end

    def handle_call({:run, fun}, _from, state) do
      result = fun.()
      {:reply, result, state}
    end
  end
end
