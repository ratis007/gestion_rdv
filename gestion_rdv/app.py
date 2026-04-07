from flask import Flask, render_template, request, redirect, session, send_file, flash, g, jsonify
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import sqlite3
import os
import io
import re
import unicodedata
import requests
import pandas as pd

app = Flask(__name__)
app.secret_key = "secret123"

DB_PATH = "database.db"


def init_db(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS agent (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nom TEXT,
        postnom TEXT,
        prenom TEXT,
        sexe TEXT,
        fonction TEXT,
        telephone TEXT
    )""")

    conn.execute("""CREATE TABLE IF NOT EXISTS hotel (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nom_hotel TEXT,
        secteur_activite TEXT,
        province TEXT,
        commune TEXT,
        quartier TEXT,
        adresse_complete TEXT,
        email_proprietaire TEXT,
        personne_contact TEXT,
        telephone_contact TEXT
    )""")

    conn.execute("""CREATE TABLE IF NOT EXISTS rendez_vous (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date_rdv TEXT,
        heure TEXT,
        date_fin TEXT,
        heure_fin TEXT,
        agent_id INTEGER,
        hotel_id INTEGER,
        telephone_contact TEXT,
        etat TEXT
    )""")

    existing_columns = [row[1] for row in conn.execute("PRAGMA table_info(rendez_vous)").fetchall()]
    if 'date_fin' not in existing_columns:
        conn.execute("ALTER TABLE rendez_vous ADD COLUMN date_fin TEXT")
    if 'heure_fin' not in existing_columns:
        conn.execute("ALTER TABLE rendez_vous ADD COLUMN heure_fin TEXT")
    if 'telephone_contact' not in existing_columns:
        conn.execute("ALTER TABLE rendez_vous ADD COLUMN telephone_contact TEXT")
    conn.execute("UPDATE rendez_vous SET date_fin = date_rdv, heure_fin = heure WHERE date_fin IS NULL OR date_fin = ''")
    conn.execute("UPDATE rendez_vous SET heure_fin = time(datetime(date_rdv || 'T' || heure, '+1 hour')) WHERE (heure_fin IS NULL OR heure_fin = '') AND heure IS NOT NULL")

    hotel_columns = [row[1] for row in conn.execute("PRAGMA table_info(hotel)").fetchall()]
    if 'secteur_activite' not in hotel_columns:
        conn.execute("ALTER TABLE hotel ADD COLUMN secteur_activite TEXT")
    if 'province' not in hotel_columns:
        conn.execute("ALTER TABLE hotel ADD COLUMN province TEXT")
    if 'commune' not in hotel_columns:
        conn.execute("ALTER TABLE hotel ADD COLUMN commune TEXT")
    if 'quartier' not in hotel_columns:
        conn.execute("ALTER TABLE hotel ADD COLUMN quartier TEXT")
    if 'adresse_complete' not in hotel_columns:
        conn.execute("ALTER TABLE hotel ADD COLUMN adresse_complete TEXT")
    if 'email_proprietaire' not in hotel_columns:
        conn.execute("ALTER TABLE hotel ADD COLUMN email_proprietaire TEXT")
    if 'personne_contact' not in hotel_columns:
        conn.execute("ALTER TABLE hotel ADD COLUMN personne_contact TEXT")
    if 'telephone_contact' not in hotel_columns:
        conn.execute("ALTER TABLE hotel ADD COLUMN telephone_contact TEXT")
    if 'contact' in hotel_columns and 'telephone_contact' not in hotel_columns:
        conn.execute("UPDATE hotel SET telephone_contact = contact WHERE telephone_contact IS NULL OR telephone_contact = ''")
    if 'adresse' in hotel_columns and 'adresse_complete' not in hotel_columns:
        conn.execute("UPDATE hotel SET adresse_complete = adresse WHERE adresse_complete IS NULL OR adresse_complete = ''")

    conn.execute("""CREATE TABLE IF NOT EXISTS user (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT
    )""")

    conn.commit()

    # Créer un administrateur par défaut (login admin/admin)
    cursor = conn.execute("SELECT COUNT(*) FROM user WHERE username = ?", ("admin",))
    if cursor.fetchone()[0] == 0:
        conn.execute("INSERT INTO user (username, password) VALUES (?, ?)",
                     ("admin", generate_password_hash("admin")))
        conn.commit()



def parse_date_time(value):
    dt = datetime.fromisoformat(value)
    return dt.date().isoformat(), dt.time().strftime('%H:%M')


def default_end(date_str, time_str, minutes=60):
    dt = datetime.fromisoformat(f"{date_str}T{time_str}")
    end = dt + timedelta(minutes=minutes)
    return end.date().isoformat(), end.time().strftime('%H:%M')


def get_db():
    if 'db_conn' in g:
        return g.db_conn

    def remove_bad_db():
        if os.path.exists(DB_PATH):
            try:
                os.remove(DB_PATH)
            except OSError:
                pass

    if os.path.exists(DB_PATH):
        try:
            test_conn = sqlite3.connect(DB_PATH)
            test_conn.execute("PRAGMA integrity_check")
            test_conn.close()
        except sqlite3.DatabaseError:
            try:
                test_conn.close()
            except Exception:
                pass
            remove_bad_db()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        init_db(conn)
    except sqlite3.DatabaseError:
        conn.close()
        remove_bad_db()
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        init_db(conn)

    g.db_conn = conn
    return conn


def normalize_column_name(name):
    if not name:
        return ''
    normalized = unicodedata.normalize('NFKD', str(name)).encode('ascii', 'ignore').decode('ascii')
    normalized = normalized.lower()
    normalized = re.sub(r'[^a-z0-9]+', '_', normalized).strip('_')
    return normalized


@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db_conn', None)
    if db is not None:
        db.close()


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated_function




@app.route('/delete_selected', methods=['POST'])
@login_required
def delete_selected():
    ids = request.form.getlist('delete_ids')
    if not ids:
        flash("Aucun rendez-vous sélectionné.", "warning")
        return redirect('/')

    db = get_db()
    query = "DELETE FROM rendez_vous WHERE id IN ({})".format(','.join('?' * len(ids)))
    db.execute(query, ids)
    db.commit()

    flash(f"{len(ids)} rendez-vous supprimé(s).", "success")
    return redirect('/')


@app.route('/reset_db_page')
@login_required
def reset_db_page():
    return render_template('reset_db.html')


@app.route('/reset_db', methods=['POST'])
@login_required
def reset_db():
    password = request.form.get('password')
    RESET_PASSWORD = "IZI2026@RESET"  # Mot de passe d'authentification

    if password != RESET_PASSWORD:
        flash("Mot de passe incorrect. Réinitialisation refusée.", "danger")
        return redirect('/reset_db_page')

    # fermer la connexion SQLite active avant suppression du fichier
    db_conn = g.pop('db_conn', None)
    if db_conn is not None:
        db_conn.close()

    if os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
        except PermissionError as ex:
            flash("La base est encore utilisée par un autre processus. Veuillez réessayer après fermeture de l'application.", "danger")
            return redirect('/')

    # recréer la base proprement
    db = get_db()
    db.close()

    flash("Base de données réinitialisée avec succès.", "success")
    return redirect('/')


@app.route('/')
@login_required
def index():
    db = get_db()
    total_agents = db.execute("SELECT COUNT(*) FROM agent").fetchone()[0]
    total_hotels = db.execute("SELECT COUNT(*) FROM hotel").fetchone()[0]
    total_rdvs = db.execute("SELECT COUNT(*) FROM rendez_vous").fetchone()[0]
    rdvs_en_attente = db.execute("SELECT COUNT(*) FROM rendez_vous WHERE etat='en_attente'").fetchone()[0]
    return render_template("index.html", total_agents=total_agents, total_hotels=total_hotels, total_rdvs=total_rdvs, rdvs_en_attente=rdvs_en_attente)


@app.route('/agents')
@login_required
def agents():
    db = get_db()
    agents = db.execute("SELECT * FROM agent").fetchall()
    return render_template("agents.html", agents=agents)


@app.route('/hotels')
@login_required
def hotels():
    db = get_db()
    hotels = db.execute("SELECT * FROM hotel").fetchall()
    return render_template("hotels.html", hotels=hotels)


@app.route('/rdvs')
@login_required
def rdvs():
    filter_status = request.args.get('filter', 'all')
    db = get_db()

    if filter_status == 'all':
        rdvs = db.execute("""
            SELECT r.id, r.date_rdv, r.heure, r.date_fin, r.heure_fin, r.etat,
                   r.agent_id, r.hotel_id, r.telephone_contact,
                   a.nom AS nom, a.postnom AS postnom, a.prenom AS prenom,
                   h.nom_hotel AS nom_hotel
            FROM rendez_vous r
            JOIN agent a ON r.agent_id = a.id
            JOIN hotel h ON r.hotel_id = h.id
        """).fetchall()
    else:
        rdvs = db.execute("""
            SELECT r.id, r.date_rdv, r.heure, r.date_fin, r.heure_fin, r.etat,
                   r.agent_id, r.hotel_id, r.telephone_contact,
                   a.nom AS nom, a.postnom AS postnom, a.prenom AS prenom,
                   h.nom_hotel AS nom_hotel
            FROM rendez_vous r
            JOIN agent a ON r.agent_id = a.id
            JOIN hotel h ON r.hotel_id = h.id
            WHERE r.etat = ?
        """, (filter_status,)).fetchall()

    agents = db.execute("SELECT * FROM agent").fetchall()
    hotels = db.execute("SELECT * FROM hotel").fetchall()
    events = [serialize_rdv_event(rdv) for rdv in rdvs]
    return render_template("rdvs.html", rdvs=rdvs, agents=agents, hotels=hotels, filter_status=filter_status, events=events)


def serialize_rdv_event(rdv):
    title = f"{rdv['nom']} {rdv['postnom']} {rdv['prenom']} @ {rdv['nom_hotel']}"
    colors = {
        'en_attente': '#f0ad4e',
        'ok': '#198754',
        'annule': '#dc3545',
        'fait': '#dc3545'
    }
    color = colors.get(rdv['etat'], '#0d6efd')
    end_date = rdv['date_fin'] or rdv['date_rdv']
    end_time = rdv['heure_fin'] or default_end(rdv['date_rdv'], rdv['heure'])[1]
    if end_date == rdv['date_rdv'] and end_time == rdv['heure']:
        end_date, end_time = default_end(rdv['date_rdv'], rdv['heure'])
    return {
        'id': rdv['id'],
        'title': title,
        'start': f"{rdv['date_rdv']}T{rdv['heure']}",
        'end': f"{end_date}T{end_time}",
        'allDay': False,
        'backgroundColor': color,
        'borderColor': color,
        'extendedProps': {
            'etat': rdv['etat'],
            'agent_id': rdv['agent_id'],
            'hotel_id': rdv['hotel_id'],
            'telephone_contact': rdv['telephone_contact'],
            'agent_name': title,
            'hotel_name': rdv['nom_hotel']
        }
    }

@app.route('/api/rdvs')
@login_required
def api_rdvs():
    db = get_db()
    rdvs = db.execute("""
        SELECT r.id, r.date_rdv, r.heure, r.date_fin, r.heure_fin, r.etat,
               r.agent_id, r.hotel_id, r.telephone_contact,
               a.nom, a.postnom, a.prenom,
               h.nom_hotel
        FROM rendez_vous r
        JOIN agent a ON r.agent_id = a.id
        JOIN hotel h ON r.hotel_id = h.id
    """).fetchall()
    events = [serialize_rdv_event(rdv) for rdv in rdvs]
    return jsonify(events)

@app.route('/api/rdvs/create', methods=['POST'])
@login_required
def api_rdvs_create():
    data = request.get_json(force=True)
    required = ['date', 'heure', 'agent_id', 'hotel_id']
    if not all(key in data and data[key] for key in required):
        return jsonify({'success': False, 'message': 'Informations manquantes.'}), 400

    end_date, end_time = default_end(data['date'], data['heure'])
    db = get_db()
    db.execute("""
        INSERT INTO rendez_vous (date_rdv, heure, date_fin, heure_fin, agent_id, hotel_id, telephone_contact, etat)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data['date'], data['heure'], end_date, end_time,
        data['agent_id'], data['hotel_id'], data.get('telephone_contact', ''), data.get('etat', 'en_attente')
    ))
    db.commit()
    rdv_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
    rdv = db.execute("""
        SELECT r.id, r.date_rdv, r.heure, r.date_fin, r.heure_fin, r.etat,
               r.agent_id, r.hotel_id, r.telephone_contact,
               a.nom, a.postnom, a.prenom,
               h.nom_hotel
        FROM rendez_vous r
        JOIN agent a ON r.agent_id = a.id
        JOIN hotel h ON r.hotel_id = h.id
        WHERE r.id = ?
    """, (rdv_id,)).fetchone()
    return jsonify({'success': True, 'event': serialize_rdv_event(rdv)})

