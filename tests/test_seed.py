from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import (
    Base,
    Competition,
    Driver,
    Match,
    NflTeam,
    Race,
    Region,
    Season,
    Stage,
    Team,
)
from app.database.seed import seed


def _make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def test_seed_idempotent():
    engine = _make_db()

    with Session(engine) as db:
        seed(db)

    with Session(engine) as db:
        seed(db)

    with Session(engine) as db:
        assert db.query(Region).count() == 1
        assert db.query(Competition).count() == 1
        assert db.query(Season).count() == 1
        assert db.query(Stage).count() == 1
        assert db.query(Team).count() == 2
        assert db.query(Match).count() == 1
        assert db.query(Race).count() == 1
        assert db.query(Driver).count() == 1
        assert db.query(NflTeam).count() == 1
