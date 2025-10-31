"""Fallback catalogue of deep markets by sport.

The Odds API exposes per-sport market lists that can be queried at runtime. When
those calls fail (for example because of network issues or quota exhaustion),
this module provides a static mapping of common deep-market keys so users can
continue configuring scans.
"""

from __future__ import annotations

from typing import Dict, List

# Generic markets shared across several sports.
_GENERIC_DEEP_MARKETS = [
    "alternate_spreads",
    "alternate_totals",
    "first_half_spreads",
    "first_half_totals",
    "first_quarter_spreads",
    "first_quarter_totals",
    "second_half_spreads",
    "second_half_totals",
    "team_totals",
]

_BASKETBALL_MARKETS = [
    "player_points",
    "player_rebounds",
    "player_assists",
    "player_points_rebounds_assists",
    "player_threes",
    "player_steals",
    "player_blocks",
    "player_turnovers",
    "player_points_assists",
    "player_points_rebounds",
] + _GENERIC_DEEP_MARKETS

_AMERICAN_FOOTBALL_MARKETS = [
    "player_pass_yards",
    "player_pass_tds",
    "player_rush_yards",
    "player_rush_attempts",
    "player_receiving_yards",
    "player_receptions",
    "player_anytime_td",
    "player_first_td",
    "alternate_spreads",
    "alternate_totals",
    "team_totals",
]

_BASEBALL_MARKETS = [
    "alternate_run_lines",
    "alternate_totals",
    "player_total_bases",
    "player_strikeouts",
    "player_hits",
    "player_runs",
    "player_rbis",
    "player_hits_runs_rbis",
]

_HOCKEY_MARKETS = [
    "alternate_puck_lines",
    "alternate_totals",
    "player_points",
    "player_assists",
    "player_goals",
    "player_shots_on_goal",
    "player_power_play_points",
    "team_totals",
]

_SOCCER_MARKETS = [
    "both_teams_to_score",
    "double_chance",
    "draw_no_bet",
    "correct_score",
    "asian_handicap",
    "team_totals",
    "first_half_result",
    "total_goals",
]

_TENNIS_MARKETS = [
    "set_betting",
    "correct_score",
    "total_sets",
    "total_games",
    "handicap_games",
    "first_set_winner",
]

_GOLF_MARKETS = [
    "tournament_winner",
    "top_5_finish",
    "top_10_finish",
    "matchups",
]

_FIGHTING_MARKETS = [
    "winning_method",
    "fight_goes_distance",
    "round_totals",
]

_ESPORTS_MARKETS = [
    "match_correct_score",
    "map_handicap",
    "map_totals",
]

_DEEP_MARKET_MAP: Dict[str, List[str]] = {
    "americanfootball": _AMERICAN_FOOTBALL_MARKETS,
    "baseball": _BASEBALL_MARKETS,
    "basketball": _BASKETBALL_MARKETS,
    "icehockey": _HOCKEY_MARKETS,
    "soccer": _SOCCER_MARKETS,
    "tennis": _TENNIS_MARKETS,
    "golf": _GOLF_MARKETS,
    "mma": _FIGHTING_MARKETS,
    "boxing": _FIGHTING_MARKETS,
    "esports": _ESPORTS_MARKETS,
}


def get_deep_markets_for_sport(sport_key: str) -> List[str]:
    """Return a list of fallback deep markets for the given sport."""

    if not sport_key:
        return []
    if sport_key in _DEEP_MARKET_MAP:
        return list(_DEEP_MARKET_MAP[sport_key])
    prefix = sport_key.split("_", 1)[0]
    if prefix in _DEEP_MARKET_MAP:
        return list(_DEEP_MARKET_MAP[prefix])
    return list(_GENERIC_DEEP_MARKETS)
