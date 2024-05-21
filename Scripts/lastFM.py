from flask import Flask, render_template, request, redirect, url_for, flash, session
import requests
from pymongo import MongoClient
import logging
from werkzeug.security import generate_password_hash, check_password_hash
from bson.objectid import ObjectId
import time
from threading import Lock

app = Flask(__name__)
app.secret_key = 'your_secret_key'

client = MongoClient('mongodb://localhost:27017/')
db = client['GJFML_projet']
collection = db['GJFML']

API_KEY = 'ac26d9791fd4d7776763641c32b0785a'
BASE_URL = 'http://ws.audioscrobbler.com/2.0/'

reviews_collection = db['reviews']

class RateLimiter:
    def __init__(self, min_interval):
        self.min_interval = min_interval
        self.lock = Lock()
        self.last_time_called = 0

    def wait(self):
        with self.lock:
            elapsed = time.time() - self.last_time_called
            wait_for = self.min_interval - elapsed
            if wait_for > 0:
                time.sleep(wait_for)
            self.last_time_called = time.time()

rate_limiter = RateLimiter(min_interval=4)  # 4 seconds interval

def make_request(method, params):
    rate_limiter.wait()  # Ensure we wait if necessary before making the request
    params['method'] = method
    params['api_key'] = API_KEY
    params['format'] = 'json'

    response = requests.get(BASE_URL, params=params)

    if response.status_code == 200:
        return response.json()
    else:
        print(f"Erreur lors de la requête: {response.status_code}")
        return None

@app.route('/', methods=['GET', 'POST'])
def index():
    if 'user_id' in session:
        if 'username' in session:
            username = session['username']
            flash(f'Bienvenue, {username} !', 'success')
        else:
            flash('Bienvenue !', 'success')

    if request.method == 'POST':
        query_type = request.form.get('query_type')

        if query_type == 'tag':
            tag = request.form.get('tag')
            return redirect(url_for('tag_result', tag=tag))
        elif query_type == 'album':
            artist = request.form.get('artist')
            album = request.form.get('query_param')
            return redirect(url_for('album_result', artist=artist, album=album))
        elif query_type == 'artist':
            artist = request.form.get('artist')
            return redirect(url_for('artist_result', artist=artist))
        elif query_type == 'global_trends':
            return redirect(url_for('global_trends_result'))
        elif query_type == 'country_trends':
            country = request.form.get('country')
            return redirect(url_for('country_trends_result', country=country))

    return render_template('index.html')

