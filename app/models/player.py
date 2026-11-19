from typing import Optional

from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(primary_key=True)
    ws_player_id: Mapped[int] = mapped_column(unique=True)
    name: Mapped[str]
    # Größe in cm, Gewicht in kg
    height: Mapped[Optional[int]]
    weight: Mapped[Optional[int]]
