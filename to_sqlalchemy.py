import os
import time

import requests
import sqlalchemy
from sqlalchemy import Column, Integer, String, Boolean, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker 

Base = declarative_base()

class System(Base):
    __tablename__ = 'systems'
    
    id = Column(Integer, primary_key=True)
    name = Column(String)
    population = Column(Integer)
    government = Column(String)
    allegiance = Column(String)
    state = Column(String)
    security = Column(String)
    power = Column(String)
    
class Station(Base):
    __tablename__ = 'stations'

    id = Column(Integer, primary_key=True)
    system_id = Column(Integer)
    name = Column(String)
    max_landing_pad_size = Column(String)
    distance_to_star = Column(Integer)
    government = Column(String)
    allegiance = Column(String)
    state = Column(String)
    type = Column(String)
    has_blackmarket = Column(Boolean)
    has_commodities = Column(Boolean)
    import_commodities = Column(String)
    export_commodities = Column(String)
    prohibited_commodities = Column(String)
    economies = Column(String)
    is_planetary = Column(Boolean)
    selling_ships = Column(String)

class Populated(Base):
    __tablename__ = 'populated'

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    population = Column(Integer)
    government = Column(String)
    allegiance = Column(String)
    state = Column(String)
    security = Column(String)
    power = Column(String)
    
class Body(Base):
    __tablename__ = 'bodies'

    id = Column(Integer, primary_key=True)
    system_id = Column(Integer)
    name = Column(String)
    group = Column(String)
    type = Column(String)
    atmosphere_type = Column(String)
    solar_masses = Column(Float)
    solar_radius = Column(Float)
    earth_masses = Column(Float)
    radius = Column(Integer)
    gravity = Column(Float)
    surface_pressure = Column(Float)
    volcanism_type = Column(String)
    is_rotational_period_tidally_locked = Column(Boolean)
    is_landable = Column(Boolean)

class Commodity(Base):
    __tablename__ = 'commodities'
    
    id = Column(Integer, primary_key=True)
    name = Column(String)
    category = Column(String)
    average_price = Column(Integer)
    is_rare = Column(Boolean)

class Listing(Base):
    __tablename__ = 'listings'
    
    id = Column(Integer, primary_key=True)
    station_id = Column(Integer)
    commodity_id = Column(Integer)
    supply = Column(Integer)
    buy_price = Column(Integer)
    sell_price = Column(Integer)
    demand = Column(Integer)
    collected_at = Column(String)
    
def remake():
    print('Updating ed.db')
    import json
    import csv
    import os
    import shutil

    if os.path.isdir('tmp'):
        if os.path.isfile('tmp/ed.db'):
            os.remove('tmp/ed.db')
    else:
        os.mkdir('tmp')

    print('Downloading raw data...')
    files = ('commodities.json', 'modules.json', 'factions.jsonl',
                 'systems_populated.jsonl', 'stations.jsonl',
                 'listings.csv', 'systems.csv', 'bodies.jsonl',)
    for file in files:
        if not os.path.isfile(f'tmp/{file}'):
            with open(f'tmp/{file}', 'wb') as handle:
                response = requests.get(f'https://eddb.io/archive/v5/{file}', stream=True)
                for block in response.iter_content(1024):
                    handle.write(block)
            print(f'{file} downloaded.')
        else:
            print(f'{file} already present.')

    print('Beginning database creation.')
    engine = sqlalchemy.create_engine('sqlite:///tmp/ed.db', echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    with open('tmp/commodities.json', encoding='utf-8') as commodities:
        commodities = json.load(commodities)
        for commodity in commodities:
            for k, v in commodity.copy().items():
                if isinstance(v, list):
                    commodity[k] = ', '.join(v)
            commodity.pop('category_id')
            commodity['category'] = commodity['category']['name']
            commodity = Commodity(**commodity)
            session.add(commodity)

    session.commit()
    print('Table commodities created.')

    with open('tmp/systems_populated.jsonl', encoding='utf-8') as populated:
        props = ('id', 'name', 'population', 'government', 'allegiance', 'state', 'security', 'power')
        for system in populated:
            system = json.loads(system)
            for prop in props:
                if isinstance(system[prop], list):
                    system[prop] = ', '.join(system[prop])
            system = Populated(**{prop: system[prop] for prop in props})
            session.add(system)

    session.commit()
    print('Table populated created.')
    
    with open('tmp/stations.jsonl', encoding='utf-8') as stations:
        props = ('id', 'system_id', 'name', 'max_landing_pad_size', 'distance_to_star', 'government',
                 'allegiance', 'state', 'type', 'has_blackmarket', 'has_commodities',
                 'import_commodities', 'export_commodities','prohibited_commodities',
                 'economies', 'is_planetary', 'selling_ships')
        for station in stations:
            station = json.loads(station)
            for prop in props:
                if isinstance(station[prop], list):
                    station[prop] = ', '.join(station[prop])
            station = Station(**{prop: station[prop] for prop in props})
            session.add(station)

    session.commit()
    print('Table stations created.')

    with open('tmp/listings.csv', encoding='utf-8') as listings:
        counter = 0
        listings = csv.reader(listings)
        header = next(listings)
        props = {prop: header.index(prop) for prop in header}
        for listing in listings:
            listing = {prop: listing[props[prop]] for prop in props}
            listing['collected_at'] = time.ctime(int(listing['collected_at']))
            listing = Listing(**listing)
            session.add(listing)
            counter += 1
            if counter > 200_000:
                session.commit()
                counter = 0
            

    session.commit()
    print('Table listings created.')
    
    with open('tmp/bodies.jsonl', encoding='utf-8') as bodies:
        counter = 0
        props = ('id', 'system_id', 'name', 'group', 'type', 'atmosphere_type', 'solar_masses',  'solar_radius',
                 'earth_masses', 'radius', 'gravity', 'surface_pressure', 'volcanism_type',
                 'is_rotational_period_tidally_locked', 'is_landable')
        for body in bodies:
            body = json.loads(body)
            for key in body.copy():
                if key.endswith('_name'):
                    body[key.replace('_name', '')] = body.pop(key)
            for prop in props:
                if isinstance(body[prop], list):
                    body[prop] = ', '.join(body[prop])
            body = Body(**{prop: body[prop] for prop in props})
            session.add(body)
            counter += 1
            if counter > 200_000:
                session.commit()
                counter = 0

    session.commit()
    print('Table bodies created.')

    with open('tmp/systems.csv', encoding='utf-8') as systems:
        counter = 0
        systems = csv.reader(systems)
        header = next(systems)
        props = {prop: header.index(prop) for prop in
                 ('id', 'name', 'population', 'government', 'allegiance', 'state', 'security', 'power')}
        for system in systems:
            system = {prop: system[props[prop]] for prop in props}
            for prop in props:
                if isinstance(system[prop], list):
                    system[prop] = ', '.join(system[prop])
            system = System(**system)
            session.add(system)
            counter += 1
            if counter > 200_000:
                session.commit()
                counter = 0

    session.commit()
    print('Table systems created.')

    print('Cleaning up.')
    session.close()
    os.remove('data/ed.db')
    shutil.move('tmp/ed.db', 'data/ed.db')
    shutil.rmtree('tmp')

    print('Update complete.')
