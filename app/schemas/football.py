from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TeamRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class PlayerRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class NamedRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class CountryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: str | None = None


class FootballCompetitionRead(BaseModel):
    id: int
    name: str
    slug: str
    format: str | None = None
    region: str | None = None
    seasons: list[str] = []


class FootballSeasonRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str


class FootballMatchCompact(BaseModel):
    id: int
    ws_match_id: int
    competition: str | None = None
    season: str | None = None
    kickoff_time: datetime | None = None
    status: str
    home_team: TeamRef
    away_team: TeamRef
    home_score: int | None = None
    away_score: int | None = None
    ht_home_score: int | None = None
    ht_away_score: int | None = None
    et_home_score: int | None = None
    et_away_score: int | None = None
    pen_home_score: int | None = None
    pen_away_score: int | None = None


class FootballStandingRow(BaseModel):
    position: int
    team: TeamRef
    played: int
    won: int
    drawn: int
    lost: int
    goals_for: int
    goals_against: int
    goal_difference: int
    points: int
    form: list[str] = []


class FootballStandings(BaseModel):
    competition: str
    season: str
    table: list[FootballStandingRow]


class FootballTeamRead(BaseModel):
    id: int
    ws_team_id: int
    name: str
    country: CountryRead | None = None


class FormationPositionRead(BaseModel):
    slot: int
    player: PlayerRef | None = None
    vertical: float | None = None
    horizontal: float | None = None


class FormationRead(BaseModel):
    name: str
    start_minute: int
    end_minute: int | None = None
    period: int | None = None
    captain: PlayerRef | None = None
    positions: list[FormationPositionRead] = []


class MatchTeamDetail(BaseModel):
    team: TeamRef
    manager: str | None = None
    average_age: float | None = None
    formations: list[FormationRead] = []


class MatchIncidentRead(BaseModel):
    id: int
    type: str
    card_type: str | None = None
    # Anzeige-Minute inkl. Nachspielzeit, z. B. "45+2"
    minute: str
    expanded_minute: int | None = None
    period: str | None = None
    # Team des Spielers (WhoScored-Semantik; bei Eigentoren das Team des Torschützen)
    team: TeamRef
    # Team, dem das Tor gutgeschrieben wird (nur bei Toren; bei Eigentoren das Gegner-Team)
    counts_for_team_id: int | None = None
    player: PlayerRef | None = None
    related_player: PlayerRef | None = None


class MatchSyncStateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    fixture_synced_at: datetime | None = None
    prematch_synced_at: datetime | None = None
    lineups_confirmed_at: datetime | None = None
    details_synced_at: datetime | None = None
    details_final_at: datetime | None = None
    last_attempt_at: datetime | None = None
    attempts: int = 0
    last_error: str | None = None


class FootballMatchDetail(FootballMatchCompact):
    venue: NamedRef | None = None
    referee: NamedRef | None = None
    attendance: int | None = None
    started_at: datetime | None = None
    first_half_ended_at: datetime | None = None
    second_half_started_at: datetime | None = None
    home: MatchTeamDetail
    away: MatchTeamDetail
    incidents: list[MatchIncidentRead] = []
    sync_state: MatchSyncStateRead | None = None


class LineupEntry(BaseModel):
    player: PlayerRef
    shirt_no: int | None = None
    position: str | None = None
    rating: float | None = None
    is_man_of_the_match: bool = False
    age: int | None = None
    subbed_in_minute: int | None = None
    subbed_out_minute: int | None = None


class LineupTeam(BaseModel):
    team: TeamRef
    starters: list[LineupEntry] = []
    bench: list[LineupEntry] = []


class FootballLineups(BaseModel):
    match_id: int
    home: LineupTeam
    away: LineupTeam


class PlayerStatsRead(BaseModel):
    player: PlayerRef
    team_id: int
    rating: float | None = None
    stats: dict[str, float] = {}


class FootballMatchStats(BaseModel):
    match_id: int
    team_stats: dict[str, dict[str, float]]
    player_stats: list[PlayerStatsRead] = []


class MissingPlayerRead(BaseModel):
    player: PlayerRef
    team: TeamRef
    reason: str | None = None
    status: str | None = None
    updated_at: datetime | None = None
    match_id: int | None = None


__all__ = [
    "TeamRef",
    "PlayerRef",
    "NamedRef",
    "CountryRead",
    "FootballCompetitionRead",
    "FootballSeasonRead",
    "FootballMatchCompact",
    "FootballStandingRow",
    "FootballStandings",
    "FootballTeamRead",
    "FormationPositionRead",
    "FormationRead",
    "MatchTeamDetail",
    "MatchIncidentRead",
    "MatchSyncStateRead",
    "FootballMatchDetail",
    "LineupEntry",
    "LineupTeam",
    "FootballLineups",
    "PlayerStatsRead",
    "FootballMatchStats",
    "MissingPlayerRead",
]
