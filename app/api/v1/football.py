from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models import Competition, Match, Season
from app.schemas.football import (
    CountryRead,
    FootballCompetitionRead,
    FootballLineups,
    FootballMatchCompact,
    FootballMatchDetail,
    FootballMatchStats,
    FootballSeasonRead,
    FootballStandingRow,
    FootballStandings,
    FootballTeamRead,
    FormationPositionRead,
    FormationRead,
    LineupEntry,
    LineupTeam,
    MatchIncidentRead,
    MatchSyncStateRead,
    MatchTeamDetail,
    MissingPlayerRead,
    NamedRef,
    PlayerRef,
    PlayerStatsRead,
    TeamRef,
)
from app.services import football_queries as q

router = APIRouter(prefix="/football", tags=["Fußball"])

MatchStatus = Literal["scheduled", "live", "finished", "postponed", "cancelled", "abandoned"]


# ── Hilfsfunktionen ──────────────────────────────────────────────────────────

def _competition_or_404(db: Session, slug: str) -> Competition:
    competition = q.get_competition_by_slug(db, slug)
    if competition is None:
        raise HTTPException(status_code=404, detail=f"Wettbewerb '{slug}' nicht gefunden")
    return competition


def _season_or_404(db: Session, competition: Competition, season_code: Optional[str]) -> Season:
    season = q.resolve_season(db, competition, season_code)
    if season is None:
        if season_code is None:
            detail = f"Keine Saison für '{competition.slug}' vorhanden"
        else:
            detail = f"Saison '{season_code}' für '{competition.slug}' nicht gefunden"
        raise HTTPException(status_code=404, detail=detail)
    return season


def _match_or_404(db: Session, match_id: int) -> Match:
    match = q.get_match(db, match_id)
    if match is None:
        raise HTTPException(status_code=404, detail=f"Spiel {match_id} nicht gefunden")
    return match


def _compact(m: Match) -> FootballMatchCompact:
    season = m.stage.season if m.stage else None
    return FootballMatchCompact(
        id=m.id,
        ws_match_id=m.ws_match_id,
        competition=season.competition.slug if season else None,
        season=season.code if season else None,
        kickoff_time=m.kickoff_time,
        status=m.status,
        home_team=TeamRef.model_validate(m.home_team),
        away_team=TeamRef.model_validate(m.away_team),
        home_score=m.home_score,
        away_score=m.away_score,
        ht_home_score=m.ht_home_score,
        ht_away_score=m.ht_away_score,
        et_home_score=m.et_home_score,
        et_away_score=m.et_away_score,
        pen_home_score=m.pen_home_score,
        pen_away_score=m.pen_away_score,
    )


def _player_ref(players: dict, player_id: Optional[int]) -> Optional[PlayerRef]:
    player = players.get(player_id) if player_id is not None else None
    return PlayerRef.model_validate(player) if player else None


# ── Wettbewerbe & Saisons ────────────────────────────────────────────────────

@router.get("/competitions", response_model=list[FootballCompetitionRead])
def get_competitions(db: Session = Depends(get_db)):
    return [
        FootballCompetitionRead(
            id=c.id,
            name=c.name,
            slug=c.slug,
            format=c.format,
            region=c.region.name if c.region else None,
            seasons=codes,
        )
        for c, codes in q.list_competitions(db)
    ]


# ── Einzelne Spiele ──────────────────────────────────────────────────────────

