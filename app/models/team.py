from typing import Optional

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.country import Country


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    ws_team_id: Mapped[int] = mapped_column(unique=True)
    name: Mapped[str]
    country_id: Mapped[Optional[int]] = mapped_column(ForeignKey("countries.id"))

    country: Mapped[Optional[Country]] = relationship()
