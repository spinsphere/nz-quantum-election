#!/usr/bin/env python3
"""
NZ Quantum Election: QAOA coalition optimiser for the 2026 MMP election
=======================================================================

Pipeline
--------
1.  Load the party scoring matrix and polling inputs (policy_data.json).
2.  Allocate seats with the Sainte-Laguë method (seat_model.py).
3.  Build the coalition objective
        maximise  sum_i w_i x_i  -  mu * sum_{i<j} d_ij x_i x_j
        subject to  sum_i s_i x_i >= majority
    where w_i is the party's aggregate policy-effectiveness weight, d_ij is the
    ideological distance between parties i and j (from the position axes) and
    x_i in {0,1} says whether party i is in the coalition.  Without the
    friction term the problem is degenerate: every party has positive value, so
    the grand coalition always wins.  The friction term is what makes this a
    genuine binary *quadratic* program.
4.  Encode the seat constraint with binary slack variables.  Seat counts are
    rescaled to the coarsest integer unit that reproduces the exact feasible
    set over all 2^7 coalitions (checked by brute force), which cuts both the
    number of slack qubits and the penalty dynamic range: this is the
    "scaled appropriately for NISQ hardware" step.
5.  Convert to a QUBO (penalty method) and then to an Ising Hamiltonian.
6.  Optimise QAOA angles with an exact Aer statevector simulation for a sweep
    of circuit depths p; sample the best circuit with qiskit_aer SamplerV2.
7.  Submit the same circuit to IBM Quantum hardware (least-busy Heron
    processor, job mode).  If the queue estimate exceeds 10 minutes, the job
    does not return within 10 minutes, or any connection error occurs, fall
    back to the local Aer sampler and record the reason.
8.  Verify against classical brute force and write quantum_results.json.

Credentials: the IBM token is read from the IBM_QUANTUM_TOKEN environment
variable or a local .env file (never committed).

Usage:  python quantum_nz_election.py [--no-hardware] [--mu 1.0] [--shots 8192]
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import os
import sys
import time
import warnings
from datetime import datetime, timezone

import numpy as np

warnings.filterwarnings("ignore")

from qiskit import QuantumCircuit
from qiskit.circuit.library import QAOAAnsatz
from qiskit.quantum_info import SparsePauliOp
from qiskit_aer import AerSimulator
from qiskit_aer.primitives import SamplerV2 as AerSampler
from qiskit_optimization import QuadraticProgram
from qiskit_optimization.converters import LinearEqualityToPenalty
from scipy.optimize import minimize

from seat_model import sainte_lague, majority_threshold

HERE = os.path.dirname(os.path.abspath(__file__))


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def load_env_token() -> str:
    tok = os.environ.get("IBM_QUANTUM_TOKEN", "").strip()
    if tok:
        return tok
    env_path = os.path.join(HERE, ".env")
    if os.path.exists(env_path):
        for line in open(env_path):
            line = line.strip()
            if line.startswith("IBM_QUANTUM_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def banner(title: str) -> None:
    print("\n" + "=" * 72)
    print(f"  {title}")
    print("=" * 72)


def diag_energies(op: SparsePauliOp) -> np.ndarray:
    """Exact diagonal of a Z-only Pauli operator over all 2^N basis states.
    Index k corresponds to the bitstring with qubit q = (k >> q) & 1."""
    nq = op.num_qubits
    idx = np.arange(2 ** nq)
    bits = (idx[:, None] >> np.arange(nq)) & 1
    energies = np.zeros(2 ** nq)
    for label, coef in zip(op.paulis, op.coeffs):
        z = np.asarray(label.z)
        if label.x.any():
            raise ValueError("Cost operator must be diagonal (Z-only)")
        energies += coef.real * ((-1.0) ** bits[:, z].sum(axis=1))
    return energies


def bits_of(index: int, nq: int) -> np.ndarray:
    return np.array([(index >> q) & 1 for q in range(nq)], dtype=int)


def bitstring_to_bits(bs: str, nq: int) -> np.ndarray:
    """Qiskit bitstrings are little-endian: rightmost char is qubit 0."""
    bs = bs.replace(" ", "").zfill(nq)
    return np.array([int(c) for c in reversed(bs)], dtype=int)


# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-hardware", action="store_true", help="skip the IBM Quantum hardware run")
    ap.add_argument("--mu", type=float, default=1.0, help="friction coefficient mu (default 1.0)")
    ap.add_argument("--shots", type=int, default=8192, help="local sampler shots")
    ap.add_argument("--hw-shots", type=int, default=4096, help="hardware shots")
    ap.add_argument("--max-p", type=int, default=4, help="largest QAOA depth in the sweep")
    ap.add_argument("--hw-p", type=int, default=2, help="QAOA depth submitted to hardware")
    ap.add_argument("--queue-limit", type=int, default=600, help="hardware queue/wait limit in seconds")
    ap.add_argument("--seed", type=int, default=2026)
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)
    t_start = time.time()

    # ------------------------------------------------------------------ 1
    banner("STEP 1  Load policy matrix and polling inputs")
    data = json.load(open(os.path.join(HERE, "policy_data.json")))
    meta = data["metadata"]
    domains = data["domains"]
    parties = list(data["parties"])
    n = len(parties)
    scores = np.array([[data["parties"][p]["scores"][d] for d in domains] for p in parties], dtype=float)
    positions = np.array([[data["parties"][p]["positions"][d] for d in domains] for p in parties], dtype=float)
    weights = scores.sum(axis=1) / (10.0 * len(domains))          # w_i in (0, 1]
    friction = np.array([[np.mean(np.abs(positions[i] - positions[j])) / 2.0
                          for j in range(n)] for i in range(n)])  # d_ij in [0, 1]
    MU = args.mu

    # ------------------------------------------------------------------ 2
    votes = {p: meta["polling_average"][p] for p in parties}
    electorates = {p: meta["electorate_assumptions"].get(p, 0) for p in parties}
    seats_d = sainte_lague(votes, electorates, meta.get("nominal_seats", 120), meta.get("threshold_pct", 5.0))
    seats = np.array([seats_d[p] for p in parties], dtype=int)
    TOTAL = int(seats.sum())
    MAJ = majority_threshold(TOTAL)

    print(f"Election: {meta['election_date']}   data as of {meta['data_as_of']}   friction mu = {MU}")
    print(f"\n{'Party':<14}{'Vote %':>7}{'Seats':>7}{'Score/80':>10}{'w_i':>8}")
    print("-" * 46)
    for i, p in enumerate(parties):
        print(f"{p:<14}{votes[p]:>7.1f}{seats[i]:>7}{scores[i].sum():>10.0f}{weights[i]:>8.3f}")
    print(f"{'House':<14}{'':>7}{TOTAL:>7}      majority = {MAJ} seats")
    print("\nPairwise ideological distance d_ij (0 = identical, 1 = opposite on every axis):")
    print("        " + "".join(f"{p[:6]:>8}" for p in parties))
    for i in range(n):
        print(f"{parties[i][:7]:<8}" + "".join(f"{friction[i, j]:>8.3f}" for j in range(n)))

    # ------------------------------------------------------------------ 3  classical ground truth
    banner("STEP 2  Classical brute force (ground truth, 2^7 = 128 coalitions)")

    def objective(x: np.ndarray, mu: float = MU) -> float:
        return float(weights @ x - mu * sum(friction[i, j] * x[i] * x[j]
                                            for i in range(n) for j in range(i + 1, n)))

    all_x = np.array(list(itertools.product([0, 1], repeat=n)), dtype=int)
    feasible_mask = all_x @ seats >= MAJ
    ranked = sorted(
        [(objective(x), int(x @ seats), tuple(int(b) for b in x)) for x in all_x[feasible_mask]],
        key=lambda r: -r[0])
    opt_val, opt_seats, opt_bits = ranked[0]
    opt_parties = [parties[i] for i in range(n) if opt_bits[i]]
    print(f"Feasible coalitions: {int(feasible_mask.sum())} of {len(all_x)}")
    print(f"\n{'rank':<5}{'objective':>10}{'seats':>7}  coalition")
    for r, (val, s, b) in enumerate(ranked[:10], 1):
        print(f"{r:<5}{val:>10.4f}{s:>7}  {' + '.join(parties[i] for i in range(n) if b[i])}")

    # sensitivity to mu and the degenerate linear case
    sensitivity = []
    for mu in [0.0, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0]:
        best = max(((objective(x, mu), x) for x in all_x[feasible_mask]), key=lambda t: t[0])
        sensitivity.append({"mu": mu, "objective": round(best[0], 4),
                            "coalition": [parties[i] for i in range(n) if best[1][i]],
                            "seats": int(best[1] @ seats)})
    print("\nSensitivity of the optimum to the friction coefficient mu:")
    for row in sensitivity:
        print(f"  mu={row['mu']:<5} -> {' + '.join(row['coalition']):<45} seats={row['seats']}  obj={row['objective']}")

    # smallest winning coalitions and bloc totals for context
    blocs = {}
    for p in parties:
        blocs.setdefault(data["parties"][p]["bloc"], []).append(p)
    bloc_seats = {b: int(sum(seats_d[p] for p in ps)) for b, ps in blocs.items()}
    print(f"\nBloc seat totals: {bloc_seats}  (majority {MAJ})")

    # ------------------------------------------------------------------ 4  constraint scaling
    banner("STEP 3  Seat-constraint scaling for NISQ (slack-variable encoding)")
    best_scaling = None
    for q in range(1, 13):
        for rounding in ("round", "floor", "ceil"):
            s_scaled = getattr(np, rounding)(seats / q).astype(int)
            for m_scaled in range(max(1, math.floor(MAJ / q) - 1), math.ceil(MAJ / q) + 2):
                if np.array_equal(all_x @ s_scaled >= m_scaled, feasible_mask):
                    surplus_max = int(s_scaled.sum() - m_scaled)
                    slack_bits = max(1, math.ceil(math.log2(surplus_max + 1)))
                    cand = (slack_bits, -q, q, rounding, m_scaled, tuple(int(v) for v in s_scaled), surplus_max)
                    if best_scaling is None or cand < best_scaling:
                        best_scaling = cand
    slack_bits, _, q_unit, rounding, M_SCALED, S_SCALED, surplus_max = best_scaling
    S_SCALED = np.array(S_SCALED, dtype=int)
    N_QUBITS = n + slack_bits
    print(f"Exact seats {tuple(int(s) for s in seats)}, majority {MAJ}")
    print(f"Chosen unit: 1 unit = {q_unit} seats ({rounding}); scaled seats {tuple(S_SCALED)}, scaled majority {M_SCALED}")
    print(f"Feasible set identical for all 128 coalitions: True   max surplus {surplus_max} units -> {slack_bits} slack qubits")
    print(f"Qubits: {n} party + {slack_bits} slack = {N_QUBITS}")

    # ------------------------------------------------------------------ 5  QUBO -> Ising
    banner("STEP 4  Quadratic program -> QUBO (penalty) -> Ising Hamiltonian")
    qp = QuadraticProgram(name="nz_coalition")
    for p in parties:
        qp.binary_var(p)
    slack_names = [f"slack_{k}" for k in range(slack_bits)]
    for s in slack_names:
        qp.binary_var(s)
    # minimise the negative objective
    qp.minimize(linear={parties[i]: -float(weights[i]) for i in range(n)},
                quadratic={(parties[i], parties[j]): float(MU * friction[i, j])
                           for i in range(n) for j in range(i + 1, n)})
    cons = {parties[i]: int(S_SCALED[i]) for i in range(n)}
    cons.update({slack_names[k]: -(2 ** k) for k in range(slack_bits)})
    qp.linear_constraint(linear=cons, sense="==", rhs=int(M_SCALED), name="majority")
    print(qp.export_as_lp_string())

    # all 2^N basis states, decoded once
    all_idx = np.arange(2 ** N_QUBITS)
    all_bits = (all_idx[:, None] >> np.arange(N_QUBITS)) & 1
    X_all = all_bits[:, :n]
    Y_all = all_bits[:, n:] @ (2 ** np.arange(slack_bits))
    scaled_total = X_all @ S_SCALED
    exact_feasible_state = (scaled_total >= M_SCALED) & (Y_all == scaled_total - M_SCALED)
    coalition_feasible_state = X_all @ seats >= MAJ
    is_opt_state = exact_feasible_state & np.all(X_all == np.array(opt_bits), axis=1)
    opt_index = int(np.flatnonzero(is_opt_state)[0])

    # choose the smallest penalty whose ground state is the constrained optimum
    penalty = None
    for lam in [0.3, 0.5, 0.7, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0]:
        qubo = LinearEqualityToPenalty(penalty=lam).convert(qp)
        op, offset = qubo.to_ising()
        energies = diag_energies(op)
        if int(np.argmin(energies)) == opt_index:
            penalty = lam
            break
    if penalty is None:
        raise RuntimeError("no penalty in scan made the ground state the constrained optimum")
    penalty = round(penalty * 1.4, 3)  # safety margin
    qubo = LinearEqualityToPenalty(penalty=penalty).convert(qp)
    cost_op, ising_offset = qubo.to_ising()
    energies_raw = diag_energies(cost_op)
    assert int(np.argmin(energies_raw)) == opt_index, "ground state check failed"
    scale = float(np.abs(cost_op.coeffs).max())
    cost_op_n = cost_op / scale
    energies = energies_raw / scale
    print(f"Penalty weight lambda = {penalty}  (smallest scan value with correct ground state, x1.4)")
    print(f"Ising Hamiltonian: {cost_op.num_qubits} qubits, {len(cost_op)} Pauli terms, offset {ising_offset:.3f}")
    print(f"Normalised by max |coefficient| = {scale:.3f}; ground state == constrained optimum: True")
    spectral_gap = float(np.sort(energies)[1] - energies.min())
    print(f"Normalised spectral gap above ground state: {spectral_gap:.5f}")

    # ------------------------------------------------------------------ 6  QAOA optimisation (Aer statevector)
    banner("STEP 5  QAOA angle optimisation on Aer statevector simulator")
    sim = AerSimulator(method="statevector", seed_simulator=args.seed)

    def make_ansatz(reps: int) -> QuantumCircuit:
        ans = QAOAAnsatz(cost_operator=cost_op_n, reps=reps, name=f"qaoa_p{reps}")
        return ans

    def statevector_probs(ansatz: QuantumCircuit, theta: np.ndarray) -> np.ndarray:
        qc = ansatz.assign_parameters(theta)
        qc = qc.decompose(reps=3)
        qc.save_statevector()
        res = sim.run(qc).result()
        psi = np.asarray(res.get_statevector())
        return np.abs(psi) ** 2

    sweep = []
    prev_theta = None
    for reps in range(1, args.max_p + 1):
        ansatz = make_ansatz(reps)
        # ansatz parameter order: betas (mixer) first, then gammas (cost)
        n_eval = [0]

        def cost_fn(theta: np.ndarray) -> float:
            n_eval[0] += 1
            return float(statevector_probs(ansatz, theta) @ energies)

        starts = []
        if prev_theta is not None and reps > 1:        # INTERP initialisation from depth p-1
            pb, pg = prev_theta[:reps - 1], prev_theta[reps - 1:]
            grid_old, grid_new = np.linspace(0, 1, reps - 1), np.linspace(0, 1, reps)
            starts.append(np.concatenate([np.interp(grid_new, grid_old, pb), np.interp(grid_new, grid_old, pg)]))
        for dt in (0.5, 1.0, 1.5):                      # linear-ramp (TQA-style) initialisations
            starts.append(np.array([dt * (1 - (k + 0.5) / reps) for k in range(reps)] +
                                   [dt * (k + 0.5) / reps for k in range(reps)]))
        t0 = time.time()
        best_res = None
        for x0 in starts:
            res = minimize(cost_fn, x0, method="COBYLA", options={"maxiter": 600, "rhobeg": 0.3, "tol": 1e-6})
            if best_res is None or res.fun < best_res.fun:
                best_res = res
        prev_theta = best_res.x
        probs = statevector_probs(ansatz, best_res.x)
        p_opt = float(probs[opt_index])
        p_feasible_exact = float(probs[exact_feasible_state].sum())
        p_majority = float(probs[coalition_feasible_state].sum())
        rank = int((probs > p_opt).sum()) + 1
        # approximation ratio on the feasible (exact) manifold
        row = {
            "p": reps, "energy": round(float(best_res.fun), 6), "evaluations": int(n_eval[0]),
            "seconds": round(time.time() - t0, 1),
            "betas": [round(float(v), 6) for v in best_res.x[:reps]],
            "gammas": [round(float(v), 6) for v in best_res.x[reps:]],
            "prob_optimum": round(p_opt, 6), "prob_optimum_over_uniform": round(p_opt * 2 ** N_QUBITS, 2),
            "rank_of_optimum": rank, "prob_exact_feasible": round(p_feasible_exact, 4),
            "prob_majority_coalition": round(p_majority, 4),
        }
        sweep.append(row)
        print(f"p={reps}: <H>={row['energy']:.4f}  P(optimum)={p_opt:.4f} ({row['prob_optimum_over_uniform']}x uniform)  "
              f"rank={rank}  P(exact feasible)={p_feasible_exact:.3f}  P(seats>=maj)={p_majority:.3f}  "
              f"[{row['evaluations']} evals, {row['seconds']}s]")

    best_row = max(sweep, key=lambda r: r["prob_optimum"])
    P_BEST = best_row["p"]
    theta_best = np.array(best_row["betas"] + best_row["gammas"])
    print(f"\nBest depth by P(optimum): p = {P_BEST}")

    # ------------------------------------------------------------------ 7  local sampling (Aer SamplerV2)
    banner("STEP 6  Sample the optimised circuit with qiskit_aer SamplerV2")

    def decode_counts(counts: dict[str, int]) -> dict:
        total = sum(counts.values())
        coalition_hist: dict[tuple, int] = {}
        best_feas = None
        n_opt_exact = 0
        n_majority = 0
        for bs, c in counts.items():
            bits = bitstring_to_bits(bs, N_QUBITS)
            x = bits[:n]
            key = tuple(int(b) for b in x)
            coalition_hist[key] = coalition_hist.get(key, 0) + c
            if int(x @ seats) >= MAJ:
                n_majority += c
                val = objective(x)
                if best_feas is None or val > best_feas[0]:
                    best_feas = (val, key, int(x @ seats))
            idx = int(sum(int(b) << q for q, b in enumerate(bits)))
            if idx == opt_index:
                n_opt_exact += c
        top = sorted(coalition_hist.items(), key=lambda kv: -kv[1])[:10]
        return {
            "shots": total,
            "unique_bitstrings": len(counts),
            "prob_optimum_exact_bitstring": round(n_opt_exact / total, 5),
            "prob_majority_coalition": round(n_majority / total, 4),
            "prob_optimal_coalition_any_slack": round(coalition_hist.get(tuple(opt_bits), 0) / total, 4),
            "best_feasible_sample": None if best_feas is None else {
                "objective": round(best_feas[0], 4),
                "bitstring_party_order": "".join(str(b) for b in best_feas[1]),
                "coalition": [parties[i] for i in range(n) if best_feas[1][i]],
                "seats": best_feas[2],
                "matches_classical_optimum": best_feas[1] == tuple(opt_bits),
            },
            "top_coalitions": [{
                "bitstring_party_order": "".join(str(b) for b in k), "count": c, "probability": round(c / total, 4),
                "coalition": [parties[i] for i in range(n) if k[i]], "seats": int(np.array(k) @ seats),
                "feasible": bool(np.array(k) @ seats >= MAJ), "objective": round(objective(np.array(k)), 4)}
                for k, c in top],
        }

    ansatz_best = make_ansatz(P_BEST)
    circ_local = ansatz_best.assign_parameters(theta_best).decompose(reps=3)
    circ_local.measure_all()
    sampler = AerSampler(seed=args.seed)
    job = sampler.run([circ_local], shots=args.shots)
    counts_local = job.result()[0].data.meas.get_counts()
    local = decode_counts(counts_local)
    local["backend"] = "qiskit_aer SamplerV2 (statevector)"
    local["qaoa_p"] = P_BEST
    print(f"Shots {local['shots']}, unique bitstrings {local['unique_bitstrings']}")
    print(f"P(exact optimum bitstring) = {local['prob_optimum_exact_bitstring']}   "
          f"P(optimal coalition, any slack) = {local['prob_optimal_coalition_any_slack']}   "
          f"P(majority coalition) = {local['prob_majority_coalition']}")
    bf = local["best_feasible_sample"]
    print(f"Best feasible sample: {' + '.join(bf['coalition'])}  seats={bf['seats']}  objective={bf['objective']}  "
          f"== classical optimum: {bf['matches_classical_optimum']}")

    # ------------------------------------------------------------------ 8  IBM Quantum hardware
    banner("STEP 7  IBM Quantum hardware execution (job mode) with 10-minute fallback")
    hardware = {"attempted": not args.no_hardware, "executed": False}
    if args.no_hardware:
        hardware["reason"] = "disabled with --no-hardware"
        print("Skipped (--no-hardware).")
    else:
        token = load_env_token()
        if not token:
            hardware["reason"] = "IBM_QUANTUM_TOKEN not set"
            print("No IBM_QUANTUM_TOKEN found; falling back to the local simulator result.")
        else:
            try:
                from qiskit_ibm_runtime import QiskitRuntimeService, SamplerV2 as RuntimeSampler
                from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager

                t0 = time.time()
                service = QiskitRuntimeService(channel="ibm_quantum_platform", token=token)
                backends = [b for b in service.backends(simulator=False, operational=True)
                            if b.num_qubits >= N_QUBITS]
                if not backends:
                    raise RuntimeError("no operational backend with enough qubits")
                statuses = {b.name: b.status().pending_jobs for b in backends}
                backend = min(backends, key=lambda b: statuses[b.name])
                pending = statuses[backend.name]
                est_wait = pending * 60  # conservative: one minute per queued job
                hardware.update({"backend": backend.name, "backend_qubits": backend.num_qubits,
                                 "pending_jobs_at_submit": pending, "queue_estimate_seconds": est_wait,
                                 "all_backends_pending": statuses,
                                 "connect_seconds": round(time.time() - t0, 1)})
                print(f"Connected in {hardware['connect_seconds']}s. Backends and queue: {statuses}")
                print(f"Selected {backend.name} ({backend.num_qubits} qubits), {pending} pending jobs")
                if est_wait > args.queue_limit:
                    raise TimeoutError(f"queue estimate {est_wait}s exceeds limit {args.queue_limit}s")

                P_HW = min(args.hw_p, P_BEST)
                row_hw = next(r for r in sweep if r["p"] == P_HW)
                theta_hw = np.array(row_hw["betas"] + row_hw["gammas"])
                circ_hw = make_ansatz(P_HW).assign_parameters(theta_hw).decompose(reps=3)
                circ_hw.measure_all()
                pm = generate_preset_pass_manager(optimization_level=3, backend=backend, seed_transpiler=args.seed)
                isa = pm.run(circ_hw)
                ops = isa.count_ops()
                two_q = int(sum(v for k, v in ops.items() if k in ("cz", "ecr", "cx", "rzz")))
                hardware.update({"qaoa_p": P_HW, "isa_depth": isa.depth(), "isa_two_qubit_gates": two_q,
                                 "isa_ops": {k: int(v) for k, v in ops.items()},
                                 "isa_two_qubit_depth": isa.depth(lambda inst: inst.operation.num_qubits == 2)})
                print(f"Transpiled p={P_HW} circuit: depth {isa.depth()}, 2q gates {two_q}, 2q depth "
                      f"{hardware['isa_two_qubit_depth']}, ops {dict(ops)}")

                rs = RuntimeSampler(mode=backend)
                rs.options.default_shots = args.hw_shots
                rs.options.dynamical_decoupling.enable = True
                rs.options.dynamical_decoupling.sequence_type = "XY4"
                rs.options.twirling.enable_gates = True
                rs.options.twirling.num_randomizations = "auto"
                t_sub = time.time()
                hw_job = rs.run([isa])
                hardware["job_id"] = hw_job.job_id()
                print(f"Submitted job {hw_job.job_id()}; waiting up to {args.queue_limit}s ...")
                result = hw_job.result(timeout=args.queue_limit)
                hardware["wall_seconds"] = round(time.time() - t_sub, 1)
                counts_hw = result[0].data.meas.get_counts()
                try:
                    usage = hw_job.usage()
                    hardware["qpu_usage_seconds"] = float(usage) if usage is not None else None
                except Exception:
                    pass
                try:
                    hardware["job_metrics_usage"] = hw_job.metrics().get("usage")
                except Exception:
                    pass
                hw = decode_counts(counts_hw)
                # distance between hardware and ideal coalition distributions (total variation)
                ideal_probs = statevector_probs(make_ansatz(P_HW), theta_hw)
                ideal_coal = {}
                for k in range(2 ** N_QUBITS):
                    key = tuple(int(b) for b in all_bits[k, :n])
                    ideal_coal[key] = ideal_coal.get(key, 0.0) + ideal_probs[k]
                hw_coal = {}
                for bs, c in counts_hw.items():
                    key = tuple(int(b) for b in bitstring_to_bits(bs, N_QUBITS)[:n])
                    hw_coal[key] = hw_coal.get(key, 0) + c / hw["shots"]
                tvd = 0.5 * sum(abs(ideal_coal.get(k, 0) - hw_coal.get(k, 0)) for k in set(ideal_coal) | set(hw_coal))
                hw["tvd_vs_ideal_coalition_marginal"] = round(float(tvd), 4)
                hw["ideal_prob_optimum_exact_bitstring_at_this_p"] = round(float(ideal_probs[opt_index]), 5)
                hw["ideal_prob_majority_coalition_at_this_p"] = round(float(ideal_probs[coalition_feasible_state].sum()), 4)
                hardware.update(hw)
                hardware["executed"] = True
                hardware["backend_label"] = f"IBM Quantum {backend.name}"
                print(f"Hardware result in {hardware['wall_seconds']}s: shots {hw['shots']}, unique {hw['unique_bitstrings']}")
                print(f"P(exact optimum) hw={hw['prob_optimum_exact_bitstring']} vs ideal={hw['ideal_prob_optimum_exact_bitstring_at_this_p']}; "
                      f"P(majority) hw={hw['prob_majority_coalition']} vs ideal={hw['ideal_prob_majority_coalition_at_this_p']}; "
                      f"TVD(coalition marginal)={tvd:.3f}")
                bfh = hw["best_feasible_sample"]
                if bfh:
                    print(f"Hardware best feasible sample: {' + '.join(bfh['coalition'])} seats={bfh['seats']} "
                          f"objective={bfh['objective']} == classical optimum: {bfh['matches_classical_optimum']}")
            except Exception as exc:  # noqa: BLE001  (any failure -> documented fallback)
                hardware["reason"] = f"{type(exc).__name__}: {exc}"
                print(f"Hardware step failed or exceeded limit -> falling back to local Aer sampler. Reason: {hardware['reason']}")

    # ------------------------------------------------------------------ 9  results
    banner("STEP 8  Results")
    primary_source = "ibm_hardware" if hardware.get("executed") and hardware.get("best_feasible_sample") else "aer_simulator"
    primary = hardware["best_feasible_sample"] if primary_source == "ibm_hardware" else local["best_feasible_sample"]
    results = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "election_date": meta["election_date"],
        "data_as_of": meta["data_as_of"],
        "house": {"total_seats": TOTAL, "majority_threshold": MAJ, "seats": {p: int(seats_d[p]) for p in parties},
                  "polling_average_pct": votes, "electorate_assumptions": electorates, "bloc_seats": bloc_seats},
        "model": {
            "objective": "maximise sum_i w_i x_i - mu * sum_{i<j} d_ij x_i x_j  s.t.  sum_i s_i x_i >= majority",
            "mu": MU,
            "weights_w": {p: round(float(weights[i]), 4) for i, p in enumerate(parties)},
            "aggregate_scores": {p: float(scores[i].sum()) for i, p in enumerate(parties)},
            "domain_scores": {p: data["parties"][p]["scores"] for p in parties},
            "positions": {p: data["parties"][p]["positions"] for p in parties},
            "friction_matrix": {parties[i]: {parties[j]: round(float(friction[i, j]), 4) for j in range(n)} for i in range(n)},
        },
        "classical": {
            "optimum": {"objective": round(opt_val, 4), "seats": opt_seats, "coalition": opt_parties,
                        "bitstring_party_order": "".join(str(b) for b in opt_bits)},
            "top10": [{"objective": round(v, 4), "seats": s, "coalition": [parties[i] for i in range(n) if b[i]]}
                      for v, s, b in ranked[:10]],
            "sensitivity_to_mu": sensitivity,
            "feasible_coalitions": int(feasible_mask.sum()),
        },
        "encoding": {
            "party_order": parties, "seat_unit": q_unit, "rounding": rounding,
            "scaled_seats": [int(v) for v in S_SCALED], "scaled_majority": int(M_SCALED),
            "slack_bits": slack_bits, "num_qubits": N_QUBITS, "penalty_lambda": penalty,
            "ising_pauli_terms": len(cost_op), "ising_offset": round(float(ising_offset), 4),
            "normalisation_scale": round(scale, 4), "normalised_spectral_gap": round(spectral_gap, 6),
            "qubo_variables": [v.name for v in qubo.variables],
        },
        "qaoa": {"optimizer": "COBYLA (SciPy), 3 linear-ramp starts + INTERP from p-1, maxiter 600 each",
                 "simulator": "qiskit_aer AerSimulator statevector (exact expectation)",
                 "depth_sweep": sweep, "selected_p": P_BEST},
        "aer_sampling": local,
        "ibm_hardware": hardware,
        "qaoa_result": {
            "source": primary_source,
            "optimal_bitstring_party_order": primary["bitstring_party_order"],
            "coalition_parties": primary["coalition"],
            "total_seats": primary["seats"],
            "majority_achieved": primary["seats"] >= MAJ,
            "objective_score": primary["objective"],
            "matches_classical_optimum": primary["matches_classical_optimum"],
        },
        "runtime_seconds": round(time.time() - t_start, 1),
        "versions": {},
    }
    try:
        import qiskit, qiskit_aer, qiskit_optimization
        results["versions"] = {"qiskit": qiskit.__version__, "qiskit_aer": qiskit_aer.__version__,
                               "qiskit_optimization": qiskit_optimization.__version__, "python": sys.version.split()[0]}
        import qiskit_ibm_runtime
        results["versions"]["qiskit_ibm_runtime"] = qiskit_ibm_runtime.__version__
    except Exception:
        pass

    out = os.path.join(HERE, "quantum_results.json")
    with open(out, "w") as fh:
        json.dump(results, fh, indent=2)

    qr = results["qaoa_result"]
    print(f"Result source:        {qr['source']}")
    print(f"Optimal bitstring:    {qr['optimal_bitstring_party_order']}   (party order {parties})")
    print(f"Winning coalition:    {' + '.join(qr['coalition_parties'])}")
    print(f"Total seats:          {qr['total_seats']} / {TOTAL}   majority {MAJ}: {'yes' if qr['majority_achieved'] else 'NO'}")
    print(f"Objective score:      {qr['objective_score']}   (classical optimum {opt_val:.4f}, match: {qr['matches_classical_optimum']})")
    print(f"Qubits / QAOA depth:  {N_QUBITS} / p={P_BEST} (hardware p={hardware.get('qaoa_p', '-')})")
    print(f"Hardware executed:    {hardware.get('executed')}  {hardware.get('backend', '')} {hardware.get('reason', '')}")
    print(f"Saved -> {out}   ({results['runtime_seconds']}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
