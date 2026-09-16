"""weapon_plays — YOUR agent's weapon moves. This is the only file you edit.

Everything else was installed once by ``forge_install.py``. To add a weapon or
a move, add a ``WeaponPlay`` below. Nothing else in the harness needs touching:
the menu group, the wire move, the replay tag, the doctrine and the rationale
are all derived from what you write here.

Each move is four decisions:

  WHEN           always | redsign_mine | redsign_theirs | other
                 The board condition. ``redsign_mine`` = a pure WE found is
                 live (we are defending it). ``redsign_theirs`` = a rival
                 found it (we are attacking it).

  HOUR           super_early (H1) | early (H1-2) | mid | late | last_night
                 Position in the move list IS the hour, so this is a hard
                 constraint. An 8h EMP cloud past H2 has no night left to use;
                 a chaff has to land on the hour they were going to act.

  COMBINES_WITH  smash_grab | blind_grab | probe | chain | standalone
                 Which existing play this borrows geometry from, so the option
                 has real coordinates rather than invented ones.

  WHY            One sentence: what firing this BUYS. Yours, in your words.
                 The full rationale the model reads is composed from this plus
                 the weapon's mechanics plus the alternative it beats — that
                 last part depends on what else is on tonight's menu, which is
                 why the machinery adds it rather than you.

Name the move whatever you like. It is public: it shows up in the game log as
the night resolves, in the lab's frozen-turn journals and in the season cards.
Be as silly as you like about the TONE and never about the CONTENT — calling a
cautious vision move ``NUKE`` tells the model that option is aggressive, and
that is a bug you will spend an hour not finding.

Check yourself any time with:

    python skills/soc-agent-forge/scripts/check_wiring.py <your_label>
"""

from __future__ import annotations

from typing import Tuple

from .weapon_forge import EconomyPolicy, WeaponPlay


# ── how the weapons get PAID FOR ──────────────────────────────────────────
# The defaults are the conservative reading and are right for most teams:
# fund what you fire, never buy ordnance you have no play for, and never pull
# your last harvester off red to fetch currency.
#
#   soc will buy the cheapest weapon you declared the moment it can afford it,
#   set the stockpile cap to 0 for any weapon you did NOT declare, and ask for
#   blue on any night your rack cannot fire.
#
# Change something only if you mean it. `hold_at={"chaff": 1}` caps the rack at
# one; `seek_blue_when_rack_empty=False` reverts to the baseline's behaviour of
# only topping up when the VAULT is short.
# Tuned from an 18-season soak vs tabula_v12 (reports/soak/ 10, reports/soak2/ 8).
#   * Credits, not hours, were the binding constraint. Every season deferred a
#     harvester ("need 1500c, have 1250c") - short by exactly one never-fired
#     charge - and the fleet never reached its 3-harvester cap while the
#     15-parcel vault was never filled. So cap the rack at ONE of each.
#   * seek_blue_always was harmful. Blue never scores, and chasing it burned
#     whole outings (one night banked +0 red doing a blue grab; another spent a
#     final-night harvester on blue, worth a guaranteed 0). Back to the default:
#     seek blue only when the rack cannot fire.
#
# CHAFF IS BACK, and the reason it was dropped was WRONG. The old note here read
# "at 300 blue it puts emp on the 600 cap boundary so emp could never arm". The
# engine refuses a build only when it would go OVER the cap:
#
#     if held_blue + blue_needed > cap:   # session.py, _apply_build_weapon
#
# so 100 + 200 + 300 = 600 is legal - `600 > 600` is False. What actually broke
# the rack was holding TWO of each (400 + 200 = 600) and then asking for chaff on
# top. One of each fits EXACTLY, with ZERO headroom: any surplus charge silently
# fails the next build. That is the failure mode to watch in check_wiring.
#
# Chaff also earns its slot on price ALONE: 300 blue and **0 CREDITS**. Snap and
# emp each cost 250 credits - which is roughly the sum every season was short by
# when it deferred the 3rd harvester. Chaff is the only weapon that does not
# compete with the fleet.
ECONOMY = EconomyPolicy(hold_at={"emp": 1, "snap": 1, "chaff": 1})