@app.route('/add_rdv_ajax', methods=['POST'])
@login_required
def add_rdv_ajax():
    data = request.get_json(force=True)
    required = ['date', 'heure', 'agent_id', 'hotel_id']
    if not all(data.get(key) for key in required):
        return jsonify({'success': False, 'message': 'Informations manquantes.'}), 400

    end_date, end_time = default_end(data['date'], data['heure'])
    db = get_db()
    db.execute("""
        INSERT INTO rendez_vous (date_rdv, heure, date_fin, heure_fin, agent_id, hotel_id, telephone_contact, etat)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data['date'], data['heure'], end_date, end_time,
        data['agent_id'], data['hotel_id'], data.get('telephone_contact', ''), 'en_attente'
    ))
    db.commit()
    rdv_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]

    agent = db.execute("SELECT nom, postnom, prenom FROM agent WHERE id = ?", (data['agent_id'],)).fetchone()
    hotel = db.execute("SELECT nom_hotel FROM hotel WHERE id = ?", (data['hotel_id'],)).fetchone()
    title = f"{agent['nom']} {agent['postnom']} {agent['prenom']} - {hotel['nom_hotel']}"

    return jsonify({
        'success': True,
        'event': {
            'id': rdv_id,
            'title': title,
            'start': data['date'] + 'T' + data['heure'],
            'backgroundColor': '#f0ad4e',
            'borderColor': '#f0ad4e',
            'extendedProps': {
                'etat': 'en_attente',
                'agent_id': data['agent_id'],
                'hotel_id': data['hotel_id'],
                'telephone_contact': data.get('telephone_contact', '')
            }
        }
    })

@app.route('/api/rdvs/update/<int:id>', methods=['POST'])
@login_required
def api_rdvs_update(id):
    data = request.get_json(force=True)
    fields = []
    values = []

    if 'start' in data and data['start']:
        start_date, start_time = parse_date_time(data['start'])
        fields.append('date_rdv = ?')
        values.append(start_date)
        fields.append('heure = ?')
        values.append(start_time)

    if 'end' in data and data['end']:
        end_date, end_time = parse_date_time(data['end'])
        fields.append('date_fin = ?')
        values.append(end_date)
        fields.append('heure_fin = ?')
        values.append(end_time)

    mapping = {
        'date': 'date_rdv',
        'heure': 'heure',
        'date_fin': 'date_fin',
        'heure_fin': 'heure_fin',
        'telephone_contact': 'telephone_contact',
        'etat': 'etat',
        'agent_id': 'agent_id',
        'hotel_id': 'hotel_id'
    }
    for key, column in mapping.items():
        if key in data and data[key] is not None and data[key] != '':
            fields.append(f"{column} = ?")
            values.append(data[key])

    if not fields:
        return jsonify({'success': False, 'message': 'Aucune mise à jour fournie.'}), 400
    values.append(id)
    db = get_db()
    db.execute(f"UPDATE rendez_vous SET {', '.join(fields)} WHERE id = ?", values)
    db.commit()
    rdv = db.execute("""
        SELECT r.id, r.date_rdv, r.heure, r.date_fin, r.heure_fin, r.etat,
               r.agent_id, r.hotel_id, r.telephone_contact,
               a.nom, a.postnom, a.prenom,
               h.nom_hotel
        FROM rendez_vous r
        JOIN agent a ON r.agent_id = a.id
        JOIN hotel h ON r.hotel_id = h.id
        WHERE r.id = ?
    """, (id,)).fetchone()
    if not rdv:
        return jsonify({'success': False, 'message': 'Rendez-vous non trouvé.'}), 404
    return jsonify({'success': True, 'event': serialize_rdv_event(rdv)})

@app.route('/api/rdvs/delete/<int:id>', methods=['POST'])
@login_required
def api_rdvs_delete(id):
    db = get_db()
    db.execute("DELETE FROM rendez_vous WHERE id = ?", (id,))
    db.commit()
    return jsonify({'success': True})

# ➜ Ajouter agent
@app.route('/add_agent', methods=['POST'])
@login_required
def add_agent():
    data = request.form
    db = get_db()
    db.execute("""
        INSERT INTO agent (nom, postnom, prenom, sexe, fonction, telephone)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (data['nom'], data['postnom'], data['prenom'], data['sexe'], data['fonction'], data['telephone']))
    db.commit()
    flash("Agent ajouté avec succès.", "success")
    return redirect('/agents')


