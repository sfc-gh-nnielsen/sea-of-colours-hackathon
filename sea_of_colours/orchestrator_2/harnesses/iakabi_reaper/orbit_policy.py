"""The seat's buying policy — what to spend credits and BLUE on, in orbit.

**This file is yours to change.** It was forked out of the shared
``sea_of_colours.agent.heuristic_agent`` planner in v1.40 for one reason:
a fork could not previously edit how its agent spends money. The planner
lived in a module every seat in the room shares, so "buy weapons earlier"
was not a change any single team could make or push.

Everything below is now local. Two surfaces, deliberately separated:

* :class:`OrbitDials` — the numbers. Thresholds, stockpile caps, the
  fallback prices. Retuning the seat's economy should be an edit here and
  nowhere else, which is what makes it a safe change to hand to a coding
  assistant.
* :func:`plan_orbit_actions` — the priority order. Repair, then fleet,
  then weapons, then probes. Reordering these, or adding a priority, is
  the structural change; the dials are the cheap one.

At the shipped dials this is byte-identical to the shared planner — same
actions, same rationale string — so V12's baseline scores did not move
when it was forked. ``tests/test_orbit_policy.py`` pins that with a
differential test against the shared implementation; if you retune the
dials, that test is *expected* to fail and should be updated or dropped.

Known holes, left deliberately (they are the exercise):

* **Nothing here reads the board.** Buying is a function of credits,
  BLUE and fleet state only. A policy of the form "buy an EMP when a
  redsign is live" needs the night-phase view, which is on ``view`` and
  simply not consulted yet.
* **EMP is capped at a small stockpile** so the seat cannot hoard salvos
  it never fires. That cap is also why V12 buys weapons and leaves them
  in the rack — raising it without teaching the night phase to fire them
  makes the agent worse, not better.
"""

from __future__ import annotations

import random as _random
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Tuple

from sea_of_colours.game.session import (
    HARVESTER_BUILD_COST,
    PROBE_BUILD_COST,
    REPAIR_COST,
)
from sea_of_colours.game.weapons import (
    CHAFF_COST_BLUE_PURITY,
    CHAFF_COST_CREDITS,
    EMP_COST_BLUE_PURITY,
    EMP_COST_CREDITS,
    SNAP_COST_BLUE_PURITY,
    SNAP_COST_CREDITS,
    WEAPONISED_BLUE_CAP,
)

# --- weapon-forge hook (installed by forge_install.py) ---
from sea_of_colours.orchestrator_2.harnesses.iakabi_reaper import weapon_forge