@router.get("/matches/{match_id}", response_model=FootballMatchDetail)
def get_match_detail(match_id: int, db: Session = Depends(get_db)):
    match = _match_or_404(db, match_id)
    data = q.get_match_detail(db, match)
    players = data["players"]

    formations_by_team: dict[int, list[FormationRead]] = {}
    for f in data["formations"]:
        formations_by_team.setdefault(f.team_id, []).append(
            FormationRead(
                name=f.name,
                start_minute=f.start_minute,
                end_minute=f.end_minute,
                period=f.period,
                captain=_player_ref(players, f.captain_player_id),
                positions=[
                    FormationPositionRead(
                        slot=p.slot,
                        player=_player_ref(players, p.player_id),
                        vertical=p.vertical,
                        horizontal=p.horizontal,
                    )
                    for p in data["positions"].get(f.id, [])
                ],
            )
        )

    def team_detail(team) -> MatchTeamDetail:
        mt = data["match_teams"].get(team.id)
        return MatchTeamDetail(
            team=TeamRef.model_validate(team),
            manager=mt.manager.name if mt and mt.manager else None,
            average_age=mt.average_age if mt else None,
            formations=formations_by_team.get(team.id, []),
        )

    teams = {match.home_team_id: match.home_team, match.away_team_id: match.away_team}
    incidents = []
    for inc in data["incidents"]:
        counts_for = None
        if inc.type in ("goal", "penalty_goal"):
            counts_for = inc.team_id
        elif inc.type == "own_goal":
            counts_for = match.away_team_id if inc.team_id == match.home_team_id else match.home_team_id
        team = teams.get(inc.team_id)
        incidents.append(
            MatchIncidentRead(
                id=inc.id,
                type=inc.type,
                card_type=inc.card_type,
                minute=q.format_minute(inc.minute, inc.period),
                expanded_minute=inc.expanded_minute,
                period=inc.period,
                team=TeamRef.model_validate(team) if team else TeamRef(id=inc.team_id, name=""),
                counts_for_team_id=counts_for,
                player=_player_ref(players, inc.player_id),
                related_player=_player_ref(players, inc.related_player_id),
            )
        )

    compact = _compact(match)
    return FootballMatchDetail(
        **compact.model_dump(),
        venue=NamedRef.model_validate(match.venue) if match.venue else None,
        referee=NamedRef.model_validate(match.referee) if match.referee else None,
        attendance=match.attendance,
        started_at=match.started_at,
        first_half_ended_at=match.first_half_ended_at,
        second_half_started_at=match.second_half_started_at,
        home=team_detail(match.home_team),
        away=team_detail(match.away_team),
        incidents=incidents,
        sync_state=(
            MatchSyncStateRead.model_validate(data["sync_state"]) if data["sync_state"] else None
        ),
    )


@router.get("/matches/{match_id}/lineups", response_model=FootballLineups)
def get_match_lineups(match_id: int, db: Session = Depends(get_db)):
    match = _match_or_404(db, match_id)
    result = {
        match.home_team_id: LineupTeam(team=TeamRef.model_validate(match.home_team)),
        match.away_team_id: LineupTeam(team=TeamRef.model_validate(match.away_team)),
    }
    for a in q.get_lineups(db, match_id):
        lineup = result.get(a.team_id)
        if lineup is None:
            continue
        entry = LineupEntry(
            player=PlayerRef.model_validate(a.player),
            shirt_no=a.shirt_no,
            position=a.position,
            rating=a.rating,
            is_man_of_the_match=a.is_man_of_the_match,
            age=a.age,
            subbed_in_minute=a.subbed_in_minute,
            subbed_out_minute=a.subbed_out_minute,
        )
        (lineup.starters if a.is_first_eleven else lineup.bench).append(entry)
    return FootballLineups(
        match_id=match_id, home=result[match.home_team_id], away=result[match.away_team_id]
    )


@router.get("/matches/{match_id}/stats", response_model=FootballMatchStats)
def get_match_stats(match_id: int, db: Session = Depends(get_db)):
    match = _match_or_404(db, match_id)
    team_stats = q.get_team_stats(db, match_id)
    player_stats = [
        PlayerStatsRead(
            player=PlayerRef.model_validate(a.player),
            team_id=a.team_id,
            rating=a.rating,
            stats=stats,
        )
        for a, stats in q.get_player_stats(db, match_id)
    ]
    # Heim-Spieler zuerst, innerhalb eines Teams nach Bewertung absteigend.
    player_stats.sort(key=lambda p: (p.team_id != match.home_team_id, -(p.rating or 0.0), p.player.id))
    return FootballMatchStats(
        match_id=match_id,
        team_stats={
            "home": team_stats.get(match.home_team_id, {}),
            "away": team_stats.get(match.away_team_id, {}),
        },
        player_stats=player_stats,
    )


# ── Teams ────────────────────────────────────────────────────────────────────

def _team_or_404(db: Session, team_id: int):
    team = q.get_team(db, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail=f"Team {team_id} nicht gefunden")
    return team


def _missing_read(rows) -> list[MissingPlayerRead]:
    return [
        MissingPlayerRead(
            player=PlayerRef.model_validate(player),
            team=TeamRef.model_validate(team),
            reason=mp.reason,
            status=mp.status,
            updated_at=mp.updated_at,
            match_id=mp.match_id,
        )
        for mp, player, team in rows
    ]


