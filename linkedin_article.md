# I asked a quantum computer which coalition should govern New Zealand. Here is what it said, and what it couldn't.

*SpinSphere, October 2026. Code, data and sources: github.com/spinsphere/nz-quantum-election*

A month before New Zealand votes on 7 November, the polls describe a stalemate. National and Labour are tied near 28%, and this morning's RNZ-Reid Research poll put National at 25.9%, its worst since 2020. Averaged over the six most recent polls, the governing National–ACT–NZ First bloc projects to 59 seats, three short of a majority. The Labour–Green–Te Pāti Māori bloc projects to 55. The eight seats in between belong to TOP, which National has ruled out working with, while NZ First has ruled out Labour.

So I did something slightly unusual with that arithmetic. I turned the coalition question into a binary optimisation problem, encoded it as a quantum Hamiltonian, and ran it through the Quantum Approximate Optimization Algorithm (QAOA) on an IBM Quantum processor. No punditry, no preferred outcome: just published policy evidence, measured ideological distance, and the seat maths.

## The answer

**Labour + Green + Te Pāti Māori + TOP. 63 seats of 122. One seat to spare.**

The quantum circuit's best sample on IBM's `ibm_fez` processor matched the classical brute-force optimum exactly, as did an earlier run on `ibm_marrakesh`. The runner-up, well behind, was a National + Labour + TOP arrangement, then a National + Labour grand coalition.

Before anyone celebrates or despairs, read the next two sections. The interesting part is how the answer was produced, and what it depends on.

## How I scored the parties

Each of the seven parties was researched across eight domains: health, education, crime and justice, housing, cost of living and the economy, employment, transport and infrastructure, and Te Tiriti o Waitangi. For each domain I asked one question: based on independent evidence (Treasury, the Reserve Bank, OECD, Ministry evaluations, the Waitangi Tribunal, peer-reviewed research), how effectively would this party's stated 2026 policies, and its record where it has governed, advance stability, growth and equality? Scores run from 1 to 10 and every cell has a written rationale in the repository.

Some of those scores will annoy people on both sides. National's structured-literacy programme scores well because the phonics data is real. Its sentencing laws score poorly because the Ministry of Justice projects a 35% rise in the prison population with weak deterrence evidence. The Greens' rent cap scores poorly because the economics literature on rent control is close to unanimous. TOP scores highest overall (53/80) partly because a land value tax and ten-year cross-party plans are what the evidence recommends, and partly because a party that has never governed is never contradicted by its own outcome data. I flag that asymmetry in the methodology rather than pretend it away.

Totals out of 80: TOP 53, Labour 44, Green 44, National 41, Te Pāti Māori 39, ACT 33, NZ First 26. The Greens' score rose a point when their full tax paper turned out to be modelled by the Parliamentary Library and reviewed by Infometrics; Te Pāti Māori's health score rose and its housing score fell once its manifesto chapters (free primary and dental care for all; a universal rent freeze) replaced the one-paragraph summaries.

## Why the obvious model gives a stupid answer

The naive formulation is: pick the set of parties that maximises total policy score subject to holding 62 seats. That problem has a trivial answer. Every party has a positive score, so the "optimal" coalition is all seven of them. A model that recommends a seven-party government has told you nothing.

What actually limits coalitions under MMP is ideological distance. So each party is also placed on a -1 to +1 position axis per domain (market versus state in health, punitive versus rehabilitative in justice, single standard versus Treaty partnership, and so on), and every pair of coalition partners is charged a friction cost proportional to how far apart they sit. National and ACT are 0.19 apart. Labour and TOP are 0.09 apart. Green and ACT are 0.85 apart. That friction term is what turns a trivial knapsack into a genuine quadratic program, and it is what makes QAOA the right tool class rather than a gimmick.

The result is robust: the same coalition wins for any friction coefficient between half and one-and-a-half times the baseline. Push friction above twice the baseline and the model switches to a National + Labour grand coalition, because two parties generate less friction than four. That switch point is worth knowing about: it is the quantitative version of "if the small parties are impossible, the big two will have to talk".

## The quantum part, honestly

The seat constraint was encoded with binary slack variables, after rescaling seats to six-seat units (verified to reproduce the exact feasible set for all 128 possible coalitions), giving an 11-qubit problem. QAOA angles were optimised on an exact simulator for circuit depths 1 to 4, and the depth-2 circuit was transpiled to 405 two-qubit gates and run on `ibm_fez` with 4,096 shots. Zero queue, 12 seconds wall time, 3 seconds of QPU time on IBM's free Open plan.

What QAOA did well: it learned the majority constraint. 88% of ideal samples and 67% of hardware samples were majority coalitions, against 60% for random guessing.

What it did weakly: it barely resolved the policy objective at these depths. The exact optimum bitstring had about six times the probability of a random guess, which with thousands of shots is enough to find it reliably, but the most frequently sampled coalitions were large, low-scoring ones. The penalty term that enforces the seat constraint dominates the energy landscape even after rescaling, which is a well-known limitation of penalty-based QAOA on knapsack-type constraints. The optimum was recovered by post-selecting the best feasible sample, which is standard practice.

And the obvious caveat: with 128 possible coalitions this problem is classically trivial. The same script brute-forces it in milliseconds as a check. There is no quantum speed-up here, and anyone who tells you otherwise about a 7-party coalition problem is selling something. The value is in the pipeline: an auditable path from policy evidence to a quantum circuit on real hardware, where every input can be changed and the whole thing re-run.

## What the result means politically

The model says the coalition with the best evidence-weighted policy programme and the least internal friction is a four-party centre-left arrangement with a one-seat buffer. Three things follow.

First, the one-seat buffer is the whole story. A single by-election, defection or waka-jumping dispute removes the majority. Te Pāti Māori's recent instability (two MPs expelled in 2025, a breakaway Te Tai Tokerau Party in 2026) makes a confidence-and-supply arrangement from outside cabinet more likely than a formal four-party coalition.

Second, the friction points the model identifies are the ones you would expect from the campaign: justice (Te Pāti Māori's prison-abolition goal against Labour's near-silence), Te Tiriti (binding Tribunal recommendations against Treaty impact analysis), and tax (four different philosophies, only one of which, Labour's narrow capital gains tax, is costed inside a fiscal plan). The concessions needed to hold the centre are spelled out in the report.

Third, the whole result hinges on a party sitting half a point above the 5% threshold. TOP polls between 4.5% and 9.5%. In every September projection where it clears 5%, it holds the balance of power; in the one where it does not, National, ACT and NZ First win a majority outright. The right bloc's problem is arithmetic, not policy: at 59 seats it needs TOP, and both sides have said no. If the polls move two points, or TOP slips under the line, the picture changes, and the repository lets you test exactly that by editing one line.

## Try it

Everything is open: the research files with sources, the scoring matrix with its rationale, the Sainte-Laguë seat model, the QAOA code, the IBM job ID, and the report generator. Disagree with a score? Change it and re-run. Think Te Pāti Māori will hold six electorates rather than four? Change it and re-run. The code will give you a different government and tell you how robust it is.

What the quantum computer cannot do is tell you what you value. That part is still yours, on 7 November.

*This is a mathematical exercise using publicly available policy information. It is not an endorsement of any party. The scoring is an expert judgement, documented cell by cell so it can be challenged.*

#QuantumComputing #Qiskit #IBMQuantum #QAOA #NewZealand #NZElection2026 #MMP #PublicPolicy #OpenSource