@app.route('/connexion', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = collection.find_one({'username': username})

        if user and check_password_hash(user['password'], password):
            session['user_id'] = str(user['_id'])
            session['username'] = user['username']
            flash('Connexion réussie.', 'success')
            return redirect(url_for('index'))
        else:
            flash('Erreur : identifiant et/ou mot de passe incorrects.', 'danger')

    return render_template('connexion.html')

@app.route('/inscription', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        hashed_password = generate_password_hash(password)

        existing_user = collection.find_one({'username': username})

        if existing_user:
            flash('Vous êtes déjà inscrit.', 'info')
            return redirect(url_for('login'))

        user_id = collection.insert_one({'username': username, 'password': hashed_password}).inserted_id
        session['user_id'] = str(user_id)
        session['username'] = username
        flash(f'Inscription réussie. Vous êtes maintenant connecté.', 'success')
        return redirect(url_for('index'))

    return render_template('inscription.html')

@app.route('/logout', methods=['GET', 'POST'])
def logout():
    session.pop('user_id', None)
    flash('Vous avez été déconnecté.', 'success')
    return redirect(url_for('index'))

@app.route('/tag_result/<tag>')
def tag_result(tag):
    data, from_db = get_tag_info(tag)
    if data is not None:
        flash(f"Les données {'proviennent de la base de données locale.' if from_db else 'ont été récupérées à distance.'}")
        return render_template('tag_result.html', data=data)
    else:
        flash("Les informations sur le tag ne sont pas disponibles.")
        return render_template('error.html', message="Les informations sur le tag ne sont pas disponibles.")

def get_tag_info(tag):
    existing_data = collection.find_one({'tag': tag})

    if existing_data:
        wiki_summary = existing_data.get('wiki', {}).get('summary', '')
        wiki_content = existing_data.get('wiki', {}).get('content', '')
        from_db = True
    else:
        method = 'tag.getInfo'
        params = {'tag': tag}
        response = make_request(method, params)

        if response and 'tag' in response:
            tag_info = response['tag']
            wiki_summary = tag_info.get('wiki', {}).get('summary', '')
            wiki_content = tag_info.get('wiki', {}).get('content', '')
            collection.insert_one({'tag': tag, 'wiki': {'summary': wiki_summary, 'content': wiki_content}})
            from_db = False
        else:
            return None, False

    return {'wiki_summary': wiki_summary, 'wiki_content': wiki_content}, from_db

@app.route('/album_result/<artist>/<album>')
def album_result(artist, album):
    data, from_db = get_album_info(artist, album)
    if data is not None:
        total_duration = data.get('total_duration', 'Non dispo')
        num_tracks = len(data.get('tracks', []))

        logging.info(f"Album: {data.get('name')}, Release Date: {data.get('release_date')}, Total Duration: {total_duration}, Num Tracks: {num_tracks}")

        flash(f"Les données {'proviennent de la base de données locale.' if from_db else 'ont été récupérées à distance.'}")
        return render_template('album_result.html', data=data, total_duration=total_duration, num_tracks=num_tracks)
    else:
        flash("Les informations sur l'album ne sont pas disponibles.")
        return render_template('error.html', message="Les informations sur l'album ne sont pas disponibles.")

def get_album_info(artist, album):
    existing_data = collection.find_one({'artist': artist, 'album': album})

    if existing_data:
        album_info = existing_data.get('album_info', {})
        from_db = True
    else:
        method = 'album.getInfo'
        params = {'artist': artist, 'album': album}
        response = make_request(method, params)

        if response and 'album' in response:
            album_info = response['album']
            tracks_info = []
            total_duration_seconds = 0

            for track in album_info.get('tracks', {}).get('track', []):
                duration = track.get('duration')
                if duration is None:
                    duration = 0
                else:
                    duration = int(duration)

                track_info = {
                    'number': track.get('@attr', {}).get('rank', ''),
                    'name': track.get('name', ''),
                    'duration': duration,
                }
                tracks_info.append(track_info)
                total_duration_seconds += duration

            total_duration_minutes = total_duration_seconds // 60
            album_info['total_duration'] = total_duration_minutes if total_duration_seconds > 0 else "Non dispo"
            album_info['tracks'] = tracks_info

            if 'wiki' in album_info and 'published' in album_info['wiki']:
                album_info['release_date'] = album_info['wiki']['published']
            else:
                album_info['release_date'] = "Non dispo"

            collection.insert_one({'artist': artist, 'album': album, 'album_info': album_info})
            from_db = False
        else:
            return None, False

    return album_info, from_db

@app.route('/artist_result/<artist>')
def artist_result(artist):
    dataTitre = get_artist_titres(artist)
    dataAlbum = get_artist_album(artist)
    dataSimilar = get_artist_similar(artist)
    nomartiste = artist
    photoartiste = get_artist_photo(artist)

    artistdataDB = {
        'name': nomartiste
    }

    collection.insert_one(artistdataDB)

    if dataTitre and dataAlbum is not None:
        return render_template('artist_result.html', dataTitre=dataTitre, dataAlbum=dataAlbum, dataSimilar=dataSimilar, nomartiste=nomartiste, photoartiste=photoartiste)
    else:
        return render_template('error.html', message="Les informations sur l'artiste ne sont pas disponibles.")

def get_artist_titres(artist):
    method = 'artist.getTopTracks'
    params = {'artist': artist}
    return make_request(method, params)

def get_artist_album(artist):
    method = 'artist.getTopAlbums'
    params = {'artist': artist}
    return make_request(method, params)

def get_artist_similar(artist):
    method = 'artist.getSimilar'
    params = {'artist': artist}
    return make_request(method, params)

def get_artist_photo(artist):
    method = 'artist.search'
    params = {'artist': artist}
    return make_request(method, params)

@app.route('/global_trends_result')
def global_trends_result():
    top_artists = get_global_trends_artiste()
    top_tracks = get_global_trends_tracks()
    top_tags = get_global_trends_tags()
    return render_template('global_trends_result.html', top_tracks=top_tracks, top_artists=top_artists, top_tags=top_tags)

def get_global_trends_artiste():
    method = 'chart.getTopArtists'
    params = {}
    return make_request(method, params)

def get_global_trends_tracks():
    method = 'chart.getTopTracks'
    params = {}
    return make_request(method, params)

def get_global_trends_tags():
    method = 'chart.getTopTags'
    params = {}
    return make_request(method, params)

@app.route('/country_trends_result/<country>')
def country_trends_result(country):
    top_tracks, top_artists, from_db = get_country_trends(country)
    if top_tracks is not None and top_artists is not None:
        flash(f"Les données {'proviennent de la base de données locale.' if from_db else 'ont été récupérées à distance.'}")
        return render_template('country_trends_result.html', top_tracks=top_tracks, top_artists=top_artists)
    else:
        flash("Les informations sur les tendances du pays ne sont pas disponibles.")
        return render_template('error.html', message="Les informations sur les tendances du pays ne sont pas disponibles.")

def get_country_trends(country):
    existing_data = collection.find_one({'country': country})

    if existing_data:
        top_tracks = existing_data.get('top_tracks')
        top_artists = existing_data.get('top_artists')
        from_db = True
    else:
        method_tracks = 'geo.getTopTracks'
        params_tracks = {'country': country}
        top_tracks = make_request(method_tracks, params_tracks)

        method_artists = 'geo.getTopArtists'
        params_artists = {'country': country}
        top_artists = make_request(method_artists, params_artists)

        if top_tracks is not None and top_artists is not None:
            collection.insert_one({'country': country, 'top_tracks': top_tracks, 'top_artists': top_artists})
            from_db = False
        else:
            return None, None, False

    return top_tracks, top_artists, from_db

@app.route('/submit_review/<type>/<item_id>', methods=['POST'])
def submit_review(type, item_id):
    if 'user_id' not in session:
        flash('Vous devez être connecté pour soumettre un avis.', 'info')
        return redirect(url_for('login'))

    if request.method == 'POST':
        user_id = session['user_id']
        rating = int(request.form.get('rating'))
        review_text = request.form.get('review_text')

        review_data = {
            'user_id': ObjectId(user_id),
            'type': type,
            'item_id': ObjectId(item_id),
            'rating': rating,
            'review_text': review_text
        }
        reviews_collection.insert_one(review_data)

        flash('Votre avis a été soumis avec succès.', 'success')
        return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)