@router.get("/teams/{team_id}", response_model=FootballTeamRead)
def get_team_detail(team_id: int, db: Session = Depends(get_db)):
    team = _team_or_404(db, team_id)
    return FootballTeamRead(
        id=team.id,
        ws_team_id=team.ws_team_id,
        name=team.name,
        country=CountryRead.model_validate(team.country) if team.country else None,
    )


@router.get("/teams/{team_id}/matches", response_model=list[FootballMatchCompact])
def get_team_matches(
    team_id: int,
    season_slug: Optional[str] = Query(default=None, description="Slug des Wettbewerbs"),
    season: Optional[str] = Query(default=None, description="Saison-Code, z. B. 2627"),
    db: Session = Depends(get_db),
):
    _team_or_404(db, team_id)
    competition_id = None
    if season_slug is not None:
        competition = _competition_or_404(db, season_slug)
        competition_id = competition.id
        if season is not None:
            _season_or_404(db, competition, season)
    matches = q.list_matches(db, team_id=team_id, competition_id=competition_id, season_code=season)
    return [_compact(m) for m in matches]


@router.get("/teams/{team_id}/missing-players", response_model=list[MissingPlayerRead])
def get_team_missing_players(team_id: int, db: Session = Depends(get_db)):
    _team_or_404(db, team_id)
    return _missing_read(q.list_missing_players(db, team_id=team_id))


# ── Wettbewerbsbezogene Endpunkte ────────────────────────────────────────────

@router.get("/{slug}/seasons", response_model=list[FootballSeasonRead])
def get_seasons(slug: str, db: Session = Depends(get_db)):
    competition = _competition_or_404(db, slug)
    return q.list_seasons(db, competition)


@router.get("/{slug}/matches", response_model=list[FootballMatchCompact])
def get_matches(
    slug: str,
    season: Optional[str] = Query(default=None, description="Saison-Code, Standard: aktuelle Saison"),
    team_id: Optional[int] = None,
    status: Optional[MatchStatus] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: Session = Depends(get_db),
):
    competition = _competition_or_404(db, slug)
    season_obj = _season_or_404(db, competition, season)
    matches = q.list_matches(
        db,
        season_id=season_obj.id,
        team_id=team_id,
        status=status,
        date_from=date_from,
        date_to=date_to,
    )
    return [_compact(m) for m in matches]


@router.get("/{slug}/standings", response_model=FootballStandings)
def get_standings(
    slug: str,
    season: Optional[str] = Query(default=None, description="Saison-Code, Standard: aktuelle Saison"),
    db: Session = Depends(get_db),
):
    competition = _competition_or_404(db, slug)
    if competition.format == "cup":
        raise HTTPException(
            status_code=404,
            detail=f"'{slug}' ist ein Pokalwettbewerb – für K.-o.-Runden gibt es keine Tabelle",
        )
    season_obj = _season_or_404(db, competition, season)
    table = q.compute_standings(db, season_obj.id)
    return FootballStandings(
        competition=competition.slug,
        season=season_obj.code,
        table=[FootballStandingRow(**row) for row in table],
    )


@router.get("/{slug}/teams", response_model=list[FootballTeamRead])
def get_teams(
    slug: str,
    season: Optional[str] = Query(default=None, description="Saison-Code, Standard: aktuelle Saison"),
    db: Session = Depends(get_db),
):
    competition = _competition_or_404(db, slug)
    season_obj = _season_or_404(db, competition, season)
    return [
        FootballTeamRead(
            id=t.id,
            ws_team_id=t.ws_team_id,
            name=t.name,
            country=CountryRead.model_validate(t.country) if t.country else None,
        )
        for t in q.list_season_teams(db, season_obj.id)
    ]


@router.get("/{slug}/missing-players", response_model=list[MissingPlayerRead])
def get_competition_missing_players(
    slug: str,
    season: Optional[str] = Query(default=None, description="Saison-Code, Standard: aktuelle Saison"),
    db: Session = Depends(get_db),
):
    competition = _competition_or_404(db, slug)
    season_obj = _season_or_404(db, competition, season)
    return _missing_read(q.list_missing_players(db, season_id=season_obj.id))
