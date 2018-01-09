from asyncqlio.orm.schema.column import Column
from asyncqlio.orm.schema.table import table_base
from asyncqlio.orm.schema.types import BigInt, Boolean, Text

Table = table_base()


class Guild(Table):
    id = Column(BigInt, primary_key=True)
    cog_blacklist = Column(Text, nullable=True)
    welcome = Column(Text, nullable=True)
    farewell = Column(Text, nullable=True)
    prefix = Column(Text, nullable=True)
    twitter = Column(Boolean, nullable=True)


class Member(Table):
    guild_id = Column(BigInt, primary_key=True)
    id = Column(BigInt, primary_key=True)
    plonked = Column(Boolean, nullable=True)


class Channel(Table):
    id = Column(BigInt, primary_key=True)
    guild_id = Column(BigInt, primary_key=True)
    plonked = Column(Boolean, nullable=True)
