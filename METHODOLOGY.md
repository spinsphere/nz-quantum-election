# Methodology

This document explains every modelling choice in the project so that the result can be audited, criticised and re-run with different assumptions. Nothing here is hidden in code: all inputs live in `policy_data.json`, all sources in `research/`.

## 1. Research

Eight research passes were run on 6 October 2026, one for polling and one per party (National, Labour, Green, ACT, NZ First, Te Pāti Māori, TOP). Each pass was asked for stated 2026 policy, numbers and dates across the eight domains, with a URL for every claim, plus independent assessments (Treasury, Reserve Bank, OECD, Ministry of Justice, ERO, Waitangi Tribunal and so on). The outputs are the files in `research/`.

**Coverage was uneven in the first pass and was then patched.** The National file was complete from the start (~90 sources including Treasury's PREFU, ERO, Ministry of Justice projections and the boot-camp evaluation). The other six passes ran after the session's web-search quota was exhausted and could only fetch official pages and Wikipedia. On 6 October 2026 the project owner supplied the text of 28 primary pages, the full policy PDFs of TOP, the Greens and Te Pāti Māori were downloaded and converted, and a Playwright crawl (DuckDuckGo plus direct pages, raw text in `research/raw/`) added news coverage: the RNZ-Reid Research poll of 6 October, the Infometrics review of the Greens' tax plan, the Wikipedia seat-projection table, coalition rule-outs and more. Each research file ends with an 'Update 6 Oct 2026' section recording what changed, including a second crawl pass (67 pages: ACT's policy sub-pages, the Infometrics review of the Greens' costings, Westpac and Cotality assessments of TOP's land tax, Labour's positions on boot camps, Three Strikes and Te Aka Whai Ora, Māori-electorate polls, and the mutual Labour-NZ First rule-out). Where independent evidence is still missing, the rationale text in `policy_data.json` draws on published work known to the author (OECD tax reviews, the 2019 Tax Working Group, Productivity Commission, Ministry of Justice programme evaluations) and says so.

## 2. Scoring matrix

Each party gets an integer **1 to 10 effectiveness score** in each of eight domains. The question asked for every score:

> Based on independent evidence, how effectively would this party's stated 2026 policies, and its track record where it has governed, advance stability (fiscal and institutional), growth (productivity and output) and equality (distribution of outcomes) in this domain?

Rules applied:

- Credit for costed, deliverable, evidence-backed measures; debit for measures contradicted by evidence, uncosted or unfunded, or carrying material legal or institutional risk.
- Incumbents (National, ACT, NZ First) are judged partly on delivered outcomes. Opposition parties are judged on plans. This is an unavoidable asymmetry: a plan is never contradicted by its own outcome data. It probably flatters smaller opposition parties, TOP in particular, which has never had to deliver.
- Scores are not ideological. National's structured-literacy programme scores well because the evidence is strong. The Greens' rent cap scores badly because the evidence is strong the other way. ACT and NZ First score badly on the Te Tiriti domain because the criterion is honouring Treaty obligations as found by the Tribunal and courts, and their platforms are to wind those arrangements back; that is a consequence of the criterion the brief specified, not a judgement about the merits of their constitutional view.

The aggregate weight is `w_i = sum of domain scores / 80`, so `w_i` lies in (0, 1].

| Party | Health | Educ. | Crime | Housing | Economy | Employ. | Transport | Tiriti | **/80** |
|---|---|---|---|---|---|---|---|---|---|
| National | 6 | 7 | 5 | 5 | 6 | 4 | 5 | 3 | **41** |
| Labour | 7 | 5 | 4 | 5 | 6 | 6 | 5 | 6 | **44** |
| Green | 6 | 5 | 5 | 4 | 5 | 5 | 6 | 8 | **44** |
| ACT | 6 | 5 | 4 | 5 | 5 | 3 | 4 | 2 | **34** |
| NZ First | 4 | 3 | 4 | 3 | 3 | 3 | 4 | 2 | **26** |
| Te Pāti Māori | 6 | 5 | 4 | 4 | 4 | 4 | 4 | 8 | **39** |
| TOP | 7 | 6 | 7 | 8 | 6 | 6 | 7 | 6 | **53** |

Every cell has a one-paragraph rationale with the evidence relied on in `policy_data.json` under `score_rationale`.

## 3. Position axes and friction

Effectiveness scores cannot measure how well two parties would get along: National and Labour both score 6 on the economy with opposite tax policies. So each party is also placed on a **-1 to +1 position axis** per domain (for example economy: -1 = lower tax and smaller state, +1 = new redistributive taxes and a larger state; Tiriti: -1 = single legal standard, +1 = Tiriti-based partnership). The axes are defined in `policy_data.json → metadata.position_axes`. Positions describe where a policy sits; they are not value judgements.

Pairwise **friction** is the mean absolute position difference over the eight domains, divided by 2 so that it lies in [0, 1]:

    d_ij = mean_k |pos_ik - pos_jk| / 2

Resulting matrix (0 = identical, 1 = opposite on every axis):

|  | Nat | Lab | Grn | ACT | NZF | TPM | TOP |
|---|---|---|---|---|---|---|---|
| National | 0 | .41 | .66 | .19 | .12 | .64 | .46 |
| Labour | .41 | 0 | .24 | .61 | .37 | .23 | .09 |
| Green | .66 | .24 | 0 | .85 | .61 | .06 | .19 |
| ACT | .19 | .61 | .85 | 0 | .24 | .84 | .66 |
| NZ First | .12 | .37 | .61 | .24 | 0 | .60 | .42 |
| Te Pāti Māori | .64 | .23 | .06 | .84 | .60 | 0 | .22 |
| TOP | .46 | .09 | .19 | .66 | .42 | .22 | 0 |

## 4. Seats

Party-vote shares are the unweighted mean of the six most recent polls (RNZ-Reid Research 24 Sep-1 Oct, 1News-Verian 23-27 Sep, Post/Freshwater 4-11 Sep, Anacta 4-10 Sep, Taxpayers' Union-Curia 1-3 Sep, Roy Morgan 27 Jul-23 Aug 2026): National 28.5, Labour 28.0, Green 14.4, ACT 9.7, NZ First 9.8, Te Pāti Māori 1.8, TOP 6.4. The Herald-Motu poll of polls on 28 September had National 29.4, Labour 26.9, Green 12.1, NZ First 11.8, TOP 8.5, ACT 8.3, Te Pāti Māori 2.0. Seats are allocated with the Sainte-Laguë method in `seat_model.py` (120 nominal seats, 5% threshold or an electorate seat, overhang retained). Te Pāti Māori is assumed to win 4 Māori electorates (Hauraki-Waikato, Tāmaki Makaurau, Te Tai Hauāuru, Waiariki, the assumption used by every published projection now that the Te Tai Tokerau and Te Tai Tonga MPs have left the party), giving a 2-seat overhang and a 122-seat House with a 62-seat majority:

| National | Labour | Green | ACT | NZ First | Te Pāti Māori | TOP | House | Majority |
|---|---|---|---|---|---|---|---|---|
| 35 | 34 | 17 | 12 | 12 | 4 | 8 | 122 | 62 |

Right bloc (National, ACT, NZ First) 59; left bloc (Labour, Green, Te Pāti Māori) 55; TOP 8. Neither bloc has a majority without TOP, which is exactly the situation the September polls describe. The one published September projection with TOP under 5% (Curia, 1-3 Sep) gives National-ACT-NZ First 64 of 121; the report's threshold scenario quantifies this.

## 5. The optimisation problem

    maximise   sum_i w_i x_i  -  mu * sum_{i<j} d_ij x_i x_j
    subject to sum_i s_i x_i  >=  62
               x_i in {0, 1}

The brief asked for `maximise sum_i w_i x_i` subject to the seat constraint. On its own that problem is degenerate: every `w_i` is positive, so the optimum is always the grand coalition of all seven parties (score 3.475, 122 seats). The friction term is the correction. It charges a cost for every pair of partners proportional to their ideological distance, which is what actually limits coalition size under MMP, and it is what makes the program quadratic. The coefficient `mu = 1` is the symmetric calibration where value and friction are measured in the same unit: a pair at maximum distance (d = 1) cancels the value of one maximally scored party (w = 1). The result is reported for `mu` from 0 to 3; it is unchanged between 0.5 and 1.5.

## 6. Quantum encoding

**Slack variables.** The inequality is turned into an equality with binary slack `y_k`: `sum_i s_i x_i - sum_k 2^k y_k = majority`. With raw seat counts (35, 34, 17, 12, 12, 4, 8) the surplus can reach 60, needing 6 slack qubits, and the penalty term `lambda * (…)^2` has coefficients up to ~600 while objective coefficients are below 1. That dynamic range is why low-depth QAOA struggles on knapsack-type constraints.

**Scaling for NISQ.** The script searches for the coarsest integer seat unit `q` and rounding rule such that `round(s_i / q)` and a scaled majority reproduce the *exact* feasible set over all 128 coalitions. For the current polls that is `q = 6`: scaled seats (6, 6, 3, 2, 2, 1, 1), scaled majority 11, maximum surplus 10, so **4 slack qubits** and **11 qubits in total**, with the largest Hamiltonian coefficient falling from ~600 to ~27. The equivalence is asserted in code, not assumed.

**Penalty.** `LinearEqualityToPenalty` from qiskit-optimization builds the QUBO. The penalty weight is the smallest value in a scan {0.3, 0.5, …, 10} for which the exact ground state of the Ising Hamiltonian (computed over all 2^11 basis states) is the constrained optimum, multiplied by 1.4 for margin. `to_ising()` yields a 66-term Z/ZZ Hamiltonian, normalised by its largest coefficient.

## 7. QAOA

- Ansatz: `qiskit.circuit.library.QAOAAnsatz` (standard X mixer), depth `p = 1 … 4`.
- Angles: COBYLA on the exact expectation value computed by `qiskit_aer` statevector simulation; three linear-ramp (TQA-style) starting points per depth plus an INTERP warm start from depth `p - 1`.
- Sampling: `qiskit_aer.primitives.SamplerV2`, 8,192 shots on the best depth.
- Hardware: the depth-2 circuit with its optimised angles is transpiled at optimisation level 3 for the least-busy operational IBM Quantum backend with at least 11 qubits and submitted with `qiskit_ibm_runtime.SamplerV2` in job mode (dynamical decoupling XY4, gate twirling), 4,096 shots. If the queue estimate exceeds 10 minutes, the job does not return within 10 minutes, or any connection error occurs, the script records the reason and the Aer result is used.
- Decoding: Qiskit bitstrings are little-endian (qubit 0 is the rightmost character). The first seven qubits are the party variables in the order National, Labour, Green, ACT, NZ First, Te Pāti Māori, TOP. A sample is feasible if the *exact* seats of the selected parties reach the majority; slack bits are ignored at readout (standard practice). The reported quantum result is the best-objective feasible sample.

## 8. What the quantum part does and does not show

QAOA learns the majority constraint well: at `p = 2` more than 85% of the probability sits on majority coalitions, against 60% for uniform sampling. It resolves the policy objective only weakly at these depths: the exact optimum bitstring carries a few tenths of a percent of the probability, a few times the uniform baseline. The optimum is recovered by post-selecting the best feasible sample, which is how QAOA is used in practice. With 128 coalitions the problem is classically trivial and is solved by brute force in the same script as a check. The value of the exercise is an auditable, end-to-end pipeline from policy evidence to a quantum circuit on real hardware, not a speed-up.

## 9. Limitations

1. Six of seven party research files lack independent evidence because of the search-quota problem; their scores lean on official policy pages plus the author's knowledge of the published evidence.
2. Scores and positions are expert judgements. They are documented cell by cell, but another analyst would produce different numbers. Change them in `policy_data.json` and re-run.
3. The incumbent/opposition asymmetry (Section 2) likely flatters TOP.
4. Seat numbers depend on one polling scenario (six-poll mean, Te Pāti Māori with 4 electorates). A 2-point swing changes bloc arithmetic materially, and TOP falling under 5% flips the result to a National-led majority.
5. The friction model treats every domain equally; in reality tax and Te Tiriti dominate coalition talks.
6. Hardware results from an 11-qubit, depth-2 circuit with about 405 two-qubit gates after routing are noisy (total variation distance 0.25 from the ideal coalition distribution); they are reported next to the ideal distribution, not in place of it.