# ── DOCTRINE: hit the GROUND or hit the CLOCK. Never hit the EYES. ────────
#
# The 18-season soak fired 16 shots. THIRTEEN of them were aimed at rival
# probes (NIGHTFALL 12, BLIND_THE_FINDER 1) and produced ZERO recorded rival
# loss, plus one friendly-fire night that cost ~500 red. That was not bad
# tuning. It was structurally impossible, and the engine says why:
#
#   _harvest_at() has NO visibility check. Its only gate is the tile colour.
#   Only the INITIAL LANDING is gated on live vision (RULEBOOK 3.9.7).
#
# So a rival who has ALREADY SEEN a pure harvests it in total darkness. Blinding
# him takes nothing away, and a dead probe is re-bought for 250c - the cards show
# him relaunching three fresh eyes within hours of our strike. Anti-eye plays are
# deleted and must not come back.
#
# What DOES bite:
#   GROUND - snap resolves ABOVE the vision snapshot, so it is the only weapon
#            that can refuse a landing TONIGHT. emp resolves BELOW it, so it
#            cannot stop tonight's committed drop but seals the next 8 hours.
#   CLOCK  - chaff cancels every seat's hour, OURS INCLUDED (launcher is immune
#            for hour N only, then self-jammed for the carry-over). 3 slots each,
#            so it is a NEUTRAL trade until our own hours are worthless - and a
#            harvester gets ONE OUTING PER NIGHT, so once our tours are home our
#            late hours are worth nothing and his are worth a full outing.
#
# One weapon per information state:
#   a rival lit a pure  -> GROUND: emp his seam, snap the contested cell
#   any night at all    -> CLOCK: chaff his hour ONE, the richest hour he has
#
# CHAFF FIRES AT HOUR ONE, not late. The first draft of this file fired it at
# hour 16 on the theory that our own late hours are worthless once our tours are
# home. They are - but so are HIS. A harvester gets one outing per night and both
# houses front-load, so a flare at H16 very likely cancels nothing at all. At H1
# it cancels his opening drop, which is the hour a smash-and-grab takes a pure,
# and the 3h window leaves him no retry inside it. The forge's own composed
# rationale says the same thing and it was right: we are immune at H1 (launching
# IS the move), self-jammed H2-H3, free from H4 with most of the night left.
#
# menu_rank is ASCENDING - lower shows FIRST. All four plays used to sit at 0,
# so their order was declaration order, i.e. luck. They are now ranked by
# MEASURED value, because ranking is mechanical and prose is not: the doctrine
# below was already in the file and the model talked past it in 5 seasons of 8.
PLAYS: Tuple[WeaponPlay, ...] = (
    WeaponPlay(
        play_id="PURE_TRAP",
        weapon="snap",
        menu_rank=10,          # the ONLY play with a proven kill: 1 shot, +765
        when="always",
        hour="super_early",
        targets="contested_pure",
        min_targets=1,
        combines_with="smash_grab",
        why=(
            "a high-value red we can see that a rival probe also watches is the "
            "one cell whose occupation is predictable \u2014 they smash-and-grab "
            "it at hour one; snapping it refuses that landing and damages the "
            "hull, then a smash-grab lands on the cold cell at hour two and "
            "banks it \u2014 up to 765 points denied to them is worth exactly "
            "765 banked by us"
        ),
    ),
    WeaponPlay(
        play_id="LIGHTS_DOWN",
        weapon="emp",
        menu_rank=20,
        when="redsign_theirs",
        hour="super_early",
        targets="redsign",
        min_targets=1,
        probe_the_comb=True,
        take_the_ground=True,
        combines_with="blind_grab",
        why=(
            "covering their smear at H1 locks them out of their own pure for "
            "eight hours; then we comb the ground they cannot reach \u2014 the "
            "exposed edge now, or the interior once our own cloud clears. "
            "Offered in season 8 with the charge in the rack and declined: the "
            "rival banked that pure for 765 and wrote it down. Do not decline it"
        ),
    ),
    WeaponPlay(
        play_id="TEMPO_THEFT",
        weapon="chaff",
        menu_rank=30,
        when="always",
        hour="super_early",
        targets="pattern",
        min_targets=1,
        combines_with="standalone",
        why=(
            "cancelling hour one takes their opening drop \u2014 the single "
            "richest hour of their night, when a smash-and-grab lands on a pure "
            "\u2014 and the three-hour window gives them no retry inside it; we "
            "are immune at H1 because launching IS our move, self-jammed at H2 "
            "and H3, and free from H4 with most of the night still ahead, so "
            "plan nothing in H2-H3 and walk in after them. It costs no credits, "
            "so unlike snap or emp it never delays the third harvester"
        ),
    ),
)
