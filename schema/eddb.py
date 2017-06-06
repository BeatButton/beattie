from asyncqlio.orm.schema.column import Column
from asyncqlio.orm.schema.relationship import Relationship, ForeignKey
from asyncqlio.orm.schema.table import table_base
from asyncqlio.orm.schema.types import \
  BigInt, Boolean, Integer, Text, Timestamp

Table = table_base()


class Commodity(Table):
    id = Column(Integer, primary_key=True)
    name = Column(Text)
    average_price = Column(Integer)
    is_rare = Column(Boolean)
    category = Column(Text)
    listings = Relationship(id, 'listing.commodity_id')


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
    stations = Relationship(id, 'station.system_id')


class Station(Table):
    id = Column(Integer, primary_key=True)
    system_id = Column(Integer, foreign_key=ForeignKey(System.id))
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
    listings = Relationship(id, 'listing.station_id')
    system = Relationship(system_id, System.id, load='joined', use_iter=False)


class Listing(Table):
    id = Column(Integer, primary_key=True)
    station_id = Column(Integer, foreign_key=ForeignKey(Station.id))
    commodity_id = Column(Integer, foreign_key=ForeignKey(Commodity.id))
    supply = Column(Integer)
    buy_price = Column(Integer)
    sell_price = Column(Integer)
    demand = Column(Integer)
    collected_at = Column(Timestamp)
    station = Relationship(station_id, Station.id,
                           load='joined', use_iter=False)
    commodity = Relationship(commodity_id, Commodity.id,
                             load='joined', use_iter=False)