@dataclass(frozen=True)
class OrbitDials:
    """Every number the buying policy consults.

    Prices are *fallbacks only*. The engine sends real prices on the view
    (``orbit.ship_prices`` / ``orbit.weapon_prices``) and those win; these
    exist so a stripped-down test view still plans sanely.

    The thresholds are the interesting ones — they are the seat's
    economic doctrine expressed as three numbers.
    """

    #: Probe magazine the playbook tops up toward each turn. Sized for a
    #: night of hot-drops (one securing probe per uncovered vein,
    #: RULEBOOK §3.9.7) plus an exploration probe.
    #:
    #: 4 -> 2 after the 18-season soak. Two findings:
    #:   * Probes were the credit leak. At 250c each, a magazine of 4 is 1000c
    #:     while EVERY season deferred a harvester short by roughly 250c.
    #:   * tabula_v12 scores WITHOUT probing, off red it already remembers,
    #:     because _harvest_at has no visibility check — vision is needed only
    #:     to LAND (RULEBOOK §3.9.7). So probe spend buys landings, not yield.
    #:
    #: MUST STAY STRICTLY POSITIVE. The active drop mode is `live_only` and an
    #: orbital harvester has no position, so it lights nothing: with zero probes
    #: the FIRST drop of the season is illegal and the seat never gets going.
    #: Probes also expire after 3 nights, so one on night 1 is not durable.
    #: A landed harvester lights a radius-1 plus, so later drops can piggyback
    #: on it — which is why 2 is enough and 0 is fatal.
    probe_target_stock: int = 2

    #: BLUE above which a weapon is ALWAYS built: chaff first when the
    #: rack is empty (the hour 5-7 / 11-13 egress jam, RULEBOOK §5),
    #: else an EMP.
    blue_always_build: int = 300
    #: BLUE above which an EMP build is rolled for at
    #: :attr:`emp_roll_chance`. Between this and
    #: :attr:`blue_always_build` the build stays a coin flip.
    blue_emp_roll: int = 250
    #: Probability of the roll above landing.
    emp_roll_chance: float = 0.5

    #: Stop buying EMP at this many in stock. Deliberately low — see the
    #: module docstring on hoarding.
    emp_stockpile_cap: int = 2
    #: Stop buying chaff at this many in stock, in the always-build band.
    chaff_stockpile_cap: int = 1

    # Fallback prices — IMPORTED from the engine, not retyped (v14).
    #
    # These were hand-copied literals and two of them had drifted:
    # ``emp_credit_cost`` said 0 where game/weapons.py says 250, and there
    # were no SNAP dials at all. A price the planner believes is zero is a
    # price it never weighs, which is how this seat came to treat ordnance
    # as blue-only — and a fork that reads these lines to learn what a
    # weapon costs learns the wrong number. Single-source them; a retune
    # of the engine dials now reaches the planner with no edit here.
    repair_cost: int = REPAIR_COST
    probe_build_cost: int = PROBE_BUILD_COST
    harvester_build_cost: int = HARVESTER_BUILD_COST
    harvester_cap: int = 3
    emp_blue_cost: int = EMP_COST_BLUE_PURITY
    emp_credit_cost: int = EMP_COST_CREDITS
    chaff_blue_cost: int = CHAFF_COST_BLUE_PURITY
    chaff_credit_cost: int = CHAFF_COST_CREDITS
    snap_blue_cost: int = SNAP_COST_BLUE_PURITY
    snap_credit_cost: int = SNAP_COST_CREDITS
    #: Fallback for ``meta.rules.weapon_blue_cap`` (RULEBOOK §4.9.8) —
    #: the most blue-worth of ordnance a seat may hold. Unlike the dials
    #: above this is not doctrine and retuning it buys you nothing: the
    #: engine refuses the build regardless. It is here so the policy can
    #: decline gracefully instead of proposing an order it will lose.
    weapon_blue_cap: int = WEAPONISED_BLUE_CAP


#: The shipped economy. Fork-local, so retuning it cannot affect a rival.
# --- weapon-forge hook (installed by forge_install.py) ---
# ECONOMY from weapon_plays.py: buy the cheapest declared weapon as
# soon as it is affordable, and never buy ordnance with no play.
DEFAULT_DIALS = weapon_forge.tune_dials(OrbitDials())


# ── View readers ──────────────────────────────────────────────────
#
# Copied in rather than imported so the fork owns its whole orbit path
# and an attendee can follow it without leaving the directory. These are
# plumbing, not policy — they read the engine's view shape and nothing
# more. Changing them is almost never what you want.


