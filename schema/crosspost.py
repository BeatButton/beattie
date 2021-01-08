from asyncqlio.orm.schema.column import Column
from asyncqlio.orm.schema.table import table_base
from asyncqlio.orm.schema.types import BigInt, Boolean, Integer

Table = table_base()


class Crosspost(Table):  # type: ignore
    guild_id = Column(BigInt, primary_key=True)
    channel_id = Column(BigInt, primary_key=True)
    auto = Column(Boolean, nullable=True)
    mode = Column(Integer, nullable=True)
    max_pages = Column(Integer, nullable=True)
