from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.session import get_db
from app.models import (
    Appearance,
    Base,
    Competition,
    Country,
    Formation,
    FormationPosition,
    Manager,
    Match,
    MatchIncident,
    MatchSyncState,
    MatchTeam,
    MissingPlayer,
    Player,
    PlayerMatchStat,
    Referee,
    Region,
    Season,
    Stage,
    StatType,
    Team,
    TeamMatchStat,
    Venue,
)
from app.services import football_queries as q
from main import app

BERLIN = ZoneInfo("Europe/Berlin")

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)

IDS: dict[str, int] = {}


def _ko(month: int, day: int, hour: int = 15, minute: int = 30) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=BERLIN)


def seed_db(db: Session) -> None:
    region = Region(ws_region_id=81, name="Germany")
    germany = Country(name="Germany", code="GER")
    db.add_all([region, germany])
    db.flush()

    bl = Competition(
        ws_tournament_id=3, region_id=region.id, league_key="GER-Bundesliga",
        name="Bundesliga", slug="bundesliga", format="league",
    )
    pokal = Competition(
        ws_tournament_id=24, region_id=region.id, league_key="GER-DFB-Pokal",
        name="DFB-Pokal", slug="dfb-pokal", format="cup",
    )
    db.add_all([bl, pokal])
    db.flush()

    s2526 = Season(competition_id=bl.id, ws_season_id=1001, code="2526")
    s2627 = Season(competition_id=bl.id, ws_season_id=1002, code="2627")
    s_pokal = Season(competition_id=pokal.id, ws_season_id=2001, code="2627")
    db.add_all([s2526, s2627, s_pokal])
    db.flush()

    st_old = Stage(season_id=s2526.id, ws_stage_id=11, name="Hauptrunde", is_default=True)
    st_main = Stage(season_id=s2627.id, ws_stage_id=12, name="Hauptrunde", is_default=True)
    st_extra = Stage(season_id=s2627.id, ws_stage_id=13, name="Relegation", is_default=False)
    st_pokal = Stage(season_id=s_pokal.id, ws_stage_id=21, name="Runde 1", is_default=True)
    db.add_all([st_old, st_main, st_extra, st_pokal])

    # Namen bewusst so gewählt, dass der Namens-Fallback beim Gleichstand "falsch" läge.
    zeta = Team(ws_team_id=1, name="Zeta", country_id=germany.id)
    alpha = Team(ws_team_id=2, name="Alpha", country_id=germany.id)
    charlie = Team(ws_team_id=3, name="Charlie")
    delta = Team(ws_team_id=4, name="Delta")
    echo = Team(ws_team_id=5, name="Echo")
    db.add_all([zeta, alpha, charlie, delta, echo])
    db.flush()

    venue = Venue(name="Testarena")
    ref = Referee(ws_official_id=77, first_name="Max", last_name="Muster", name="Max Muster")
    db.add_all([venue, ref])
    db.flush()

    def mk(ws_id, stage, home, away, ko, status="finished", hs=None, as_=None, **extra):
        m = Match(
            ws_match_id=ws_id, stage_id=stage.id, home_team_id=home.id, away_team_id=away.id,
            kickoff_time=ko, status=status, home_score=hs, away_score=as_, **extra,
        )
        db.add(m)
        db.flush()
        return m

    m1 = mk(
        9001, st_main, zeta, alpha, _ko(8, 22), hs=1, as_=0, ht_home_score=1, ht_away_score=0,
        venue_id=venue.id, referee_id=ref.id, attendance=40000,
        started_at=_ko(8, 22), first_half_ended_at=_ko(8, 22, 16, 18),
        second_half_started_at=_ko(8, 22, 16, 33),
    )
    m2 = mk(9002, st_main, charlie, zeta, _ko(8, 29), hs=1, as_=0)
    m3 = mk(9003, st_main, alpha, delta, _ko(9, 5), hs=1, as_=0)
    m4 = mk(9004, st_main, delta, echo, _ko(9, 12), status="scheduled")
    m5 = mk(9005, st_extra, delta, charlie, _ko(9, 13), hs=5, as_=0)
    m_old = mk(9006, st_old, charlie, alpha, datetime(2025, 8, 30, 15, 30, tzinfo=BERLIN), hs=2, as_=2)
    m_cup = mk(9007, st_pokal, charlie, delta, _ko(8, 15), hs=3, as_=0, pen_home_score=None)

    # Spieler
    names = ["Z Keeper", "Z Bank", "A Stuermer", "Z Stuermer", "D Verteidiger"]
    players = [Player(ws_player_id=100 + i, name=n) for i, n in enumerate(names)]
    db.add_all(players)
    db.flush()
    z_keeper, z_bank, a_striker, z_striker, d_def = players

    coach = Manager(name="Coach Z")
    db.add(coach)
    db.flush()
    db.add_all([
        MatchTeam(match_id=m1.id, team_id=zeta.id, manager_id=coach.id, average_age=26.5),
        MatchTeam(match_id=m1.id, team_id=alpha.id),
    ])

    app_z1 = Appearance(
        match_id=m1.id, team_id=zeta.id, player_id=z_keeper.id, shirt_no=1, position="GK",
        is_first_eleven=True, is_man_of_the_match=True, age=30, rating=7.1,
    )
    app_z2 = Appearance(
        match_id=m1.id, team_id=zeta.id, player_id=z_bank.id, shirt_no=12, position="Sub",
        is_first_eleven=False, rating=6.5, subbed_in_minute=60,
    )
    app_a1 = Appearance(
        match_id=m1.id, team_id=alpha.id, player_id=a_striker.id, shirt_no=9, position="FW",
        is_first_eleven=True, age=24, rating=6.0, subbed_out_minute=70,
    )
    app_z3 = Appearance(
        match_id=m1.id, team_id=zeta.id, player_id=z_striker.id, shirt_no=10, position="FW",
        is_first_eleven=True, age=22,
    )
    db.add_all([app_z1, app_z2, app_a1, app_z3])
    db.flush()

    shots = StatType(key="shotsTotal")
    passes = StatType(key="passesAccurate")
    db.add_all([shots, passes])
    db.flush()
    db.add_all([
        TeamMatchStat(match_id=m1.id, team_id=zeta.id, stat_type_id=shots.id, value=12),
        TeamMatchStat(match_id=m1.id, team_id=zeta.id, stat_type_id=passes.id, value=300),
        TeamMatchStat(match_id=m1.id, team_id=alpha.id, stat_type_id=shots.id, value=8),
        PlayerMatchStat(appearance_id=app_z1.id, stat_type_id=shots.id, value=3),
        PlayerMatchStat(appearance_id=app_z1.id, stat_type_id=passes.id, value=25),
    ])

    f_z = Formation(
        match_id=m1.id, team_id=zeta.id, start_minute=0, end_minute=59, period=1,
        name="4-4-2", captain_player_id=z_keeper.id,
    )
    f_a = Formation(match_id=m1.id, team_id=alpha.id, start_minute=0, name="4-3-3")
    db.add_all([f_z, f_a])
    db.flush()
    db.add_all([
        FormationPosition(formation_id=f_z.id, slot=1, player_id=z_keeper.id, vertical=0.0, horizontal=5.0),
        FormationPosition(formation_id=f_z.id, slot=2, player_id=z_striker.id, vertical=8.0, horizontal=4.0),
    ])

    db.add_all([
        MatchIncident(
            match_id=m1.id, team_id=zeta.id, ws_event_id=1, type="goal", minute=46,
            expanded_minute=47, period="FirstHalf", player_id=z_striker.id, related_player_id=z_keeper.id,
        ),
        MatchIncident(
            match_id=m1.id, team_id=alpha.id, ws_event_id=2, type="card", card_type="yellow",
            minute=59, expanded_minute=60, period="SecondHalf", player_id=a_striker.id,
        ),
        # Eigentor: team_id = Team des Torschützen (Zeta) -> Tor zählt für Charlie
        MatchIncident(
            match_id=m2.id, team_id=zeta.id, ws_event_id=3, type="own_goal", minute=70,
            expanded_minute=71, period="SecondHalf", player_id=z_bank.id,
        ),
    ])

    db.add(MatchSyncState(match_id=m1.id, attempts=2, last_error=None, details_final_at=_ko(8, 23)))
    db.add_all([
        MissingPlayer(team_id=alpha.id, player_id=a_striker.id, match_id=m4.id, reason="injured", status="Out"),
        MissingPlayer(team_id=delta.id, player_id=d_def.id, reason="suspended", status="Doubtful"),
        MissingPlayer(team_id=zeta.id, player_id=z_bank.id, reason="unfit", status="Out"),
    ])
    db.commit()

    IDS.update(
        m1=m1.id, m2=m2.id, m3=m3.id, m4=m4.id, m5=m5.id, m_old=m_old.id, m_cup=m_cup.id,
        zeta=zeta.id, alpha=alpha.id, charlie=charlie.id, delta=delta.id, echo=echo.id,
        s2627=s2627.id, z_keeper=z_keeper.id, z_striker=z_striker.id,
        a_striker=a_striker.id, z_bank=z_bank.id,
    )


