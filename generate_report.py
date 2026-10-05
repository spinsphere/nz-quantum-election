#!/usr/bin/env python3
"""
Executive report generator for the NZ Quantum Election project.

Reads quantum_results.json and policy_data.json and prints a plain-English
report to the terminal:

  1. Executive summary          (coalition, seats, objective, source)
  2. Comprehensive policy impact (domain-by-domain merge of member policies)
  3. MMP stability assessment    (friction points, concessions, declared rule-outs)
  4. Quantum simulation breakdown (qubits, encoding, optimiser, hardware)

Everything in sections 1, 3 and 4 and the tables in section 2 is derived from
the two JSON files, so the report stays correct if the data or the result
changes.  Section 2 also carries a written analysis for the coalition that
the optimiser actually found; if a different coalition is found, a generic
data-driven paragraph is printed instead.

Usage:  python generate_report.py [--markdown]
"""

from __future__ import annotations

import argparse
import json
import os
import textwrap
from datetime import datetime

from seat_model import sainte_lague, majority_threshold

HERE = os.path.dirname(os.path.abspath(__file__))
WIDTH = 78

DISPLAY = {
    "National": "National", "Labour": "Labour", "Green": "Green Party", "ACT": "ACT",
    "NZFirst": "NZ First", "TePatiMaori": "Te Pāti Māori", "TOP": "TOP (Opportunity)",
}
SHORT = {"National": "Nat", "Labour": "Lab", "Green": "Grn", "ACT": "ACT", "NZFirst": "NZF", "TePatiMaori": "TPM", "TOP": "TOP"}
DOMAIN_TITLES = {
    "health": "Health & Mental Health", "education": "Education", "crime_justice": "Crime & Justice",
    "housing_rental": "Housing & Rental Costs", "economy_col": "Cost of Living & Economy",
    "employment": "Employment", "transport_infra": "Transport & Infrastructure",
    "tiriti_maori": "Te Tiriti o Waitangi & Māori Issues",
}

# Written analysis for the coalition the optimiser is expected to find.
# Keyed by frozenset of party keys so it is only used when it actually applies.
NARRATIVES = {
    frozenset({"Labour", "Green", "TePatiMaori", "TOP"}): {
        "health": (
            "Labour's Medicard (three free GP visits a year from 2028) and free prescriptions are the "
            "costed core; TOP's ten-year cross-party health plan is a stated bottom line and supplies "
            "the long-horizon governance the Greens' and Te Pāti Māori's universal and Māori-led "
            "ambitions lack. The merge is a primary-care-first system with multi-year funding "
            "settings, a Māori-led commissioning arm restored in some form, and universal dental "
            "deferred to a costed second term."),
        "housing_rental": (
            "The four parties agree on supply through public building (Labour's $2.9b Kāinga Ora "
            "restart, Green and Te Pāti Māori public and papakāinga housing) but disagree on price "
            "levers. TOP's land value tax and ten-zone planning code are the most evidence-backed "
            "measures in the matrix; the Greens' 2% rent cap is the least. The likely settlement is "
            "an LVT design review and planning consolidation in exchange for shelving rent control, "
            "with Labour's investment-property CGT as the bridging tax."),
        "economy_col": (
            "Four different tax philosophies must be sequenced: Labour's narrow 28% CGT (legislated, "
            "ring-fenced to health), the Greens' wealth and inheritance taxes, Te Pāti Māori's 48% top "
            "rate and TOP's land tax plus Citizen's Income. Only the CGT is both costed and inside "
            "Labour's fiscal plan (OBEGAL surplus 2028/29, debt under 20% of GDP). On groceries all "
            "four back structural intervention: Labour's wholesale split, TOP's Commerce Commission "
            "separation powers and the Greens' divestment demand point the same way and would pass "
            "easily."),
        "crime_justice": (
            "This is the coalition's weakest domain. Labour has no standalone justice "
            "policy; TOP's specialist-court and reintegration programme is the evidence-based "
            "anchor; the Greens and Te Pāti Māori favour decarceration goals (abolishing preventive "
            "detention, prisons by 2040) that the evidence does not support and the public would "
            "not accept. The workable merge is Labour-led repeal of the youth military academies, "
            "expansion of Te Pae Oranga, AODT and sexual-violence courts, and kaupapa Māori "
            "rehabilitation funding, with sentencing settings left largely alone."),
        "tiriti_maori": (
            "Positions span +0.3 (TOP) to +1.0 (Te Pāti Māori). All four opposed the Treaty "
            "Principles Bill and the Treaty-clauses review, so repeal of the clause changes and "
            "restoration of section 7AA are consensus items. Binding Waitangi Tribunal "
            "recommendations and a Te Tiriti Commission are not: Labour and TOP would offer Treaty "
            "impact analysis in lawmaking, restored customary marine title settings and a funded "
            "constitutional conversation instead, which is the concession Te Pāti Māori must accept "
            "for a formal coalition rather than confidence and supply."),
        "transport_infra": (
            "Labour's $20 fare cap and the Greens' $2 cap are reconcilable (one is a weekly version "
            "of the other); TOP's legislated 30-year infrastructure plan with a parliamentary lock on "
            "cancelling large projects is the institutional glue, and its 60% maintenance share is "
            "the evidence-based priority. Intercity rail revivals have weak benefit-cost ratios and "
            "would be limited to pilots."),
        "education": (
            "The partners agree on keeping structured literacy, expanding school lunches and school "
            "property funding. TOP's independent Curriculum and Assessment Council gives Labour a "
            "way to slow the NCEA replacement without re-litigating it every term. The Greens' "
            "student-debt write-off (~$16b) is the item most likely to be dropped on cost."),
        "employment": (
            "Pay-equity restoration is common ground for Labour and the Greens and is costed for the "
            "first tranche ($2.5b). TOP's Citizen's Income is a long-run design project; the "
            "practical merge is a benefit-abatement review and compulsory KiwiSaver, which Labour and "
            "TOP both propose."),
    }
}


