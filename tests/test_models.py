import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

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


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _):
        # SQLite erzwingt Fremdschlüssel (inkl. ON DELETE CASCADE) nur mit diesem PRAGMA
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _make_chain(db: Session, ws_match_id: int = 1001):
    region = Region(ws_region_id=81, name="Germany")
    db.add(region)
    db.flush()
    comp = Competition(
        ws_tournament_id=3,
        region_id=region.id,
        league_key="GER-Bundesliga",
        name="Bundesliga",
        slug="bundesliga",
        format="league",
    )
    db.add(comp)
    db.flush()
    season = Season(competition_id=comp.id, ws_season_id=10, code="2627")
    db.add(season)
    db.flush()
    stage = Stage(season_id=season.id, ws_stage_id=20, name="Bundesliga", is_default=True)
    home = Team(ws_team_id=1, name="FC Bayern München")
    away = Team(ws_team_id=2, name="Borussia Dortmund")
    db.add_all([stage, home, away])
    db.flush()
    match = Match(
        ws_match_id=ws_match_id,
        stage_id=stage.id,
        home_team_id=home.id,
        away_team_id=away.id,
    )
    db.add(match)
    db.flush()
    return comp, season, stage, home, away, match


def test_create_competition_with_region(db):
    region = Region(ws_region_id=81, name="Germany")
    db.add(region)
    db.flush()
    comp = Competition(
        ws_tournament_id=3,
        region_id=region.id,
        league_key="GER-Bundesliga",
        name="Bundesliga",
        slug="bundesliga",
        format="league",
    )
    db.add(comp)
    db.commit()

    fetched = db.get(Competition, comp.id)
    assert fetched.region.name == "Germany"
    assert fetched.slug == "bundesliga"
    assert fetched.format == "league"


def test_full_chain_match_to_player_stat(db):
    comp, season, stage, home, away, match = _make_chain(db)

    germany = Country(name="Germany", code="GER")
    db.add(germany)
    db.flush()
    home.country_id = germany.id

    player = Player(ws_player_id=500, name="Harry Kane", height=188, weight=86)
    venue = Venue(name="Allianz Arena")
    referee = Referee(ws_official_id=77, first_name="Felix", last_name="Zwayer", name="Felix Zwayer")
    manager = Manager(name="Vincent Kompany")
    stat_type = StatType(key="shotsTotal")
    db.add_all([player, venue, referee, manager, stat_type])
    db.flush()

    match.venue_id = venue.id
    match.referee_id = referee.id
    db.add(MatchTeam(match_id=match.id, team_id=home.id, manager_id=manager.id, average_age=26.5))
    appearance = Appearance(
        match_id=match.id,
        team_id=home.id,
        player_id=player.id,
        shirt_no=9,
        position="FW",
        is_first_eleven=True,
        rating=8.1,
    )
    db.add(appearance)
    db.flush()
    db.add(PlayerMatchStat(appearance_id=appearance.id, stat_type_id=stat_type.id, value=4))
    db.add(TeamMatchStat(match_id=match.id, team_id=home.id, stat_type_id=stat_type.id, value=15))
    db.commit()

    fetched = db.get(Match, match.id)
    assert fetched.home_team.name == "FC Bayern München"
    assert fetched.away_team.name == "Borussia Dortmund"
    assert fetched.stage.season.competition.name == "Bundesliga"
    assert fetched.venue.name == "Allianz Arena"
    assert fetched.referee.name == "Felix Zwayer"
    assert fetched.home_team.country.name == "Germany"
    assert db.get(Appearance, appearance.id).player.name == "Harry Kane"
    assert db.get(PlayerMatchStat, (appearance.id, stat_type.id)).value == 4
    assert db.get(TeamMatchStat, (match.id, home.id, stat_type.id)).value == 15
    assert db.get(MatchTeam, (match.id, home.id)).manager.name == "Vincent Kompany"


def test_match_defaults(db):
    _, _, _, _, _, match = _make_chain(db)
    db.commit()

    fetched = db.get(Match, match.id)
    assert fetched.status == "scheduled"
    assert fetched.last_updated is not None
    assert fetched.home_score is None
    assert fetched.kickoff_time is None


def test_match_ws_match_id_unique(db):
    _, _, stage, home, away, _ = _make_chain(db, ws_match_id=1001)
    db.commit()

    db.add(Match(ws_match_id=1001, stage_id=stage.id, home_team_id=home.id, away_team_id=away.id))
    with pytest.raises(IntegrityError):
        db.flush()


def test_match_teams_must_differ(db):
    _, _, stage, home, _, _ = _make_chain(db)
    db.commit()

    db.add(Match(ws_match_id=2002, stage_id=stage.id, home_team_id=home.id, away_team_id=home.id))
    with pytest.raises(IntegrityError):
        db.flush()


def test_appearance_unique_per_match_and_player(db):
    _, _, _, home, _, match = _make_chain(db)
    player = Player(ws_player_id=500, name="Harry Kane")
    db.add(player)
    db.flush()
    db.add(Appearance(match_id=match.id, team_id=home.id, player_id=player.id))
    db.flush()

    db.add(Appearance(match_id=match.id, team_id=home.id, player_id=player.id))
    with pytest.raises(IntegrityError):
        db.flush()


def test_season_unique_per_competition_and_code(db):
    comp, _, _, _, _, _ = _make_chain(db)
    db.commit()

    db.add(Season(competition_id=comp.id, ws_season_id=11, code="2627"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_delete_match_cascades_to_children(db):
    _, _, _, home, away, match = _make_chain(db)
    player = Player(ws_player_id=500, name="Harry Kane")
    stat_type = StatType(key="shotsTotal")
    db.add_all([player, stat_type])
    db.flush()
    appearance = Appearance(match_id=match.id, team_id=home.id, player_id=player.id)
    formation = Formation(match_id=match.id, team_id=home.id, start_minute=0, name="4-2-3-1")
    db.add_all([appearance, formation])
    db.flush()
    db.add_all(
        [
            PlayerMatchStat(appearance_id=appearance.id, stat_type_id=stat_type.id, value=1),
            TeamMatchStat(match_id=match.id, team_id=home.id, stat_type_id=stat_type.id, value=2),
            FormationPosition(formation_id=formation.id, slot=1, player_id=player.id),
            MatchTeam(match_id=match.id, team_id=home.id),
            MatchIncident(
                match_id=match.id,
                team_id=home.id,
                ws_event_id=9_000_000_000_001,
                type="goal",
                minute=12,
                player_id=player.id,
            ),
            MatchSyncState(match_id=match.id),
            MissingPlayer(team_id=away.id, player_id=player.id, match_id=match.id, reason="Knie"),
        ]
    )
    db.commit()

    db.delete(db.get(Match, match.id))
    db.commit()
    db.expire_all()

    for model in (
        Appearance,
        Formation,
        FormationPosition,
        PlayerMatchStat,
        TeamMatchStat,
        MatchTeam,
        MatchIncident,
        MatchSyncState,
    ):
        assert db.scalars(select(model)).first() is None, model.__name__
    # MissingPlayer bleibt erhalten, verliert aber den Spielbezug (ON DELETE SET NULL)
    missing = db.scalars(select(MissingPlayer)).one()
    assert missing.match_id is None
    assert missing.updated_at is not None


def test_match_sync_state_defaults(db):
    _, _, _, _, _, match = _make_chain(db)
    db.add(MatchSyncState(match_id=match.id))
    db.commit()

    state = db.get(MatchSyncState, match.id)
    assert state.attempts == 0
    assert state.last_error is None
    assert state.details_final_at is None