@pytest.fixture(scope="module")
def client():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    seed_db(db)
    db.close()

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


API = "/api/v1/football"


# ── format_minute ────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "minute, period, expected",
    [
        (0, "FirstHalf", "1"),
        (43, "FirstHalf", "44"),
        (44, "FirstHalf", "45"),
        (45, "FirstHalf", "45+1"),
        (47, "FirstHalf", "45+3"),
        (45, "SecondHalf", "46"),
        (89, "SecondHalf", "90"),
        (90, "SecondHalf", "90+1"),
        (93, "SecondHalf", "90+4"),
        (104, "FirstPeriodOfExtraTime", "105"),
        (105, "FirstPeriodOfExtraTime", "105+1"),
        (119, "SecondPeriodOfExtraTime", "120"),
        (121, "SecondPeriodOfExtraTime", "120+2"),
        (50, None, "51"),
        (130, "PenaltyShootout", "131"),
    ],
)
def test_format_minute(minute, period, expected):
    assert q.format_minute(minute, period) == expected


# ── Wettbewerbe / Saisons ────────────────────────────────────────────────────

def test_competitions(client):
    resp = client.get(f"{API}/competitions")
    assert resp.status_code == 200
    data = {c["slug"]: c for c in resp.json()}
    assert {"bundesliga", "dfb-pokal"} <= set(data)
    assert data["bundesliga"]["region"] == "Germany"
    assert data["bundesliga"]["format"] == "league"
    assert data["bundesliga"]["seasons"] == ["2627", "2526"]
    assert data["dfb-pokal"]["seasons"] == ["2627"]


