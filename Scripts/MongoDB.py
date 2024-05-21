import click
import pymongo
from flask import current_app, g
from flask.cli import with_appcontext
from werkzeug.security import generate_password_hash

def get_db():
    if 'db' not in g:
        client =  pymongo.MongoClient(current_app.config['MONGO_URI'])
        g.db = client['GJFML_projet']
    return g.db

def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.client.close()

