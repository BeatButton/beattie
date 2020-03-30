from asyncqlio.orm.schema.column import Column
from asyncqlio.orm.schema.table import table_base
from asyncqlio.orm.schema.types import BigInt, Serial, Text, Timestamp

Table = table_base()


class Reminder(Table):  # type: ignore
    id = Column(Serial, primary_key=True)
    guild_id = Column(BigInt)
    channel_id = Column(BigInt)
    user_id = Column(BigInt)
    time = Column(Timestamp)
    topic = Column(Text)
