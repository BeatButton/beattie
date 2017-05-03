from katagawa.orm.schema import table_base, Column
from katagawa.orm.schema.types import BigInt, Integer, String, Text, ColumnType


class Boolean(ColumnType):
    @staticmethod
    def sql():
        return 'BOOLEAN'


Table = table_base()


class Commodity(Table):
    id = Column(Integer, primary_key=True)
    name = Column(Text)
    average_price = Column(Integer)
    is_rare = Column(Boolean)
    category = Column(Text)


class System(Table):
    id = Column(Integer, primary_key=True)
    name = Column(Text)
    population = Column(BigInt)
    primary_economy = Column(Text)
    government = Column(Text)
    allegiance = Column(Text)
    state = Column(Text)
    security = Column(Text)
    power = Column(Text)


class Station(Table):
    id = Column(Integer, primary_key=True)
    system_id = Column(Integer)
    name = Column(Text)
    max_landing_pad_size = Column(Text)
    distance_to_star = Column(Integer)
    government = Column(Text)
    allegiance = Column(Text)
    state = Column(Text)
    type = Column(Text)
    has_blackmarket = Column(Boolean)
    has_commodities = Column(Boolean)
    import_commodities = Column(Text)
    export_commodities = Column(Text)
    prohibited_commodities = Column(Text)
    economies = Column(Text)
    is_planetary = Column(Boolean)
    selling_ships = Column(Text)


class Listing(Table):
    id = Column(Integer, primary_key=True)
    station_id = Column(Integer)
    commodity_id = Column(Integer)
    supply = Column(Integer)
    buy_price = Column(Integer)
    sell_price = Column(Integer)
    demand = Column(Integer)
    collected_at = Column(Text)
