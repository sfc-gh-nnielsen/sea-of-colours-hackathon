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
# seek_blue_always: ask for blue every night regardless of vault state,
# not only when the rack is empty — keeps all three weapons funded.
# buy_asap: drop the build threshold to just under the cheapest declared
# weapon so ordnance is purchased the turn it becomes affordable.
ECONOMY = EconomyPolicy(seek_blue_always=True, buy_asap=True)


PLAYS: Tuple[WeaponPlay, ...] = (
    WeaponPlay(
        play_id="BLACKOUT",
        weapon="emp",
        when="redsign_theirs",
        hour="super_early",
        targets="rival_probes",
        min_targets=1,
        combines_with="standalone",
        why=(
            "a rival that has just lit a pure is about to land on it, so "
            "blinding their probe cover at H1 refuses that landing for the "
            "full night and leaves the seam dark for us to approach"
        ),
    ),
    WeaponPlay(
        play_id="LOCKDOWN",
        weapon="chaff",
        when="redsign_theirs",
        hour="super_early",
        combines_with="blind_grab",
        why=(
            "cancelling their committed H1 resets their whole plan for the "
            "night and leaves us free to work mid-value seams unopposed "
            "while they replan from scratch"
        ),
    ),
    WeaponPlay(
        play_id="POKE",
        weapon="snap",
        when="always",
        hour="early",
        targets="rival_probes",
        min_targets=1,
        combines_with="standalone",
        why=(
            "killing the single eye lighting their best cell costs 100 blue "
            "and costs them the landing cover they built — cheap and repeatable"
        ),
    ),
)