def test_seasons(client):
    resp = client.get(f"{API}/bundesliga/seasons")
    assert resp.status_code == 200
    assert [s["code"] for s in resp.json()] == ["2627", "2526"]


def test_seasons_unknown_slug_404(client):
    assert client.get(f"{API}/nope/seasons").status_code == 404


# ── Spiele ───────────────────────────────────────────────────────────────────

def test_matches_default_is_latest_season(client):
    resp = client.get(f"{API}/bundesliga/matches")
    assert resp.status_code == 200
    data = resp.json()
    assert [m["id"] for m in data] == [IDS["m1"], IDS["m2"], IDS["m3"], IDS["m4"], IDS["m5"]]
    first = data[0]
    assert first["home_team"]["name"] == "Zeta"
    assert first["away_team"]["name"] == "Alpha"
    assert (first["home_score"], first["away_score"]) == (1, 0)
    assert (first["ht_home_score"], first["ht_away_score"]) == (1, 0)
    assert first["competition"] == "bundesliga"
    assert first["season"] == "2627"
    assert first["ws_match_id"] == 9001


def test_matches_other_season(client):
    resp = client.get(f"{API}/bundesliga/matches", params={"season": "2526"})
    assert [m["id"] for m in resp.json()] == [IDS["m_old"]]


def test_matches_filters(client):
    by_team = client.get(f"{API}/bundesliga/matches", params={"team_id": IDS["zeta"]}).json()
    assert [m["id"] for m in by_team] == [IDS["m1"], IDS["m2"]]

    by_status = client.get(f"{API}/bundesliga/matches", params={"status": "scheduled"}).json()
    assert [m["id"] for m in by_status] == [IDS["m4"]]

    by_date = client.get(
        f"{API}/bundesliga/matches", params={"date_from": "2026-08-29", "date_to": "2026-09-05"}
    ).json()
    assert [m["id"] for m in by_date] == [IDS["m2"], IDS["m3"]]

    one_day = client.get(
        f"{API}/bundesliga/matches", params={"date_from": "2026-08-22", "date_to": "2026-08-22"}
    ).json()
    assert [m["id"] for m in one_day] == [IDS["m1"]]