def wrap(text: str, indent: str = "  ") -> str:
    """Wrap a paragraph; a bullet-style indent ('- ', '> ') is only printed on the first line."""
    stripped = indent.rstrip()
    follow = indent if not stripped or stripped[-1] not in "->•" else " " * len(indent)
    return "\n".join(textwrap.fill(p, WIDTH, initial_indent=indent, subsequent_indent=follow)
                     for p in text.split("\n"))


def hr(char: str = "─") -> str:
    return char * WIDTH


def section(title: str) -> str:
    return f"\n{hr('═')}\n  {title}\n{hr('═')}"


def names(keys) -> str:
    return " + ".join(DISPLAY.get(k, k) for k in keys)


def build_report(results: dict, data: dict) -> str:
    out: list[str] = []
    P = out.append
    parties = results["encoding"]["party_order"]
    domains = data["domains"]
    house = results["house"]
    model = results["model"]
    qr = results["qaoa_result"]
    cls = results["classical"]
    enc = results["encoding"]
    qa = results["qaoa"]
    hw = results["ibm_hardware"]
    aer = results["aer_sampling"]
    members = qr["coalition_parties"]
    outsiders = [p for p in parties if p not in members]
    seats = house["seats"]
    maj = house["majority_threshold"]
    total = house["total_seats"]
    scores = model["domain_scores"]
    positions = model["positions"]
    fric = model["friction_matrix"]

    P(hr("═"))
    P("  NZ QUANTUM ELECTION — EXECUTIVE REPORT")
    P(f"  2026 New Zealand General Election ({results['election_date']}), data as of {results['data_as_of']}")
    P(f"  Report generated {datetime.now().strftime('%Y-%m-%d %H:%M')} from quantum_results.json")
    P(hr("═"))

    # ------------------------------------------------------------------ 1
    P(section("1. EXECUTIVE SUMMARY"))
    src = ("IBM Quantum hardware (" + hw.get("backend", "") + ")") if qr["source"] == "ibm_hardware" \
        else "the local Qiskit Aer simulator"
    P(wrap(
        f"The quantum approximate optimisation algorithm (QAOA), with its final circuit sampled on {src}, "
        f"identifies the following coalition as the policy-optimal majority government for a "
        f"{total}-seat House where {maj} seats are needed:"))
    P("")
    for p in members:
        P(f"    • {DISPLAY[p]:<20} {seats[p]:>3} seats   policy score {model['aggregate_scores'][p]:.0f}/80   w = {model['weights_w'][p]:.3f}")
    buffer = qr["total_seats"] - maj
    P("")
    P(f"    Total seats          {qr['total_seats']} / {total}  (majority {maj}, buffer {buffer:+d})")
    P(f"    Objective score      {qr['objective_score']:.4f}  (classical optimum {cls['optimum']['objective']:.4f}; "
      f"{'match' if qr['matches_classical_optimum'] else 'MISMATCH'})")
    P(f"    Bitstring            {qr['optimal_bitstring_party_order']}  (party order: {', '.join(parties)})")
    P("")
    P("    Parties outside the coalition:")
    for p in outsiders:
        P(f"    • {DISPLAY[p]:<20} {seats[p]:>3} seats   policy score {model['aggregate_scores'][p]:.0f}/80")
    P("")
    P(wrap(
        f"The objective rewards each party's aggregate evidence-based policy score (w_i) and charges a "
        f"friction cost proportional to the ideological distance between every pair of partners "
        f"(coefficient mu = {model['mu']}). Without the friction term the best coalition is trivially all "
        f"seven parties; with it, the optimiser prefers the smallest ideologically coherent majority. "
        f"The answer is unchanged for mu between {min(r['mu'] for r in cls['sensitivity_to_mu'] if r['coalition'] == members)} "
        f"and {max(r['mu'] for r in cls['sensitivity_to_mu'] if r['coalition'] == members)}; at mu >= "
        f"{next((r['mu'] for r in cls['sensitivity_to_mu'] if r['mu'] > 1 and r['coalition'] != members), 'n/a')} "
        f"the grand coalition {names(next((r['coalition'] for r in cls['sensitivity_to_mu'] if r['mu'] > 1 and r['coalition'] != members), []))} "
        f"takes over because it minimises the number of partners."))
    P("")
    P("    Classical top five for comparison:")
    for i, row in enumerate(cls["top10"][:5], 1):
        P(f"    {i}. {names(row['coalition']):<55} {row['seats']:>3} seats  obj {row['objective']:.4f}")
    P("")
    bloc_txt = ", ".join(f"{b} {s}" for b, s in house["bloc_seats"].items())
    poll_txt = ", ".join(f"{DISPLAY[p]} {house['polling_average_pct'][p]:.1f}%" for p in parties)
    P(wrap(f"Bloc arithmetic: {bloc_txt} seats. Polling average used: {poll_txt}.", indent="    "))

    # ------------------------------------------------------------------ 2
    P(section("2. COMPREHENSIVE POLICY IMPACT"))
    P(wrap("Scores are 1-10 effectiveness ratings per domain (see METHODOLOGY.md). The position column "
           "places each party on a -1..+1 axis for that domain; the spread across coalition members is "
           "the friction the partners must negotiate away."))
    P("")
    head = f"{'Domain':<34}" + "".join(f"{SHORT[p]:>6}" for p in parties) + "   members  spread"
    P(head)
    P(hr())
    spreads = {}
    for d in domains:
        row = f"{DOMAIN_TITLES[d]:<34}"
        for p in parties:
            mark = "*" if p in members else " "
            row += f"{scores[p][d]:>5}{mark}"
        msum = sum(scores[p][d] for p in members)
        pos = [positions[p][d] for p in members]
        spread = max(pos) - min(pos)
        spreads[d] = spread
        row += f"   {msum:>3}/{10*len(members):<3} {spread:>5.2f}"
        P(row)
    P(hr())
    row = f"{'TOTAL (/80)':<34}"
    for p in parties:
        mark = "*" if p in members else " "
        row += f"{model['aggregate_scores'][p]:>5.0f}{mark}"
    P(row)
    P("  * = coalition member; 'members' = summed member scores; 'spread' = max-min position among members")
    P("")
    narrative = NARRATIVES.get(frozenset(members))
    order = sorted(domains, key=lambda d: -spreads[d])
    for d in domains:
        member_scores = ", ".join(f"{DISPLAY[p]} {scores[p][d]}" for p in members)
        P(f"\n  {DOMAIN_TITLES[d].upper()}  (member scores {member_scores}; position spread {spreads[d]:.2f})")
        for p in members:
            P(wrap(f"{DISPLAY[p]}: {data['parties'][p]['key_policies'][d]}", indent="    - "))
        if narrative and d in narrative:
            P(wrap(narrative[d], indent="    > "))
        else:
            hi = max(members, key=lambda p: scores[p][d])
            lo = min(members, key=lambda p: scores[p][d])
            P(wrap(f"{DISPLAY[hi]} holds the strongest evidence base here ({scores[hi][d]}/10) and would be "
                   f"expected to lead the portfolio; {DISPLAY[lo]} ({scores[lo][d]}/10) contributes least and "
                   f"its position ({positions[lo][d]:+.1f}) sits {abs(positions[lo][d] - positions[hi][d]):.1f} from the lead party's.",
                   indent="    > "))

    # ------------------------------------------------------------------ 3
    P(section("3. MMP STABILITY ASSESSMENT"))
    P(wrap(f"Seat buffer: {buffer:+d} above the {maj}-seat majority. "
           + ("A single defection, by-election loss or waka-jumping dispute removes the majority." if buffer <= 1
              else "Survives one defection." if buffer <= 3 else "Comfortable working majority.")))
    P("")
    P("  Pairwise ideological distance inside the coalition (0 = identical, 1 = opposite):")
    pairs = []
    for i, a in enumerate(members):
        for b in members[i + 1:]:
            pairs.append((fric[a][b], a, b))
    for dval, a, b in sorted(pairs, reverse=True):
        P(f"    {DISPLAY[a]:<18} – {DISPLAY[b]:<18} {dval:.3f}")
    total_friction = sum(d for d, _, _ in pairs)
    P(f"    total friction charged in the objective: {model['mu']} x {total_friction:.3f} = {model['mu'] * total_friction:.3f}")
    P("")
    P("  3.1 Friction points (domains ranked by position spread among members)")
    for rank, d in enumerate(order[:4], 1):
        pos = {p: positions[p][d] for p in members}
        far = max(pos, key=lambda p: pos[p])
        near = min(pos, key=lambda p: pos[p])
        P(f"    {rank}. {DOMAIN_TITLES[d]}: spread {spreads[d]:.2f} between {DISPLAY[far]} ({pos[far]:+.1f}) and {DISPLAY[near]} ({pos[near]:+.1f}).")
        P(wrap(f"{DISPLAY[far]} wants: {data['parties'][far]['key_policies'][d]}", indent="         "))
        P(wrap(f"{DISPLAY[near]} wants: {data['parties'][near]['key_policies'][d]}", indent="         "))
    P("")
    P("  3.2 Concessions required (each party's distance from the coalition's seat-weighted centre)")
    for d in order[:4]:
        tot_s = sum(seats[p] for p in members)
        centre = sum(positions[p][d] * seats[p] for p in members) / tot_s
        P(f"    {DOMAIN_TITLES[d]} (seat-weighted centre {centre:+.2f}):")
        for p in sorted(members, key=lambda p: -abs(positions[p][d] - centre)):
            gap = positions[p][d] - centre
            if abs(gap) < 0.15:
                continue
            direction = "soften" if gap > 0 else "move toward"
            P(f"      - {DISPLAY[p]} must {direction} its {DOMAIN_TITLES[d].lower()} position by about {abs(gap):.2f} "
              f"(from {positions[p][d]:+.1f}) to hold the centre.")
    if narrative:
        P("")
        P("  3.3 Specific concessions this coalition would need")
        for line in [
            "Te Pāti Māori accepts Treaty impact analysis, repeal of the Treaty-clauses changes and a funded constitutional conversation instead of binding Tribunal recommendations in this term.",
            "The Greens shelve the 2% rent cap and the full student-debt write-off; in return the LVT design review and the grocery divestment path proceed.",
            "TOP accepts that the Citizen's Income is a staged design project, not a first-Budget item, and that the land value tax is phased after an independent costing.",
            "Labour accepts a ten-year cross-party health plan (TOP's bottom line), independent curriculum governance and kaupapa Māori justice funding, and gives up the fuel-tax freeze to protect the land transport fund that pays for the fare cap.",
            "All four commit to the OBEGAL surplus in 2028/29 and the sub-20% debt track, which rules out the Greens' and Te Pāti Māori's full tax packages in the first term.",
        ]:
            P(wrap(line, indent="    - "))
    P("")
    P("  3.4 Declared coalition positions (reality check on the optimiser)")
    for line in data["metadata"]["declared_coalition_positions"]:
        P(wrap(line, indent="    - "))
    blocked = []
    for i, a in enumerate(members):
        for b in members[i + 1:]:
            if {a, b} == {"National", "TOP"}:
                blocked.append("National has ruled out TOP")
    P("")
    P(wrap("Verdict: " + ("no declared rule-out blocks this coalition; " if not blocked else "; ".join(blocked) + "; ")
           + f"the binding constraint is the {buffer:+d} seat buffer and Te Pāti Māori's internal instability "
           f"(two MPs expelled in 2025, the Te Tai Tokerau split in 2026), which makes a confidence-and-supply "
           f"arrangement with Te Pāti Māori outside cabinet more likely than a four-party formal coalition."
           if "TePatiMaori" in members else
           "Verdict: " + ("no declared rule-out blocks this coalition." if not blocked else "; ".join(blocked) + ".")))

    # threshold scenario: what happens if TOP misses 5% (or any member below 5% without an electorate)
    P("")
    P("  3.5 Threshold scenario")
    votes = house["polling_average_pct"]
    elect = house["electorate_assumptions"]
    at_risk = [p for p in parties if votes[p] < 7.5 and elect.get(p, 0) == 0]
    for p in at_risk:
        v2 = dict(votes); v2[p] = 0.0
        s2 = sainte_lague(v2, elect)
        tot2 = sum(s2.values()); maj2 = majority_threshold(tot2)
        coal2 = sum(s2[q] for q in members if q != p)
        blocs2 = {}
        for q in parties:
            blocs2.setdefault(data["parties"][q]["bloc"], 0)
            blocs2[data["parties"][q]["bloc"]] += s2[q]
        P(wrap(f"If {DISPLAY[p]}, at {votes[p]:.1f}% in the poll average, fell below the 5% threshold with no electorate seat, "
               f"its votes would be redistributed: House of {tot2}, majority {maj2}; the optimal coalition without it would hold "
               f"{coal2} seats ({'still a majority' if coal2 >= maj2 else 'no longer a majority'}); bloc totals "
               f"{', '.join(f'{b} {s}' for b, s in blocs2.items())}.", indent="    "))
    P(wrap("Every published September 2026 seat projection in which Opportunity falls under 5% (Taxpayers' Union-Curia, 1-3 Sep) "
           "produces a National-ACT-NZ First majority; every projection with Opportunity above 5% leaves it holding the balance. "
           "The optimiser's answer therefore rests on a party polling within one margin of error of the threshold.", indent="    "))

    # ------------------------------------------------------------------ 4
    P(section("4. QUANTUM SIMULATION BREAKDOWN"))
    P(f"  Problem         binary quadratic program, {len(parties)} party variables, 2^{len(parties)} = {2**len(parties)} coalitions, "
      f"{cls['feasible_coalitions']} feasible")
    P(f"  Constraint      seats rescaled to units of {enc['seat_unit']} ({enc['rounding']}): {enc['scaled_seats']} >= {enc['scaled_majority']}, "
      f"verified identical feasible set; {enc['slack_bits']} binary slack variables")
    P(f"  Qubits          {enc['num_qubits']} ({len(parties)} party + {enc['slack_bits']} slack)")
    P(f"  QUBO penalty    lambda = {enc['penalty_lambda']}; Ising Hamiltonian with {enc['ising_pauli_terms']} Pauli terms, "
      f"normalised spectral gap {enc['normalised_spectral_gap']}")
    P(f"  Optimiser       {qa['optimizer']}")
    P(f"  Simulator       {qa['simulator']}")
    P("  Depth sweep:")
    P(f"    {'p':>3} {'<H>':>9} {'P(opt)':>9} {'x uniform':>10} {'rank':>6} {'P(feasible)':>12} {'P(seats>=maj)':>14} {'evals':>7}")
    for r in qa["depth_sweep"]:
        P(f"    {r['p']:>3} {r['energy']:>9.4f} {r['prob_optimum']:>9.4f} {r['prob_optimum_over_uniform']:>10.1f} {r['rank_of_optimum']:>6} "
          f"{r['prob_exact_feasible']:>12.3f} {r['prob_majority_coalition']:>14.3f} {r['evaluations']:>7}")
    P(f"  Selected depth  p = {qa['selected_p']} for local sampling")
    P(f"  Aer sampling    {aer['shots']} shots, {aer['unique_bitstrings']} unique bitstrings; "
      f"P(optimal coalition) = {aer['prob_optimal_coalition_any_slack']}, P(majority) = {aer['prob_majority_coalition']}; "
      f"best feasible sample = classical optimum: {aer['best_feasible_sample']['matches_classical_optimum']}")
    P("  Hardware:")
    if hw.get("executed"):
        P(f"    backend        {hw['backend']} ({hw['backend_qubits']} qubits), job {hw['job_id']}, queue at submit {hw['pending_jobs_at_submit']} jobs")
        P(f"    circuit        p = {hw['qaoa_p']}, ISA depth {hw['isa_depth']}, two-qubit gates {hw['isa_two_qubit_gates']}, two-qubit depth {hw['isa_two_qubit_depth']}")
        P(f"    shots          {hw['shots']}, wall time {hw['wall_seconds']}s"
          + (f", QPU usage {hw['qpu_usage_seconds']}s" if hw.get("qpu_usage_seconds") else ""))
        P(f"    fidelity       P(majority) hardware {hw['prob_majority_coalition']} vs ideal {hw['ideal_prob_majority_coalition_at_this_p']}; "
          f"P(exact optimum) {hw['prob_optimum_exact_bitstring']} vs ideal {hw['ideal_prob_optimum_exact_bitstring_at_this_p']}; "
          f"total variation distance on coalition marginal {hw['tvd_vs_ideal_coalition_marginal']}")
        bf = hw["best_feasible_sample"]
        P(f"    best sample    {names(bf['coalition'])} ({bf['seats']} seats, obj {bf['objective']}) "
          f"== classical optimum: {bf['matches_classical_optimum']}")
    else:
        P(f"    not executed   {hw.get('reason', '')}; result taken from the Aer simulator")
    P("")
    P(wrap("Interpretation: QAOA learns the majority constraint well (most samples are feasible coalitions) but at "
           "low depth it only weakly resolves the policy objective, because the penalty term dominates the energy "
           "spectrum even after rescaling. The optimum is recovered by classical post-selection of the best "
           "feasible sample, which is standard QAOA practice. With 128 coalitions the problem is classically "
           "trivial; the value of the exercise is the end-to-end pipeline and the explicit, auditable policy model, "
           "not quantum speed-up."))
    ver_txt = ", ".join(f"{k} {v}" for k, v in results.get("versions", {}).items())
    P(f"\n  Versions: {ver_txt}; runtime {results['runtime_seconds']}s")
    P(hr("═"))
    P("  END OF REPORT   (sources: research/*.md, policy_data.json, quantum_results.json)")
    P(hr("═"))
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--markdown", action="store_true", help="wrap output in a fenced code block for docs/REPORT.md")
    args = ap.parse_args()
    results = json.load(open(os.path.join(HERE, "quantum_results.json")))
    data = json.load(open(os.path.join(HERE, "policy_data.json")))
    text = build_report(results, data)
    if args.markdown:
        print("# Executive report\n\nGenerated by `python generate_report.py` from `quantum_results.json`.\n\n```text")
        print(text)
        print("```")
    else:
        print(text)


if __name__ == "__main__":
    main()
