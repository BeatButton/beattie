from asyncqlio.orm.schema.column import Column
from asyncqlio.orm.schema.table import table_base
from asyncqlio.orm.schema.types import BigInt, Text

Table = table_base()


class Guild(Table):  # type: ignore
    id = Column(BigInt, primary_key=True)
    cog_blacklist = Column(Text, nullable=True)
    prefix = Column(Text, nullable=True)
    reminder_channel = Column(BigInt, nullable=True)