def test_matches_invalid_status_422(client):
    assert client.get(f"{API}/bundesliga/matches", params={"status": "bogus"}).status_code == 422


def test_matches_404s(client):
    assert client.get(f"{API}/nope/matches").status_code == 404
    assert client.get(f"{API}/bundesliga/matches", params={"season": "1999"}).status_code == 404


# ── Tabelle ──────────────────────────────────────────────────────────────────

def test_standings_order_with_head_to_head(client):
    resp = client.get(f"{API}/bundesliga/standings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["competition"] == "bundesliga"
    assert data["season"] == "2627"
    table = data["table"]
    assert [r["team"]["name"] for r in table] == ["Charlie", "Zeta", "Alpha", "Echo", "Delta"]
    assert [r["position"] for r in table] == [1, 2, 3, 4, 5]

    charlie, zeta, alpha, echo, delta = table
    assert (charlie["played"], charlie["won"], charlie["points"], charlie["goal_difference"]) == (1, 1, 3, 1)
    # Zeta und Alpha: identisch in Punkten/Tordifferenz/Toren -> Zeta vorn durch direkten Vergleich
    for row in (zeta, alpha):
        assert (row["points"], row["goal_difference"], row["goals_for"]) == (3, 0, 1)
    assert (zeta["played"], zeta["won"], zeta["lost"]) == (2, 1, 1)
    assert zeta["form"] == ["W", "L"]
    assert alpha["form"] == ["L", "W"]
    # Echo hat nur ein angesetztes Spiel -> 0 Spiele, aber vorhanden
    assert (echo["played"], echo["points"], echo["form"]) == (0, 0, [])
    # Das Spiel der Nicht-Standard-Stage (Delta 5:0 Charlie) zählt nicht
    assert (delta["played"], delta["goals_against"], delta["points"]) == (1, 1, 0)


def test_standings_other_season(client):
    data = client.get(f"{API}/bundesliga/standings", params={"season": "2526"}).json()
    table = data["table"]
    assert [r["team"]["name"] for r in table] == ["Alpha", "Charlie"]  # Gleichstand -> Name
    assert all(r["drawn"] == 1 and r["points"] == 1 for r in table)


def test_standings_cup_404(client):
    resp = client.get(f"{API}/dfb-pokal/standings")
    assert resp.status_code == 404
    assert "Pokal" in resp.json()["detail"]


def test_standings_404s(client):
    assert client.get(f"{API}/nope/standings").status_code == 404
    assert client.get(f"{API}/bundesliga/standings", params={"season": "1999"}).status_code == 404


def test_standings_form_limited_to_five(client):
    db = TestingSessionLocal()
    try:
        # Sechs Spiele hintereinander in einem eigenen Wettbewerb -> nur die letzten 5 in "form"
        region = db.query(Region).one()
        comp = Competition(
            ws_tournament_id=999, region_id=region.id, league_key="TST-Liga",
            name="Testliga", slug="testliga", format="league",
        )
        db.add(comp)
        db.flush()
        season = Season(competition_id=comp.id, ws_season_id=9999, code="2728")
        db.add(season)
        db.flush()
        stage = Stage(season_id=season.id, ws_stage_id=9999, name="Hauptrunde", is_default=True)
        db.add(stage)
        db.flush()
        for i in range(6):
            db.add(Match(
                ws_match_id=8000 + i, stage_id=stage.id, home_team_id=IDS["zeta"], away_team_id=IDS["alpha"],
                kickoff_time=datetime(2027, 8, 1 + i, 15, 30, tzinfo=BERLIN),
                status="finished", home_score=1 if i < 5 else 0, away_score=0 if i < 5 else 1,
            ))
        db.commit()
        table = q.compute_standings(db, season.id)
    finally:
        db.close()
    zeta_row = next(r for r in table if r["team"]["name"] == "Zeta")
    assert zeta_row["form"] == ["W", "W", "W", "W", "L"]
    assert zeta_row["played"] == 6


# ── Teams ────────────────────────────────────────────────────────────────────

def test_competition_teams(client):
    resp = client.get(f"{API}/bundesliga/teams")
    assert resp.status_code == 200
    assert [t["name"] for t in resp.json()] == ["Alpha", "Charlie", "Delta", "Echo", "Zeta"]
    zeta = next(t for t in resp.json() if t["name"] == "Zeta")
    assert zeta["country"]["code"] == "GER"
    assert client.get(f"{API}/bundesliga/teams", params={"season": "2526"}).json()[0]["name"] == "Alpha"
    assert client.get(f"{API}/nope/teams").status_code == 404
    assert client.get(f"{API}/bundesliga/teams", params={"season": "1999"}).status_code == 404


def test_team_detail(client):
    resp = client.get(f"{API}/teams/{IDS['zeta']}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Zeta"
    assert data["country"] == {"id": data["country"]["id"], "name": "Germany", "code": "GER"}
    assert client.get(f"{API}/teams/{IDS['charlie']}").json()["country"] is None
    assert client.get(f"{API}/teams/99999").status_code == 404


def test_team_matches(client):
    charlie = IDS["charlie"]
    all_ids = [m["id"] for m in client.get(f"{API}/teams/{charlie}/matches").json()]
    assert set(all_ids) == {IDS["m2"], IDS["m5"], IDS["m_old"], IDS["m_cup"]}

    bl = client.get(f"{API}/teams/{charlie}/matches", params={"season_slug": "bundesliga"}).json()
    assert {m["id"] for m in bl} == {IDS["m2"], IDS["m5"], IDS["m_old"]}

    old = client.get(
        f"{API}/teams/{charlie}/matches", params={"season_slug": "bundesliga", "season": "2526"}
    ).json()
    assert [m["id"] for m in old] == [IDS["m_old"]]

    cup = client.get(f"{API}/teams/{charlie}/matches", params={"season_slug": "dfb-pokal"}).json()
    assert [m["id"] for m in cup] == [IDS["m_cup"]]
    assert cup[0]["competition"] == "dfb-pokal"

    assert client.get(f"{API}/teams/99999/matches").status_code == 404
    assert client.get(f"{API}/teams/{charlie}/matches", params={"season_slug": "nope"}).status_code == 404
    assert client.get(
        f"{API}/teams/{charlie}/matches", params={"season_slug": "bundesliga", "season": "1999"}
    ).status_code == 404


# ── Spieldetail ──────────────────────────────────────────────────────────────

def test_match_detail(client):
    resp = client.get(f"{API}/matches/{IDS['m1']}")
    assert resp.status_code == 200
    d = resp.json()
    assert d["home_team"]["name"] == "Zeta"
    assert d["venue"]["name"] == "Testarena"
    assert d["referee"]["name"] == "Max Muster"
    assert d["attendance"] == 40000
    assert d["started_at"] is not None
    assert d["first_half_ended_at"] is not None
    assert d["second_half_started_at"] is not None

    assert d["home"]["team"]["name"] == "Zeta"
    assert d["home"]["manager"] == "Coach Z"
    assert d["home"]["average_age"] == 26.5
    assert d["away"]["manager"] is None
    formation = d["home"]["formations"][0]
    assert formation["name"] == "4-4-2"
    assert formation["start_minute"] == 0
    assert formation["end_minute"] == 59
    assert formation["captain"]["name"] == "Z Keeper"
    assert [p["slot"] for p in formation["positions"]] == [1, 2]
    assert formation["positions"][0]["player"]["name"] == "Z Keeper"
    assert formation["positions"][1]["vertical"] == 8.0
    assert d["away"]["formations"][0]["name"] == "4-3-3"
    assert d["away"]["formations"][0]["captain"] is None

    goal, card = d["incidents"]
    assert goal["type"] == "goal"
    assert goal["minute"] == "45+2"
    assert goal["team"]["name"] == "Zeta"
    assert goal["player"]["name"] == "Z Stuermer"
    assert goal["related_player"]["name"] == "Z Keeper"
    assert goal["counts_for_team_id"] == IDS["zeta"]
    assert card["type"] == "card"
    assert card["card_type"] == "yellow"
    assert card["minute"] == "60"
    assert card["counts_for_team_id"] is None

    assert d["sync_state"]["attempts"] == 2
    assert d["sync_state"]["details_final_at"] is not None


def test_match_detail_own_goal_counts_for_opponent(client):
    d = client.get(f"{API}/matches/{IDS['m2']}").json()
    own = d["incidents"][0]
    assert own["type"] == "own_goal"
    assert own["team"]["name"] == "Zeta"
    assert own["counts_for_team_id"] == IDS["charlie"]
    assert own["minute"] == "71"
    # Ohne Zusatzdaten
    assert d["venue"] is None
    assert d["sync_state"] is None
    assert d["home"]["formations"] == []


def test_match_404s(client):
    for suffix in ("", "/lineups", "/stats"):
        assert client.get(f"{API}/matches/99999{suffix}").status_code == 404


def test_lineups(client):
    resp = client.get(f"{API}/matches/{IDS['m1']}/lineups")
    assert resp.status_code == 200
    d = resp.json()
    assert d["match_id"] == IDS["m1"]
    assert d["home"]["team"]["name"] == "Zeta"
    assert [p["player"]["name"] for p in d["home"]["starters"]] == ["Z Keeper", "Z Stuermer"]
    keeper = d["home"]["starters"][0]
    assert keeper["shirt_no"] == 1
    assert keeper["position"] == "GK"
    assert keeper["rating"] == 7.1
    assert keeper["is_man_of_the_match"] is True
    assert keeper["age"] == 30
    assert [p["player"]["name"] for p in d["home"]["bench"]] == ["Z Bank"]
    assert d["home"]["bench"][0]["subbed_in_minute"] == 60
    assert [p["player"]["name"] for p in d["away"]["starters"]] == ["A Stuermer"]
    assert d["away"]["starters"][0]["subbed_out_minute"] == 70
    assert d["away"]["bench"] == []


def test_lineups_empty_match(client):
    d = client.get(f"{API}/matches/{IDS['m3']}/lineups").json()
    assert d["home"]["starters"] == [] and d["away"]["bench"] == []


def test_stats(client):
    resp = client.get(f"{API}/matches/{IDS['m1']}/stats")
    assert resp.status_code == 200
    d = resp.json()
    assert d["team_stats"]["home"] == {"passesAccurate": 300, "shotsTotal": 12}
    assert d["team_stats"]["away"] == {"shotsTotal": 8}
    # Z Stuermer hat weder Statistik noch Bewertung -> nicht enthalten
    assert [p["player"]["name"] for p in d["player_stats"]] == ["Z Keeper", "Z Bank", "A Stuermer"]
    keeper = d["player_stats"][0]
    assert keeper["team_id"] == IDS["zeta"]
    assert keeper["rating"] == 7.1
    assert keeper["stats"] == {"passesAccurate": 25, "shotsTotal": 3}
    assert d["player_stats"][1]["stats"] == {}


def test_stats_empty_match(client):
    d = client.get(f"{API}/matches/{IDS['m3']}/stats").json()
    assert d["team_stats"] == {"home": {}, "away": {}}
    assert d["player_stats"] == []


# ── Fehlende Spieler ─────────────────────────────────────────────────────────

def test_team_missing_players(client):
    resp = client.get(f"{API}/teams/{IDS['alpha']}/missing-players")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["player"]["name"] == "A Stuermer"
    assert data[0]["team"]["name"] == "Alpha"
    assert data[0]["reason"] == "injured"
    assert data[0]["status"] == "Out"
    assert data[0]["match_id"] == IDS["m4"]
    assert data[0]["updated_at"] is not None
    assert client.get(f"{API}/teams/{IDS['echo']}/missing-players").json() == []
    assert client.get(f"{API}/teams/99999/missing-players").status_code == 404


def test_competition_missing_players(client):
    resp = client.get(f"{API}/bundesliga/missing-players")
    assert resp.status_code == 200
    assert [(m["team"]["name"], m["player"]["name"]) for m in resp.json()] == [
        ("Alpha", "A Stuermer"),
        ("Delta", "D Verteidiger"),
        ("Zeta", "Z Bank"),
    ]
    # Saison 2526 enthält nur Alpha und Charlie
    old = client.get(f"{API}/bundesliga/missing-players", params={"season": "2526"}).json()
    assert [m["team"]["name"] for m in old] == ["Alpha"]
    assert client.get(f"{API}/nope/missing-players").status_code == 404
    assert client.get(f"{API}/bundesliga/missing-players", params={"season": "1999"}).status_code == 404


def test_date_helpers_accept_date_type():
    # date_from/date_to sind auf Tagesgrenzen in Berliner Zeit normalisiert
    db = TestingSessionLocal()
    try:
        matches = q.list_matches(db, date_from=date(2026, 9, 13), date_to=date(2026, 9, 13))
    finally:
        db.close()
    assert [m.id for m in matches] == [IDS["m5"]]
