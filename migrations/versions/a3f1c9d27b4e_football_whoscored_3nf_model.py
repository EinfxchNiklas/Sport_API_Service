"""football whoscored 3nf model

Ersetzt den alten API-Football-Fußball-Stack (competitions, teams, matches, players,
standings, injuries) durch ein neues 3NF-Modell für WhoScored-Daten.
Alte Fußballdaten werden verworfen (vom Betreiber freigegeben).

Revision ID: a3f1c9d27b4e
Revises: 997265bbfef6
Create Date: 2026-11-19 17:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3f1c9d27b4e'
down_revision: Union[str, Sequence[str], None] = '997265bbfef6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # --- Alte Fußballtabellen entfernen (FK-sichere Reihenfolge) ---
    op.drop_index(op.f('ix_injuries_team_id'), table_name='injuries')
    op.drop_index(op.f('ix_injuries_player_id'), table_name='injuries')
    op.drop_table('injuries')
    op.drop_index(op.f('ix_standings_group_name'), table_name='standings')
    op.drop_index(op.f('ix_standings_competition_id'), table_name='standings')
    op.drop_table('standings')
    op.drop_index(op.f('ix_players_team_id'), table_name='players')
    op.drop_index(op.f('ix_players_external_id'), table_name='players')
    op.drop_table('players')
    op.drop_index(op.f('ix_matches_stage'), table_name='matches')
    op.drop_index(op.f('ix_matches_external_id'), table_name='matches')
    op.drop_table('matches')
    op.drop_index(op.f('ix_teams_external_id'), table_name='teams')
    op.drop_table('teams')
    op.drop_index(op.f('ix_competitions_slug'), table_name='competitions')
    op.drop_index(op.f('ix_competitions_external_id'), table_name='competitions')
    op.drop_table('competitions')

    # --- Stammdaten ---
    op.create_table('regions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('ws_region_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('ws_region_id')
    )
    op.create_table('countries',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('code', sa.String(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code'),
    sa.UniqueConstraint('name')
    )
    op.create_table('competitions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('ws_tournament_id', sa.Integer(), nullable=False),
    sa.Column('region_id', sa.Integer(), nullable=False),
    sa.Column('league_key', sa.String(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('slug', sa.String(), nullable=False),
    sa.Column('format', sa.String(), nullable=True),
    sa.ForeignKeyConstraint(['region_id'], ['regions.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('league_key'),
    sa.UniqueConstraint('slug'),
    sa.UniqueConstraint('ws_tournament_id')
    )
    op.create_table('seasons',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('competition_id', sa.Integer(), nullable=False),
    sa.Column('ws_season_id', sa.Integer(), nullable=False),
    sa.Column('code', sa.String(), nullable=False),
    sa.ForeignKeyConstraint(['competition_id'], ['competitions.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('competition_id', 'code'),
    sa.UniqueConstraint('ws_season_id')
    )
    op.create_index(op.f('ix_seasons_competition_id'), 'seasons', ['competition_id'], unique=False)
    op.create_table('stages',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('season_id', sa.Integer(), nullable=False),
    sa.Column('ws_stage_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(), nullable=True),
    sa.Column('is_default', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['season_id'], ['seasons.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('ws_stage_id')
    )
    op.create_index(op.f('ix_stages_season_id'), 'stages', ['season_id'], unique=False)
    op.create_table('teams',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('ws_team_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('country_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['country_id'], ['countries.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('ws_team_id')
    )
    op.create_table('players',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('ws_player_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('height', sa.Integer(), nullable=True),
    sa.Column('weight', sa.Integer(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('ws_player_id')
    )
    op.create_table('venues',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('referees',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('ws_official_id', sa.Integer(), nullable=False),
    sa.Column('first_name', sa.String(), nullable=True),
    sa.Column('last_name', sa.String(), nullable=True),
    sa.Column('name', sa.String(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('ws_official_id')
    )
    op.create_table('managers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('stat_types',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('key', sa.String(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('key')
    )

    # --- Spiele und Spiel-Kindtabellen ---
    op.create_table('matches',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('ws_match_id', sa.Integer(), nullable=False),
    sa.Column('stage_id', sa.Integer(), nullable=False),
    sa.Column('home_team_id', sa.Integer(), nullable=False),
    sa.Column('away_team_id', sa.Integer(), nullable=False),
    sa.Column('kickoff_time', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('home_score', sa.Integer(), nullable=True),
    sa.Column('away_score', sa.Integer(), nullable=True),
    sa.Column('ht_home_score', sa.Integer(), nullable=True),
    sa.Column('ht_away_score', sa.Integer(), nullable=True),
    sa.Column('et_home_score', sa.Integer(), nullable=True),
    sa.Column('et_away_score', sa.Integer(), nullable=True),
    sa.Column('pen_home_score', sa.Integer(), nullable=True),
    sa.Column('pen_away_score', sa.Integer(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('first_half_ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('second_half_started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('venue_id', sa.Integer(), nullable=True),
    sa.Column('referee_id', sa.Integer(), nullable=True),
    sa.Column('attendance', sa.Integer(), nullable=True),
    sa.Column('last_updated', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('home_team_id <> away_team_id', name='ck_matches_teams_differ'),
    sa.ForeignKeyConstraint(['away_team_id'], ['teams.id'], ),
    sa.ForeignKeyConstraint(['home_team_id'], ['teams.id'], ),
    sa.ForeignKeyConstraint(['referee_id'], ['referees.id'], ),
    sa.ForeignKeyConstraint(['stage_id'], ['stages.id'], ),
    sa.ForeignKeyConstraint(['venue_id'], ['venues.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('ws_match_id')
    )
    op.create_index(op.f('ix_matches_away_team_id'), 'matches', ['away_team_id'], unique=False)
    op.create_index(op.f('ix_matches_home_team_id'), 'matches', ['home_team_id'], unique=False)
    op.create_index(op.f('ix_matches_kickoff_time'), 'matches', ['kickoff_time'], unique=False)
    op.create_index(op.f('ix_matches_stage_id'), 'matches', ['stage_id'], unique=False)
    op.create_index(op.f('ix_matches_status'), 'matches', ['status'], unique=False)
    op.create_table('match_teams',
    sa.Column('match_id', sa.Integer(), nullable=False),
    sa.Column('team_id', sa.Integer(), nullable=False),
    sa.Column('manager_id', sa.Integer(), nullable=True),
    sa.Column('average_age', sa.Float(), nullable=True),
    sa.ForeignKeyConstraint(['manager_id'], ['managers.id'], ),
    sa.ForeignKeyConstraint(['match_id'], ['matches.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ),
    sa.PrimaryKeyConstraint('match_id', 'team_id')
    )
    op.create_table('appearances',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('match_id', sa.Integer(), nullable=False),
    sa.Column('team_id', sa.Integer(), nullable=False),
    sa.Column('player_id', sa.Integer(), nullable=False),
    sa.Column('shirt_no', sa.Integer(), nullable=True),
    sa.Column('position', sa.String(), nullable=True),
    sa.Column('is_first_eleven', sa.Boolean(), nullable=False),
    sa.Column('is_man_of_the_match', sa.Boolean(), nullable=False),
    sa.Column('age', sa.Integer(), nullable=True),
    sa.Column('rating', sa.Float(), nullable=True),
    sa.Column('subbed_in_minute', sa.Integer(), nullable=True),
    sa.Column('subbed_out_minute', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['match_id'], ['matches.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['player_id'], ['players.id'], ),
    sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('match_id', 'player_id')
    )
    op.create_index(op.f('ix_appearances_match_id'), 'appearances', ['match_id'], unique=False)
    op.create_index(op.f('ix_appearances_player_id'), 'appearances', ['player_id'], unique=False)
    op.create_table('formations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('match_id', sa.Integer(), nullable=False),
    sa.Column('team_id', sa.Integer(), nullable=False),
    sa.Column('start_minute', sa.Integer(), nullable=False),
    sa.Column('end_minute', sa.Integer(), nullable=True),
    sa.Column('period', sa.Integer(), nullable=True),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('captain_player_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['captain_player_id'], ['players.id'], ),
    sa.ForeignKeyConstraint(['match_id'], ['matches.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('match_id', 'team_id', 'start_minute')
    )
    op.create_table('formation_positions',
    sa.Column('formation_id', sa.Integer(), nullable=False),
    sa.Column('slot', sa.Integer(), nullable=False),
    sa.Column('player_id', sa.Integer(), nullable=True),
    sa.Column('vertical', sa.Float(), nullable=True),
    sa.Column('horizontal', sa.Float(), nullable=True),
    sa.ForeignKeyConstraint(['formation_id'], ['formations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['player_id'], ['players.id'], ),
    sa.PrimaryKeyConstraint('formation_id', 'slot')
    )
    op.create_table('team_match_stats',
    sa.Column('match_id', sa.Integer(), nullable=False),
    sa.Column('team_id', sa.Integer(), nullable=False),
    sa.Column('stat_type_id', sa.Integer(), nullable=False),
    sa.Column('value', sa.Float(), nullable=False),
    sa.ForeignKeyConstraint(['match_id'], ['matches.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['stat_type_id'], ['stat_types.id'], ),
    sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ),
    sa.PrimaryKeyConstraint('match_id', 'team_id', 'stat_type_id')
    )
    op.create_table('player_match_stats',
    sa.Column('appearance_id', sa.Integer(), nullable=False),
    sa.Column('stat_type_id', sa.Integer(), nullable=False),
    sa.Column('value', sa.Float(), nullable=False),
    sa.ForeignKeyConstraint(['appearance_id'], ['appearances.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['stat_type_id'], ['stat_types.id'], ),
    sa.PrimaryKeyConstraint('appearance_id', 'stat_type_id')
    )
    op.create_table('match_incidents',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('match_id', sa.Integer(), nullable=False),
    sa.Column('team_id', sa.Integer(), nullable=False),
    sa.Column('ws_event_id', sa.BigInteger(), nullable=False),
    sa.Column('type', sa.String(), nullable=False),
    sa.Column('card_type', sa.String(), nullable=True),
    sa.Column('minute', sa.Integer(), nullable=False),
    sa.Column('expanded_minute', sa.Integer(), nullable=True),
    sa.Column('period', sa.String(), nullable=True),
    sa.Column('player_id', sa.Integer(), nullable=True),
    sa.Column('related_player_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['match_id'], ['matches.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['player_id'], ['players.id'], ),
    sa.ForeignKeyConstraint(['related_player_id'], ['players.id'], ),
    sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('match_id', 'ws_event_id')
    )
    op.create_index(op.f('ix_match_incidents_match_id'), 'match_incidents', ['match_id'], unique=False)
    op.create_table('missing_players',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('team_id', sa.Integer(), nullable=False),
    sa.Column('player_id', sa.Integer(), nullable=False),
    sa.Column('match_id', sa.Integer(), nullable=True),
    sa.Column('reason', sa.String(), nullable=True),
    sa.Column('status', sa.String(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['match_id'], ['matches.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['player_id'], ['players.id'], ),
    sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('team_id', 'player_id')
    )
    op.create_index(op.f('ix_missing_players_team_id'), 'missing_players', ['team_id'], unique=False)
    op.create_table('match_sync_state',
    sa.Column('match_id', sa.Integer(), nullable=False),
    sa.Column('fixture_synced_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('prematch_synced_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('lineups_confirmed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('details_synced_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('details_final_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_attempt_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('last_error', sa.String(), nullable=True),
    sa.ForeignKeyConstraint(['match_id'], ['matches.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('match_id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    # --- Neue Fußballtabellen entfernen (Kindtabellen zuerst) ---
    op.drop_table('match_sync_state')
    op.drop_index(op.f('ix_missing_players_team_id'), table_name='missing_players')
    op.drop_table('missing_players')
    op.drop_index(op.f('ix_match_incidents_match_id'), table_name='match_incidents')
    op.drop_table('match_incidents')
    op.drop_table('player_match_stats')
    op.drop_table('team_match_stats')
    op.drop_table('formation_positions')
    op.drop_table('formations')
    op.drop_index(op.f('ix_appearances_player_id'), table_name='appearances')
    op.drop_index(op.f('ix_appearances_match_id'), table_name='appearances')
    op.drop_table('appearances')
    op.drop_table('match_teams')
    op.drop_index(op.f('ix_matches_status'), table_name='matches')
    op.drop_index(op.f('ix_matches_stage_id'), table_name='matches')
    op.drop_index(op.f('ix_matches_kickoff_time'), table_name='matches')
    op.drop_index(op.f('ix_matches_home_team_id'), table_name='matches')
    op.drop_index(op.f('ix_matches_away_team_id'), table_name='matches')
    op.drop_table('matches')
    op.drop_table('stat_types')
    op.drop_table('managers')
    op.drop_table('referees')
    op.drop_table('venues')
    op.drop_table('players')
    op.drop_table('teams')
    op.drop_index(op.f('ix_stages_season_id'), table_name='stages')
    op.drop_table('stages')
    op.drop_index(op.f('ix_seasons_competition_id'), table_name='seasons')
    op.drop_table('seasons')
    op.drop_table('competitions')
    op.drop_table('countries')
    op.drop_table('regions')

    # --- Alte Fußballtabellen wiederherstellen (Stand vor dieser Migration, ohne Daten) ---
    op.create_table('competitions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('sport', sa.String(), nullable=False),
    sa.Column('country', sa.String(), nullable=True),
    sa.Column('season', sa.String(), nullable=True),
    sa.Column('slug', sa.String(), nullable=True),
    sa.Column('format', sa.String(), nullable=True),
    sa.Column('logo_url', sa.String(), nullable=True),
    sa.Column('external_id', sa.Integer(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_competitions_external_id'), 'competitions', ['external_id'], unique=False)
    op.create_index(op.f('ix_competitions_slug'), 'competitions', ['slug'], unique=False)
    op.create_table('teams',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('short_name', sa.String(), nullable=True),
    sa.Column('country', sa.String(), nullable=True),
    sa.Column('logo_url', sa.String(), nullable=True),
    sa.Column('external_id', sa.Integer(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_teams_external_id'), 'teams', ['external_id'], unique=False)
    op.create_table('matches',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('competition_id', sa.Integer(), nullable=False),
    sa.Column('home_team_id', sa.Integer(), nullable=False),
    sa.Column('away_team_id', sa.Integer(), nullable=False),
    sa.Column('kickoff_time', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.String(), nullable=True),
    sa.Column('home_score', sa.Integer(), nullable=True),
    sa.Column('away_score', sa.Integer(), nullable=True),
    sa.Column('last_updated', sa.DateTime(timezone=True), nullable=False),
    sa.Column('stage', sa.String(), nullable=True),
    sa.Column('round_name', sa.String(), nullable=True),
    sa.Column('matchday', sa.Integer(), nullable=True),
    sa.Column('group_name', sa.String(), nullable=True),
    sa.Column('external_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['away_team_id'], ['teams.id'], ),
    sa.ForeignKeyConstraint(['competition_id'], ['competitions.id'], ),
    sa.ForeignKeyConstraint(['home_team_id'], ['teams.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_matches_external_id'), 'matches', ['external_id'], unique=False)
    op.create_index(op.f('ix_matches_stage'), 'matches', ['stage'], unique=False)
    op.create_table('players',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('team_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('position', sa.String(), nullable=True),
    sa.Column('age', sa.Integer(), nullable=True),
    sa.Column('number', sa.Integer(), nullable=True),
    sa.Column('nationality', sa.String(), nullable=True),
    sa.Column('external_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_players_external_id'), 'players', ['external_id'], unique=False)
    op.create_index(op.f('ix_players_team_id'), 'players', ['team_id'], unique=False)
    op.create_table('standings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('competition_id', sa.Integer(), nullable=False),
    sa.Column('team_id', sa.Integer(), nullable=False),
    sa.Column('group_name', sa.String(), nullable=True),
    sa.Column('rank', sa.Integer(), nullable=True),
    sa.Column('played', sa.Integer(), nullable=False),
    sa.Column('won', sa.Integer(), nullable=False),
    sa.Column('draw', sa.Integer(), nullable=False),
    sa.Column('lost', sa.Integer(), nullable=False),
    sa.Column('goals_for', sa.Integer(), nullable=False),
    sa.Column('goals_against', sa.Integer(), nullable=False),
    sa.Column('goal_difference', sa.Integer(), nullable=False),
    sa.Column('points', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['competition_id'], ['competitions.id'], ),
    sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_standings_competition_id'), 'standings', ['competition_id'], unique=False)
    op.create_index(op.f('ix_standings_group_name'), 'standings', ['group_name'], unique=False)
    op.create_table('injuries',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('player_id', sa.Integer(), nullable=False),
    sa.Column('team_id', sa.Integer(), nullable=False),
    sa.Column('description', sa.String(), nullable=True),
    sa.Column('since', sa.Date(), nullable=True),
    sa.Column('missed_matches', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(), nullable=True),
    sa.ForeignKeyConstraint(['player_id'], ['players.id'], ),
    sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_injuries_player_id'), 'injuries', ['player_id'], unique=False)
    op.create_index(op.f('ix_injuries_team_id'), 'injuries', ['team_id'], unique=False)
