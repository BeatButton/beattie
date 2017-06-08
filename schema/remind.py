from asyncqlio.orm.schema.column import Column
from asyncqlio.orm.schema.table import table_base
from asyncqlio.orm.schema.types import BigInt, Text, Timestamp

Table = table_base()


class Message(Table):
    time = Column(Timestamp, primary_key=True)
    channel = Column(BigInt, primary_key=True)
    text = Column(Text, primary_key=True)
