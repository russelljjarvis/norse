import numpy as np
import time
import sys
from subprocess import run, STDOUT
from multiprocessing.shared_memory import ShareableList
from multiprocessing.managers import SharedMemoryManager

# pytype: disable=import-error
from pygenn.genn_model import GeNNModel
from pygenn.genn_wrapper import NO_DELAY

# pytype: enable=import-error

from benchmark import BenchmarkParameters


def lif_feed_forward_benchmark(parameters: BenchmarkParameters):
    shared = SharedMemoryManager()
    shared.start()
    params = list(parameters._asdict().values())
    shared_list = shared.ShareableList(params)

    run(["python3", __file__, shared_list.shm.name], stderr=STDOUT)
    duration = shared_list[0]
    shared_list.shm.close()
    shared.shutdown()
    return duration


if __name__ == "__main__":
    # Assume we're running the genn benchmark and draw configs from the shared memory
    parameter_list = ShareableList(sequence=None, name=sys.argv[1])
    parameters = BenchmarkParameters(*parameter_list)

    model = GeNNModel("float", "pygenn")
    model.dT = parameters.dt
    np.random.seed(0)

    layers = []
    for i in range(parameters.batch_size):
        # Note: weights, parameters and poisson rate are magic numbers that seem to generate reasonable spike activity
        weights = np.random.rand(parameters.features, parameters.features).flatten() * 8
        model.add_neuron_population(
            f"PoissonNew{i}",
            parameters.features,
            "PoissonNew",
            {"rate": 100},
            {"timeStepToSpike": 1},
        )
        # From https://neuralensemble.org/docs/PyNN/reference/neuronmodels.html#pyNN.standardmodels.cells.IF_curr_exp
        lif_params = {
            "C": 1.0,
            "TauM": 20.0,
            "Vrest": 0.0,
            "Vreset": 0.0,
            "Vthresh": 1.0,
            "Ioffset": 0.0,
            "TauRefrac": 0.1,
        }
        lif_vars = {"V": 0.0, "RefracTime": 0.0}
        layer = model.add_neuron_population(
            f"LIF{i}", parameters.features, "LIF", lif_params, lif_vars
        )
        layer.spike_recording_enabled = True
        
        layers.append(layer)
        # From https://github.com/genn-team/genn/blob/master/userproject/PoissonIzh_project/model/PoissonIzh.cc#L93
        model.add_synapse_population(
            f"PL{i}",
            "DENSE_INDIVIDUALG",
            NO_DELAY,
            f"PoissonNew{i}",
            f"LIF{i}",
            "StaticPulse",
            {},
            {"g": weights},
            {},
            {},
            "DeltaCurr",
            {},
            {},
        )

    model.build()
    model.load(num_recording_timesteps=parameters.sequence_length)

    # Run simulation
    start = time.time()
    for _ in range(parameters.sequence_length):
        model.step_time()

    # Not sure if this should be within or outside the timing section
    model.pull_recording_buffers_from_device()
    end = time.time()

    parameter_list[0] = end - start
    parameter_list[1] = sum(len(layer.spike_recording_data[0]) for layer in layers)
    parameter_list.shm.close()
