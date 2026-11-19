from typing import Optional

from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Referee(Base):
    __tablename__ = "referees"

    id: Mapped[int] = mapped_column(primary_key=True)
    ws_official_id: Mapped[int] = mapped_column(unique=True)
    first_name: Mapped[Optional[str]]
    last_name: Mapped[Optional[str]]
    name: Mapped[str]
