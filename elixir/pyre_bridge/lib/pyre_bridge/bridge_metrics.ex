defmodule PyreBridge.BridgeMetrics do
  @moduledoc """
  Lightweight bridge metrics with lock-free hot-path counters and capped samples.
  """

  use GenServer

  @queue_table :pyre_bridge_queue_samples
  @restart_table :pyre_bridge_restart_samples
  @counters_key {__MODULE__, :counters}

  @idx_in_flight 1
  @idx_max_in_flight_observed 2
  @idx_backpressure_events 3
  @idx_sample_seq 4

  @sample_every 16
  @max_samples 512

  @spec start_link(keyword()) :: GenServer.on_start()
  def start_link(opts) do
    GenServer.start_link(__MODULE__, opts, name: __MODULE__)
  end

  @spec try_reserve_in_flight(non_neg_integer()) :: boolean()
  def try_reserve_in_flight(max_in_flight) when is_integer(max_in_flight) and max_in_flight >= 0 do
    case counters_ref() do
      nil ->
        true

      ref ->
        :counters.add(ref, @idx_in_flight, 1)
        current = :counters.get(ref, @idx_in_flight)

        if max_in_flight > 0 and current > max_in_flight do
          :counters.sub(ref, @idx_in_flight, 1)
          false
        else
          maybe_update_max(ref, current)
          maybe_sample_queue_depth(ref, current)
          true
        end
    end
  end

  @spec release_in_flight() :: :ok
  def release_in_flight do
    case counters_ref() do
      nil -> :ok
      ref ->
        :counters.sub(ref, @idx_in_flight, 1)
        :ok
    end
  end

  @spec current_in_flight() :: non_neg_integer()
  def current_in_flight do
    case counters_ref() do
      nil -> 0
      ref -> max(:counters.get(ref, @idx_in_flight), 0)
    end
  end

  @spec increment_backpressure() :: :ok
  def increment_backpressure do
    case counters_ref() do
      nil -> :ok
      ref ->
        :counters.add(ref, @idx_backpressure_events, 1)
        :ok
    end
  end

  @spec add_restart_latency(non_neg_integer()) :: :ok
  def add_restart_latency(ms) when is_integer(ms) and ms >= 0 do
    seq = System.unique_integer([:positive, :monotonic])
    :ets.insert(@restart_table, {seq, ms})
    prune_table(@restart_table, @max_samples)
    :ok
  end

  @spec snapshot() :: map()
  def snapshot do
    {in_flight, max_in_flight_observed, backpressure_events} =
      case counters_ref() do
        nil -> {0, 0, 0}
        ref ->
          {
            max(:counters.get(ref, @idx_in_flight), 0),
            max(:counters.get(ref, @idx_max_in_flight_observed), 0),
            max(:counters.get(ref, @idx_backpressure_events), 0)
          }
      end

    queue_samples =
      @queue_table
      |> :ets.tab2list()
      |> Enum.map(fn {_seq, value} -> value end)

    restart_samples =
      @restart_table
      |> :ets.tab2list()
      |> Enum.map(fn {_seq, value} -> value end)

    %{
      in_flight: in_flight,
      max_in_flight_observed: max_in_flight_observed,
      backpressure_events: backpressure_events,
      queue_depth_percentiles: percentiles(queue_samples),
      restart_latency_percentiles: percentiles(restart_samples)
    }
  end

  @impl true
  def init(_opts) do
    _ = :ets.new(@queue_table, [:named_table, :public, :ordered_set, read_concurrency: true, write_concurrency: true])
    _ = :ets.new(@restart_table, [:named_table, :public, :ordered_set, read_concurrency: true, write_concurrency: true])

    ref = :counters.new(4, [:write_concurrency])
    :counters.put(ref, @idx_in_flight, 0)
    :counters.put(ref, @idx_max_in_flight_observed, 0)
    :counters.put(ref, @idx_backpressure_events, 0)
    :counters.put(ref, @idx_sample_seq, 0)
    :persistent_term.put(@counters_key, ref)

    {:ok, %{counters_ref: ref}}
  end

  @impl true
  def terminate(_reason, state) do
    :persistent_term.erase(@counters_key)
    _ = state
    :ok
  end

  defp counters_ref do
    :persistent_term.get(@counters_key, nil)
  end

  defp maybe_update_max(ref, current) do
    observed = :counters.get(ref, @idx_max_in_flight_observed)
    if current > observed, do: :counters.put(ref, @idx_max_in_flight_observed, current)
    :ok
  end

  defp maybe_sample_queue_depth(ref, current) do
    :counters.add(ref, @idx_sample_seq, 1)
    seq = :counters.get(ref, @idx_sample_seq)

    if rem(seq, @sample_every) == 0 do
      :ets.insert(@queue_table, {seq, current})
      prune_table(@queue_table, @max_samples)
    end

    :ok
  end

  defp prune_table(table, max_samples) do
    if :ets.info(table, :size) > max_samples do
      case :ets.first(table) do
        :"$end_of_table" -> :ok
        oldest -> :ets.delete(table, oldest)
      end

      prune_table(table, max_samples)
    else
      :ok
    end
  end

  defp percentiles([]), do: %{p50: 0, p95: 0, p99: 0}

  defp percentiles(samples) do
    sorted = Enum.sort(samples)

    %{
      p50: at_percentile(sorted, 0.50),
      p95: at_percentile(sorted, 0.95),
      p99: at_percentile(sorted, 0.99)
    }
  end

  defp at_percentile(sorted, pct) do
    idx = round((length(sorted) - 1) * pct)
    Enum.at(sorted, idx, 0)
  end
end