# ➜ Ajouter hôtel
@app.route('/add_hotel', methods=['POST'])
@login_required
def add_hotel():
    data = request.form
    db = get_db()
    db.execute("""
        INSERT INTO hotel (
            nom_hotel, secteur_activite, province, commune, quartier,
            adresse_complete, email_proprietaire, personne_contact, telephone_contact
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data.get('nom_hotel'),
        data.get('secteur_activite'),
        data.get('province'),
        data.get('commune'),
        data.get('quartier'),
        data.get('adresse_complete'),
        data.get('email_proprietaire'),
        data.get('personne_contact'),
        data.get('telephone_contact')
    ))
    db.commit()
    flash("Hôtel ajouté avec succès.", "success")
    return redirect('/hotels')


@app.route('/import_hotels_excel', methods=['POST'])
@login_required
def import_hotels_excel():
    file = request.files.get('excel_file')
    if not file or file.filename == '':
        flash("Aucun fichier sélectionné.", "warning")
        return redirect('/hotels')

    try:
        df = pd.read_excel(file)
    except Exception as error:
        flash(f"Impossible de lire le fichier Excel : {error}", "danger")
        return redirect('/hotels')

    if df.empty:
        flash("Le fichier Excel est vide.", "warning")
        return redirect('/hotels')

    column_map = {
        'nom': 'nom_hotel',
        'nom_hotel': 'nom_hotel',
        'nom_de_l_etablissement': 'nom_hotel',
        'nom_de_letablissement': 'nom_hotel',
        'hotel': 'nom_hotel',
        'secteur_d_activite': 'secteur_activite',
        'secteur_activite': 'secteur_activite',
        'province': 'province',
        'commune': 'commune',
        'quartier': 'quartier',
        'adresse_complete': 'adresse_complete',
        'adresse': 'adresse_complete',
        'email': 'email_proprietaire',
        'email_proprietaire': 'email_proprietaire',
        'personne_contact': 'personne_contact',
        'contact': 'personne_contact',
        'telephone': 'telephone_contact',
        'telephone_contact': 'telephone_contact',
        'tel': 'telephone_contact'
    }

    normalized_columns = {normalize_column_name(col): col for col in df.columns}
    mapped_columns = {}
    for normalized_name, original_name in normalized_columns.items():
        if normalized_name in column_map:
            mapped_columns[column_map[normalized_name]] = original_name

    if 'nom_hotel' not in mapped_columns:
        flash("Le fichier Excel doit contenir une colonne Nom de l’établissement.", "danger")
        return redirect('/hotels')

    def clean_value(value):
        if pd.isna(value):
            return ''
        return str(value).strip()

    fields = [
        'nom_hotel', 'secteur_activite', 'province', 'commune',
        'quartier', 'adresse_complete', 'email_proprietaire',
        'personne_contact', 'telephone_contact'
    ]

    inserted = 0
    skipped = 0
    db = get_db()

    for _, row in df.iterrows():
        values = []
        for field in fields:
            source_column = mapped_columns.get(field)
            if source_column and source_column in row:
                values.append(clean_value(row[source_column]))
            else:
                values.append('')

        if not values[0].strip():
            skipped += 1
            continue

        db.execute("""
            INSERT INTO hotel (
                nom_hotel, secteur_activite, province, commune, quartier,
                adresse_complete, email_proprietaire, personne_contact, telephone_contact
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, tuple(values))
        inserted += 1

    db.commit()
    flash(f"Import terminé : {inserted} hôtel(s) ajoutés, {skipped} ignoré(s).", "success")
    return redirect('/hotels')


@app.route('/edit_hotel/<int:id>')
@login_required
def edit_hotel(id):
    db = get_db()
    hotel = db.execute("SELECT * FROM hotel WHERE id = ?", (id,)).fetchone()
    if not hotel:
        flash("Hôtel introuvable.", "warning")
        return redirect('/hotels')
    return render_template('edit_hotel.html', hotel=hotel)


@app.route('/update_hotel/<int:id>', methods=['POST'])
@login_required
def update_hotel(id):
    data = request.form
    db = get_db()
    db.execute("""
        UPDATE hotel SET
            nom_hotel = ?,
            secteur_activite = ?,
            province = ?,
            commune = ?,
            quartier = ?,
            adresse_complete = ?,
            email_proprietaire = ?,
            personne_contact = ?,
            telephone_contact = ?
        WHERE id = ?
    """, (
        data.get('nom_hotel'),
        data.get('secteur_activite'),
        data.get('province'),
        data.get('commune'),
        data.get('quartier'),
        data.get('adresse_complete'),
        data.get('email_proprietaire'),
        data.get('personne_contact'),
        data.get('telephone_contact'),
        id
    ))
    db.commit()
    flash("Hôtel mis à jour avec succès.", "success")
    return redirect('/hotels')


@app.route('/edit_agent/<int:id>')
@login_required
def edit_agent(id):
    db = get_db()
    agent = db.execute("SELECT * FROM agent WHERE id = ?", (id,)).fetchone()
    if not agent:
        flash("Agent introuvable.", "warning")
        return redirect('/agents')
    return render_template('edit_agent.html', agent=agent)


@app.route('/update_agent/<int:id>', methods=['POST'])
@login_required
def update_agent(id):
    data = request.form
    db = get_db()
    db.execute("""
        UPDATE agent SET
            nom = ?,
            postnom = ?,
            prenom = ?,
            sexe = ?,
            fonction = ?,
            telephone = ?
        WHERE id = ?
    """, (
        data.get('nom'),
        data.get('postnom'),
        data.get('prenom'),
        data.get('sexe'),
        data.get('fonction'),
        data.get('telephone'),
        id
    ))
    db.commit()
    flash("Agent mis à jour avec succès.", "success")
    return redirect('/agents')


# ➜ Ajouter rendez-vous
@app.route('/add_rdv', methods=['POST'])
@login_required
def add_rdv():
    data = request.form
    db = get_db()
    end_date = data.get('date_fin') or data['date']
    end_time = data.get('heure_fin')
    if not end_time:
        end_date, end_time = default_end(data['date'], data['heure'])

    db.execute("""
        INSERT INTO rendez_vous (date_rdv, heure, date_fin, heure_fin, agent_id, hotel_id, etat)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        data['date'], data['heure'], end_date, end_time,
        data['agent_id'], data['hotel_id'], "en_attente"
    ))
    db.commit()
    flash("Rendez-vous créé avec succès.", "success")
    return redirect('/rdvs')


@app.route('/delete_agent/<int:id>')
@login_required
def delete_agent(id):
    db = get_db()
    db.execute("DELETE FROM agent WHERE id=?", (id,))
    db.commit()
    flash("Agent supprimé.", "info")
    return redirect('/agents')


@app.route('/delete_agents_bulk', methods=['POST'])
@login_required
def delete_agents_bulk():
    ids = request.form.getlist('selected_ids')
    if not ids:
        flash("Aucun agent sélectionné.", "warning")
        return redirect('/agents')

    db = get_db()
    query = "DELETE FROM agent WHERE id IN ({})".format(','.join('?' * len(ids)))
    db.execute(query, ids)
    db.commit()

    flash(f"{len(ids)} agent(s) supprimé(s).", "success")
    return redirect('/agents')


@app.route('/delete_hotel/<int:id>')
@login_required
def delete_hotel(id):
    db = get_db()
    db.execute("DELETE FROM hotel WHERE id=?", (id,))
    db.commit()
    flash("Hôtel supprimé.", "info")
    return redirect('/hotels')


@app.route('/delete_hotels_bulk', methods=['POST'])
@login_required
def delete_hotels_bulk():
    ids = request.form.getlist('selected_ids')
    if not ids:
        flash("Aucun hôtel sélectionné.", "warning")
        return redirect('/hotels')

    db = get_db()
    query = "DELETE FROM hotel WHERE id IN ({})".format(','.join('?' * len(ids)))
    db.execute(query, ids)
    db.commit()

    flash(f"{len(ids)} hôtel(s) supprimé(s).", "success")
    return redirect('/hotels')


@app.route('/delete_rdv/<int:id>')
@login_required
def delete_rdv(id):
    db = get_db()
    db.execute("DELETE FROM rendez_vous WHERE id=?", (id,))
    db.commit()
    flash("Rendez-vous supprimé.", "info")
    return redirect('/')


@app.route('/valider/<int:id>')
@login_required
def valider(id):
    db = get_db()
    db.execute("UPDATE rendez_vous SET etat='ok' WHERE id=?", (id,))
    db.commit()
    flash("Rendez-vous validé.", "success")
    return redirect('/')


@app.route('/annuler/<int:id>')
@login_required
def annuler(id):
    db = get_db()
    db.execute("UPDATE rendez_vous SET etat='annule' WHERE id=?", (id,))
    db.commit()
    flash("Rendez-vous annulé.", "warning")
    return redirect('/')


@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        user = request.form['username']
        pwd = request.form['password']

        db = get_db()
        user_data = db.execute("SELECT * FROM user WHERE username=?", (user,)).fetchone()

        if user_data and check_password_hash(user_data['password'], pwd):
            session['user'] = user
            flash("Connexion réussie.", "success")
            return redirect('/')
        else:
            flash("Nom d'utilisateur ou mot de passe incorrect.", "danger")

    return render_template("login.html")


@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect('/login')


def send_sms(numero, message):
    url = "https://api.orange.com/smsmessaging/v1/outbound/tel:+243XXXXXXXX/requests"

    headers = {
        "Authorization": "Bearer TON_TOKEN",
        "Content-Type": "application/json"
    }

    data = {
        "outboundSMSMessageRequest": {
            "address": f"tel:{numero}",
            "outboundSMSTextMessage": {
                "message": message
            }
        }
    }

    requests.post(url, json=data, headers=headers)

@app.route('/send_sms', methods=['GET','POST'])
@login_required
def send_sms_route():
    if request.method == 'POST':
        numero = request.form.get('numero')
        message = request.form.get('message')
        send_sms(numero, message)
        flash("SMS envoye avec succes.", "success")
        return redirect('/')
    return render_template('send_sms.html')


@app.route('/export')
@login_required
def export():
    db = get_db()
    # Récupère les RDV avec les informations d'agent et hôtel dans l'ordre requis
    data = db.execute("""
        SELECT r.date_rdv, r.heure,
               a.nom || ' ' || a.postnom || ' ' || a.prenom,
               h.nom_hotel,
               r.etat
        FROM rendez_vous r
        JOIN agent a ON r.agent_id = a.id
        JOIN hotel h ON r.hotel_id = h.id
        ORDER BY r.date_rdv DESC, r.heure DESC
    """).fetchall()

    # Crée le DataFrame avec les colonnes dans l'ordre spécifié
    df = pd.DataFrame(data, columns=["Date", "Heure", "Nom de l'agent", "Nom de l'hôtel", "État"])

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='RDV')
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name='rdv.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )


@app.errorhandler(404)
def not_found(error):
    return render_template('404.html'), 404


@app.errorhandler(500)
def internal_error(error):
    return render_template('500.html'), 500


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)

