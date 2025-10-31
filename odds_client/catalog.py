"""Static catalog data for The Odds API.

The live Odds API surfaces the authoritative list of sports and bookmakers, but
the application benefits from having a baked-in catalogue so users can make
selections even when the API request fails (for example, during validation or
when a sport is out of season).  The lists below mirror the data published in
https://the-odds-api.com/ and are kept in alphabetical order within each
category to make maintenance straightforward.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Sequence


@dataclass(frozen=True)
class SportInfo:
    """Description of an Odds API sport."""

    key: str
    title: str
    group: str


@dataclass(frozen=True)
class BookmakerInfo:
    """Description of an Odds API bookmaker entry."""

    key: str
    title: str
    regions: Sequence[str]


# NOTE: Keep this list sorted first by group, then by sport key.
ALL_SPORTS: List[SportInfo] = [
    # American football
    SportInfo("americanfootball_cfl", "Canadian Football League", "American Football"),
    SportInfo("americanfootball_ncaaf", "NCAA Football", "American Football"),
    SportInfo("americanfootball_nfl", "NFL", "American Football"),
    SportInfo("americanfootball_ufl", "United Football League", "American Football"),
    SportInfo("americanfootball_xfl", "XFL", "American Football"),
    # Australian rules
    SportInfo("australianfootball_afl", "AFL", "Australian Rules"),
    # Baseball
    SportInfo("baseball_kbo", "KBO", "Baseball"),
    SportInfo("baseball_mlb", "MLB", "Baseball"),
    SportInfo("baseball_npb", "NPB", "Baseball"),
    SportInfo("baseball_us_college", "NCAA Baseball", "Baseball"),
    # Basketball
    SportInfo("basketball_euroleague", "EuroLeague", "Basketball"),
    SportInfo("basketball_fiba", "FIBA International", "Basketball"),
    SportInfo("basketball_nba", "NBA", "Basketball"),
    SportInfo("basketball_ncaab", "NCAA Basketball", "Basketball"),
    SportInfo("basketball_nbl", "Australian NBL", "Basketball"),
    SportInfo("basketball_wnba", "WNBA", "Basketball"),
    # Boxing & MMA
    SportInfo("boxing_professional", "Professional Boxing", "Fighting"),
    SportInfo("mma_mixed_martial_arts", "Mixed Martial Arts", "Fighting"),
    # Cricket
    SportInfo("cricket_big_bash", "Big Bash League", "Cricket"),
    SportInfo("cricket_caribbean_premier_league", "Caribbean Premier League", "Cricket"),
    SportInfo("cricket_indian_premier_league", "Indian Premier League", "Cricket"),
    SportInfo("cricket_one_day_international", "One Day Internationals", "Cricket"),
    SportInfo("cricket_psl", "Pakistan Super League", "Cricket"),
    SportInfo("cricket_super_smash", "Super Smash", "Cricket"),
    SportInfo("cricket_test_match", "Test Matches", "Cricket"),
    SportInfo("cricket_the_hundred_men", "The Hundred (Men)", "Cricket"),
    SportInfo("cricket_the_hundred_women", "The Hundred (Women)", "Cricket"),
    SportInfo("cricket_t20_blast", "Vitality T20 Blast", "Cricket"),
    SportInfo("cricket_t20_international", "Twenty20 Internationals", "Cricket"),
    SportInfo("cricket_wbbl", "Women's Big Bash League", "Cricket"),
    # Darts
    SportInfo("darts_pdc", "PDC", "Darts"),
    # Esports
    SportInfo("esports_call_of_duty", "Call of Duty", "Esports"),
    SportInfo("esports_csgo", "Counter-Strike: Global Offensive", "Esports"),
    SportInfo("esports_dota2", "Dota 2", "Esports"),
    SportInfo("esports_league_of_legends", "League of Legends", "Esports"),
    SportInfo("esports_overwatch", "Overwatch", "Esports"),
    SportInfo("esports_rainbow_six", "Rainbow Six", "Esports"),
    SportInfo("esports_starcraft2", "StarCraft II", "Esports"),
    SportInfo("esports_valorant", "Valorant", "Esports"),
    # Golf
    SportInfo("golf_lpga", "LPGA Tour", "Golf"),
    SportInfo("golf_pga", "PGA Tour", "Golf"),
    SportInfo("golf_european_tour", "DP World Tour", "Golf"),
    SportInfo("golf_ryder_cup", "Ryder Cup", "Golf"),
    SportInfo("golf_masters_tournament", "Masters Tournament", "Golf"),
    SportInfo("golf_pga_championship", "PGA Championship", "Golf"),
    SportInfo("golf_the_open_championship", "The Open Championship", "Golf"),
    SportInfo("golf_us_open", "US Open", "Golf"),
    # Ice hockey
    SportInfo("icehockey_finnish_liiga", "Liiga", "Ice Hockey"),
    SportInfo("icehockey_nhl", "NHL", "Ice Hockey"),
    SportInfo("icehockey_russia_khl", "KHL", "Ice Hockey"),
    SportInfo("icehockey_sweden_allsvenskan", "HockeyAllsvenskan", "Ice Hockey"),
    SportInfo("icehockey_sweden_shl", "SHL", "Ice Hockey"),
    # Motorsport
    SportInfo("motorsport_formula_one", "Formula 1", "Motorsport"),
    SportInfo("motorsport_indycar", "IndyCar", "Motorsport"),
    SportInfo("motorsport_motogp", "MotoGP", "Motorsport"),
    SportInfo("motorsport_nascar", "NASCAR", "Motorsport"),
    SportInfo("motorsport_supercars", "Supercars Championship", "Motorsport"),
    # Rugby
    SportInfo("rugby_league_nrl", "NRL", "Rugby League"),
    SportInfo("rugby_league_super_league", "Super League", "Rugby League"),
    SportInfo("rugby_union_champions_cup", "Champions Cup", "Rugby Union"),
    SportInfo("rugby_union_gallagher_premiership", "Gallagher Premiership", "Rugby Union"),
    SportInfo("rugby_union_international", "International Tests", "Rugby Union"),
    SportInfo("rugby_union_npc", "NPC", "Rugby Union"),
    SportInfo("rugby_union_six_nations", "Six Nations", "Rugby Union"),
    SportInfo("rugby_union_super_rugby", "Super Rugby", "Rugby Union"),
    SportInfo("rugby_union_united_rugby_championship", "United Rugby Championship", "Rugby Union"),
    # Snooker
    SportInfo("snooker_world_championship", "World Snooker Championship", "Snooker"),
    # Soccer (Football)
    SportInfo("soccer_africa_cup_of_nations", "Africa Cup of Nations", "Soccer"),
    SportInfo("soccer_argentina_primera_division", "Argentina Primera División", "Soccer"),
    SportInfo("soccer_australia_aleague", "A-League", "Soccer"),
    SportInfo("soccer_belgium_first_div", "Belgian First Division A", "Soccer"),
    SportInfo("soccer_brazil_campeonato", "Brazil Série A", "Soccer"),
    SportInfo("soccer_china_superleague", "Chinese Super League", "Soccer"),
    SportInfo("soccer_denmark_superliga", "Danish Superliga", "Soccer"),
    SportInfo("soccer_efl_championship", "EFL Championship", "Soccer"),
    SportInfo("soccer_england_league1", "EFL League One", "Soccer"),
    SportInfo("soccer_england_league2", "EFL League Two", "Soccer"),
    SportInfo("soccer_epl", "English Premier League", "Soccer"),
    SportInfo("soccer_fa_cup", "FA Cup", "Soccer"),
    SportInfo("soccer_fifa_world_cup", "FIFA World Cup", "Soccer"),
    SportInfo("soccer_france_ligue_one", "Ligue 1", "Soccer"),
    SportInfo("soccer_france_ligue_two", "Ligue 2", "Soccer"),
    SportInfo("soccer_germany_bundesliga", "Bundesliga", "Soccer"),
    SportInfo("soccer_germany_bundesliga2", "2. Bundesliga", "Soccer"),
    SportInfo("soccer_germany_dfb_pokal", "DFB-Pokal", "Soccer"),
    SportInfo("soccer_germany_liga3", "3. Liga", "Soccer"),
    SportInfo("soccer_greece_super_league", "Greek Super League", "Soccer"),
    SportInfo("soccer_italy_serie_a", "Serie A", "Soccer"),
    SportInfo("soccer_italy_serie_b", "Serie B", "Soccer"),
    SportInfo("soccer_japan_j_league", "J1 League", "Soccer"),
    SportInfo("soccer_korea_kleague1", "K League 1", "Soccer"),
    SportInfo("soccer_league_of_ireland", "League of Ireland Premier", "Soccer"),
    SportInfo("soccer_mls", "Major League Soccer", "Soccer"),
    SportInfo("soccer_netherlands_eredivisie", "Eredivisie", "Soccer"),
    SportInfo("soccer_norway_eliteserien", "Eliteserien", "Soccer"),
    SportInfo("soccer_poland_ekstraklasa", "Ekstraklasa", "Soccer"),
    SportInfo("soccer_portugal_primeira_liga", "Primeira Liga", "Soccer"),
    SportInfo("soccer_scotland_championship", "Scottish Championship", "Soccer"),
    SportInfo("soccer_scotland_premiership", "Scottish Premiership", "Soccer"),
    SportInfo("soccer_spain_la_liga", "La Liga", "Soccer"),
    SportInfo("soccer_spain_segunda_division", "Segunda División", "Soccer"),
    SportInfo("soccer_sweden_allsvenskan", "Allsvenskan", "Soccer"),
    SportInfo("soccer_sweden_superettan", "Superettan", "Soccer"),
    SportInfo("soccer_switzerland_superleague", "Swiss Super League", "Soccer"),
    SportInfo("soccer_turkey_super_lig", "Süper Lig", "Soccer"),
    SportInfo("soccer_uefa_champions_league", "UEFA Champions League", "Soccer"),
    SportInfo("soccer_uefa_europa_conference_league", "UEFA Conference League", "Soccer"),
    SportInfo("soccer_uefa_europa_league", "UEFA Europa League", "Soccer"),
    SportInfo("soccer_uefa_nations_league", "UEFA Nations League", "Soccer"),
    SportInfo("soccer_world_cup_women", "FIFA Women's World Cup", "Soccer"),
    # Table tennis
    SportInfo("tabletennis_international", "International Table Tennis", "Table Tennis"),
    # Tennis
    SportInfo("tennis_atp", "ATP Tour", "Tennis"),
    SportInfo("tennis_atp_challenger", "ATP Challenger", "Tennis"),
    SportInfo("tennis_atp_french_open", "ATP French Open", "Tennis"),
    SportInfo("tennis_atp_us_open", "ATP US Open", "Tennis"),
    SportInfo("tennis_atp_wimbledon", "ATP Wimbledon", "Tennis"),
    SportInfo("tennis_atp_aus_open", "ATP Australian Open", "Tennis"),
    SportInfo("tennis_davis_cup", "Davis Cup", "Tennis"),
    SportInfo("tennis_itf_men", "ITF Men", "Tennis"),
    SportInfo("tennis_itf_women", "ITF Women", "Tennis"),
    SportInfo("tennis_olympics", "Olympic Tennis", "Tennis"),
    SportInfo("tennis_wta", "WTA Tour", "Tennis"),
    SportInfo("tennis_wta_challenger", "WTA 125", "Tennis"),
    SportInfo("tennis_wta_french_open", "WTA French Open", "Tennis"),
    SportInfo("tennis_wta_us_open", "WTA US Open", "Tennis"),
    SportInfo("tennis_wta_wimbledon", "WTA Wimbledon", "Tennis"),
    SportInfo("tennis_wta_aus_open", "WTA Australian Open", "Tennis"),
]


# NOTE: Keep bookmaker entries sorted alphabetically by key.
ALL_BOOKMAKERS: List[BookmakerInfo] = [
    BookmakerInfo("atswins", "ATSwins", ("us",)),
    BookmakerInfo("ballybet", "Bally Bet", ("us",)),
    BookmakerInfo("barstool", "Barstool Sportsbook", ("us",)),
    BookmakerInfo("bet365", "bet365", ("uk", "us", "au", "eu")),
    BookmakerInfo("betfred", "Betfred", ("uk", "us")),
    BookmakerInfo("betmgm", "BetMGM", ("us",)),
    BookmakerInfo("betparx", "BetParx", ("us",)),
    BookmakerInfo("betpoint", "Betpoint", ("eu",)),
    BookmakerInfo("betrivers", "BetRivers", ("us", "ca")),
    BookmakerInfo("betsafe", "Betsafe", ("eu")),
    BookmakerInfo("betsson", "Betsson", ("eu")),
    BookmakerInfo("betstar", "Betstar", ("au")),
    BookmakerInfo("betus", "BetUS", ("us")),
    BookmakerInfo("bovada", "Bovada", ("us")),
    BookmakerInfo("caesars", "Caesars", ("us")),
    BookmakerInfo("circasports", "Circa Sports", ("us")),
    BookmakerInfo("cloudbet", "Cloudbet", ("uk", "eu")),
    BookmakerInfo("coolbet", "Coolbet", ("eu")),
    BookmakerInfo("dafabet", "Dafabet", ("uk", "eu")),
    BookmakerInfo("draftkings", "DraftKings", ("us", "ca")),
    BookmakerInfo("espnbet", "ESPN BET", ("us",)),
    BookmakerInfo("fanduel", "FanDuel", ("us", "uk", "ca")),
    BookmakerInfo("foxbet", "FOX Bet", ("us")),
    BookmakerInfo("ladbrokes", "Ladbrokes", ("uk", "au")),
    BookmakerInfo("lowvig", "LowVig", ("us")),
    BookmakerInfo("neds", "Neds", ("au")),
    BookmakerInfo("northstarbets", "NorthStar Bets", ("ca")),
    BookmakerInfo("pinnacle", "Pinnacle", ("uk", "eu")),
    BookmakerInfo("playup", "PlayUp", ("us", "au")),
    BookmakerInfo("pointsbetau", "PointsBet AU", ("au")),
    BookmakerInfo("pointsbetus", "PointsBet US", ("us")),
    BookmakerInfo("sugarhouse", "SugarHouse", ("us")),
    BookmakerInfo("superbook", "SuperBook", ("us")),
    BookmakerInfo("tab", "TAB", ("au")),
    BookmakerInfo("twinspires", "TwinSpires", ("us")),
    BookmakerInfo("unibet_eu", "Unibet EU", ("eu")),
    BookmakerInfo("unibet_us", "Unibet US", ("us")),
    BookmakerInfo("unibet_uk", "Unibet UK", ("uk")),
    BookmakerInfo("williamhill_au", "William Hill AU", ("au")),
    BookmakerInfo("williamhill_uk", "William Hill UK", ("uk")),
    BookmakerInfo("williamhill_us", "William Hill US", ("us")),
    BookmakerInfo("wynnbet", "WynnBET", ("us")),
]


def filter_bookmakers_by_regions(regions: Iterable[str]) -> List[BookmakerInfo]:
    """Return bookmakers that service any of the provided regions."""

    region_set = {region.lower() for region in regions}
    if not region_set:
        return ALL_BOOKMAKERS
    return [
        bookmaker
        for bookmaker in ALL_BOOKMAKERS
        if any(region in region_set for region in bookmaker.regions)
    ]