def _my_harvesters(view: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """All harvesters the seat owns, in stable id order."""
    entities = (view.get("entities") or {}).get("mine") or []
    rows = [ent for ent in entities if ent.get("type") == "harvester"]
    rows.sort(key=lambda r: str(r.get("id") or ""))
    return rows


def _seat_of(view: Mapping[str, Any]) -> str:
    """The viewer's seat id, defaulting to ``p1`` on a stripped view."""
    meta = view.get("meta") or {}
    hud = view.get("hud") or {}
    return str(meta.get("player") or hud.get("player") or "p1")


def _seat_day_rng(
    view: Mapping[str, Any], seat: str, salt: str = "",
) -> _random.Random:
    """Seeded RNG for ``(session, seat, day, salt)``.

    Determinism matters here: the same view must replan to the same buy,
    or a transient retry silently changes what the seat owns.
    """
    meta = view.get("meta") or {}
    hud = view.get("hud") or {}
    session_id = str(meta.get("session_id") or "")
    day = int(hud.get("day") or meta.get("day") or 0)
    return _random.Random(f"{session_id}|{seat}|{day}|{salt}")


def _blue_purity_total(view: Mapping[str, Any]) -> int:
    """Rolled-up BLUE the seat is holding — the weapons currency."""
    orbit = view.get("orbit") or {}
    total = orbit.get("blue_purity_total")
    if total is not None:
        try:
            return int(total)
        except (TypeError, ValueError):
            pass
    blue = 0
    for p in orbit.get("hoard_parcels") or []:
        if str(p.get("colour", "")).upper() == "BLUE":
            try:
                blue += int(p.get("purity", 0) or 0)
            except (TypeError, ValueError):
                continue
    return blue


# ── The policy ────────────────────────────────────────────────────


def plan_orbit_actions(
    view: Dict[str, Any],
    *,
    weapons_enabled: bool = True,
    dials: OrbitDials = DEFAULT_DIALS,
) -> Tuple[List[Dict[str, Any]], str]:
    """Plan this seat's orbit submission (RULEBOOK §4).

    Returns ``(actions, rationale)`` — wire-format orbit actions ready for
    ``engine.submit_orbit_actions``, and the prose that lands on the card.

    Pure spending in priority order, with no slot cap: credits and BLUE
    are the only limit.

        1. Repair every damaged harvester — a dead rig earns nothing.
        2. Build a harvester if under the fleet cap and affordable.
        3. Build weapons from surplus BLUE (skipped when disabled).
        4. Top the probe magazine up toward :attr:`OrbitDials.probe_target_stock`.

    Probes come last on purpose. Shipping RED is automatic and free, so
    there is no bid to hold credits back for; probes soak up whatever the
    fleet did not need.

    ``weapons_enabled=False`` is the no-weapons tutorial opponent
    (RED_HARVEST_LITE) — it skips priority 3 and changes nothing else.
    """
    orbit = view.get("orbit") or {}
    credits = int(orbit.get("credits", 0))
    # --- weapon-forge hook (installed by forge_install.py) ---
    if not weapons_enabled:
        try:
            from . import weapon_plays as _wp
            if getattr(_wp, "PLAYS", ()): 
                weapons_enabled = True  # this fork fires weapons
        except Exception:
            pass
    cap_used = int(orbit.get("harvester_cap_used", 0))
    cap_max = int(orbit.get("harvester_cap_max", dials.harvester_cap))
    prices = orbit.get("ship_prices") or {}
    repair_cost = int(prices.get("repair", dials.repair_cost))
    probe_cost = int(prices.get("probe_build", dials.probe_build_cost))
    harvester_cost = int(
        prices.get("harvester_build", dials.harvester_build_cost),
    )

    blue_total = _blue_purity_total(view)
    weapon_stock = orbit.get("weapon_stock") or {}
    emp_stock = int(weapon_stock.get("emp", 0) or 0)
    chaff_stock = int(weapon_stock.get("chaff", 0) or 0)
    weapon_prices = orbit.get("weapon_prices") or {}
    emp_price = weapon_prices.get("emp") or {}
    emp_blue_cost = int(emp_price.get("blue", dials.emp_blue_cost))
    emp_credit_cost = int(emp_price.get("credits", dials.emp_credit_cost))
    chaff_price = weapon_prices.get("chaff") or {}
    chaff_blue_cost = int(chaff_price.get("blue", dials.chaff_blue_cost))
    chaff_credit_cost = int(
        chaff_price.get("credits", dials.chaff_credit_cost),
    )

    actions: List[Dict[str, Any]] = []
    descriptors: List[str] = []
    remaining = credits

    # LEGACY PATH, KEPT ON PURPOSE (v1.30). A new season never reaches
    # here — the simulator settles the terminal orbit itself rather than
    # asking, precisely BECAUSE "nothing worth buying" was the only
    # answer anyone ever had. It still fires for a season persisted
    # mid-final-orbit by a pre-v1.30 build. Delete it only once no such
    # save can exist.
    if bool(orbit.get("final_orbit")):
        return [], (
            "final settlement orbit: RED ships and GREEN clears "
            "automatically — nothing worth buying"
        )

    # Priority 1: repair every damaged harvester.
    for harv in [h for h in _my_harvesters(view) if bool(h.get("damaged"))]:
        if remaining < repair_cost:
            descriptors.append(
                f"deferred repair on {harv.get('id')} (need {repair_cost}c, "
                f"have {remaining}c)",
            )
            continue
        actions.append({"a": "repair", "unit": str(harv.get("id"))})
        remaining -= repair_cost
        descriptors.append(f"repaired {harv.get('id')} ({repair_cost}c)")

    # Priority 2: build a new harvester if under cap and affordable.
    #
    # v19 — RESERVE THE LANDING. A fresh harvester is built INTO ORBIT with no
    # board position, and the active drop mode is `live_only`: it can only land
    # on a cell under live sensor cover. An orbital unit lights nothing, so with
    # no probe in stock and no harvester already down, a rig bought here is
    # STRANDED — 1500c for zero parcels, which is the worst single outcome in
    # the whole policy. The cascade spends one shared wallet in priority order,
    # so the harvester used to be able to eat the probe money that would have
    # landed it.
    #
    # Reserve the price of ONE probe unless we can already land: either probes
    # in stock, or a harvester on the surface whose radius-1 plus is legal
    # drop ground for the newcomer.
    probe_stock_now = int(orbit.get("probe_stock", 0) or 0)
    can_already_land = probe_stock_now > 0 or any(
        h.get("x") is not None for h in _my_harvesters(view)
    )
    landing_reserve = 0 if can_already_land else probe_cost
    if cap_used >= cap_max:
        descriptors.append(
            f"skipped harvester build (fleet at cap {cap_used}/{cap_max})",
        )
    elif remaining >= harvester_cost + landing_reserve:
        actions.append({"a": "build_harvester"})
        remaining -= harvester_cost
        descriptors.append(f"built harvester ({harvester_cost}c)")
    elif landing_reserve and remaining >= harvester_cost:
        descriptors.append(
            f"withheld harvester build ({harvester_cost}c affordable, but "
            f"holding {probe_cost}c for the probe that lands it — no live "
            f"cover, so buying now strands it in orbit)",
        )
    else:
        descriptors.append(
            f"deferred harvester build (need "
            f"{harvester_cost + landing_reserve}c, have {remaining}c)",
        )

    # Priority 3: weapons, tiered on rolled-up BLUE. Chaff leads the
    # always-build band because an empty rack loses the egress jam, and
    # the jam is the cheapest denial in the game.
    # v1.34 — the arsenal ceiling (RULEBOOK §4.9.8). Threaded through the
    # affordability helpers so every branch below inherits it, rather
    # than bolted onto each one. At most one weapon is queued per orbit,
    # so the held figure does not need to move mid-plan.
    weapon_blue_cap = int(
        ((view.get("meta") or {}).get("rules") or {}).get(
            "weapon_blue_cap", dials.weapon_blue_cap
        )
    )
    # v1.38 — sum EVERY kind the game prices, not the two this policy
    # happens to buy. It used to be ``emp_stock * emp + chaff_stock *
    # chaff``, which stopped being the seat's arsenal the moment a third
    # weapon existed: a seat holding two SNAPs read as 0 of 600, so the
    # policy would cheerfully propose a build the engine then refused at
    # the cap — the exact failure the descriptor below exists to avoid.
    # Nothing is bought here that is not already bought below; this is
    # only the arithmetic of what is already held.
    held_weapon_blue = 0
    for kind, price in (weapon_prices or {}).items():
        if not isinstance(price, Mapping):
            continue
        held_weapon_blue += (
            int(weapon_stock.get(kind, 0) or 0) * int(price.get("blue", 0) or 0)
        )

    # v19 — TWO defects fixed here, both exposed by declaring a third weapon.
    #
    # 1. The always-build band was an if/elif CASCADE. Chaff led it, so EMP was
    #    only reached on a night chaff was capped or unaffordable: a three-weapon
    #    rack took THREE separate orbits to fill, and check_wiring's
    #    "orbital can buy emp" failed outright from an empty rack.
    # 2. `held_weapon_blue` and `blue_total` were both read ONCE, on the stated
    #    assumption that at most one weapon is queued per orbit. That assumption
    #    died when the forge procurement hook started queueing a build of its
    #    own. Two builds in one plan against a stale arsenal figure is how a
    #    policy proposes an order the engine then refuses at the 600 ceiling —
    #    the exact silent failure the cap descriptor exists to prevent.
    #
    # Both branches are independent now, and both tallies move as builds queue.
    _queued_blue = [0]

    def _room_for(blue_cost: int) -> bool:
        return (
            held_weapon_blue + _queued_blue[0] + blue_cost <= weapon_blue_cap
        )

    def _afford_emp() -> bool:
        return (
            blue_total - _queued_blue[0] >= emp_blue_cost
            and remaining >= emp_credit_cost
            and _room_for(emp_blue_cost)
        )

    def _afford_chaff() -> bool:
        return (
            blue_total - _queued_blue[0] >= chaff_blue_cost
            and remaining >= chaff_credit_cost
            and _room_for(chaff_blue_cost)
        )

    if weapons_enabled and not _room_for(min(emp_blue_cost, chaff_blue_cost)):
        # Say the cap out loud rather than letting it read as "cannot
        # afford" — an agent at the ceiling with a full wallet is a
        # different situation, and the descriptor is what a fork reads
        # when it wonders why its build never fired.
        descriptors.append(
            f"weapon build skipped (holding {held_weapon_blue} of the "
            f"{weapon_blue_cap} blue arsenal cap)"
        )
    elif weapons_enabled and blue_total > dials.blue_always_build:
        built_any = False
        if chaff_stock < dials.chaff_stockpile_cap and _afford_chaff():
            actions.append({"a": "build_chaff", "count": 1})
            remaining -= chaff_credit_cost
            _queued_blue[0] += chaff_blue_cost
            built_any = True
            descriptors.append(
                f"built CHAFF for egress jam (blue {blue_total} > "
                f"{dials.blue_always_build})"
            )
        if emp_stock < dials.emp_stockpile_cap and _afford_emp():
            actions.append({"a": "build_emp", "count": 1})
            remaining -= emp_credit_cost
            _queued_blue[0] += emp_blue_cost
            built_any = True
            descriptors.append(
                f"built EMP (blue {blue_total} > {dials.blue_always_build})"
            )
        if not built_any:
            descriptors.append(
                f"weapon build wanted (blue {blue_total}) but unaffordable "
                f"or capped (have {remaining}c, holding {held_weapon_blue} "
                f"of {weapon_blue_cap} blue)"
            )
    elif (
        weapons_enabled
        and blue_total > dials.blue_emp_roll
        and emp_stock < dials.emp_stockpile_cap
        and _afford_emp()
    ):
        emp_rng = _seat_day_rng(view, _seat_of(view), salt="emp-build")
        if emp_rng.random() < dials.emp_roll_chance:
            actions.append({"a": "build_emp", "count": 1})
            remaining -= emp_credit_cost
            _queued_blue[0] += emp_blue_cost
            descriptors.append(
                f"built EMP (blue {blue_total} > {dials.blue_emp_roll}, "
                f"50% roll hit)"
            )
        else:
            descriptors.append(
                "skipped EMP build (blue surplus but 50% roll missed)"
            )

    # --- weapon-forge hook (installed by forge_install.py) ---
    # PLACEMENT IS LOAD-BEARING. This must sit with the stock weapon
    # branch (priority 3), BEFORE the probe magazine top-up — probes
    # cost 250c each and a 3-probe batch spends 750c, so a hook placed
    # after them is handed an empty wallet. That is exactly what
    # happened: an EMP agent armed 3 times from the stock branch while
    # a SNAP agent never armed once, reporting 'could not afford it
    # (credits 0/250)' every night with plenty of blue in the bank.
    remaining = weapon_forge.add_procurement(
        actions, descriptors, view, remaining=remaining,
        weapons_enabled=weapons_enabled)

    # Priority 4: top the probe magazine up. A flat "build 2" ran dry and
    # left harvesters unable to hot-drop, so top up toward the target in
    # one batched build, bounded by credits and current stock.
    current_probe_stock = int(orbit.get("probe_stock", 0) or 0)
    want = max(0, dials.probe_target_stock - current_probe_stock)
    affordable = remaining // probe_cost if probe_cost > 0 else 0
    build_n = min(want, affordable)
    if build_n >= 1:
        actions.append({"a": "build_probe", "count": int(build_n)})
        remaining -= build_n * probe_cost
        descriptors.append(
            f"built {build_n} probe(s) ({build_n * probe_cost}c) — "
            f"stock {current_probe_stock}→{current_probe_stock + build_n}"
        )
    elif want <= 0:
        descriptors.append(
            f"probe magazine full (stock {current_probe_stock}≥"
            f"{dials.probe_target_stock})"
        )
    else:
        descriptors.append(
            f"deferred probe build (need {probe_cost}c, have {remaining}c)",
        )

    rationale = (
        f"orbit day plan ({credits}c available): "
        + "; ".join(descriptors)
        + f". Carryover {remaining}c."
    )
    return actions, rationale
