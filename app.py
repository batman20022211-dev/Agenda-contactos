# Flask-Login lleva las sesiones y werkzeug cuida las contraseñas.
import base64  # convierte las fotos en texto (base64) para guardarlas en la base
import os  # lee variables de entorno
import re  # para revisar que el teléfono tenga 10 números

from flask import Flask, render_template, request, redirect, url_for, flash  # lo básico: páginas, formularios, redirecciones y mensajitos
from flask_sqlalchemy import SQLAlchemy  # el traductor entre python y la base de datos
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user  # sesiones: quién entró, quién salió y quien no pasa sin login
from werkzeug.security import generate_password_hash, check_password_hash  # encripta y compara contraseñas
from sqlalchemy import inspect, text  # inspect revisa las columnas de la tabla text nos deja escribir SQL a mano

app = Flask(__name__)  # crea la aplicacion, aqui arranca todo

# clave secreta
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "clave-para-no-se-que-pero-vi-que-se-necesita")

# si existe DATABASE_URL usa postgresql si no usa sqlite
db_url = os.environ.get("DATABASE_URL", "sqlite:///agenda.db")
if db_url.startswith("postgres://"):
    # algunos servicios dan la URL con "postgres://" y SQLAlchemy quiere "postgresql+psycopg2://"
    db_url = db_url.replace("postgres://", "postgresql+psycopg2://", 1)
elif db_url.startswith("postgresql://"):
    # Neon da la URL como "postgresql://", así que también la pasamos a psycopg2
    db_url = db_url.replace("postgresql://", "postgresql+psycopg2://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = db_url

# 2 mb por imagen
# si alguien intenta subir algo mas grande, flask lo rechaza con error 413 (archivo muy pesado)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024

db = SQLAlchemy(app)  # conecta SQLAlchemy con la app

login_manager = LoginManager(app)  # activa el sistema de login en la app
login_manager.login_view = "login"  # si alguien sin sesion entra a una pagina protegida, se regresa al login
login_manager.login_message = "Inicia sesión para ver tu agenda."  # el mensajito que aparece

# imagen permitidas
# tipos de archivo que acepta
TIPOS_IMAGEN = ("image/png", "image/jpeg", "image/gif", "image/webp")

# lada de pais para el selector
CODIGOS = [
    ("+52", "México (+52)"),
    ("+1", "EE.UU./Canadá (+1)"),
    ("+34", "España (+34)"),
    ("+54", "Argentina (+54)"),
    ("+57", "Colombia (+57)"),
    ("+56", "Chile (+56)"),
    ("+51", "Perú (+51)"),
    ("+502", "Guatemala (+502)"),
]

# categorías de contacto (las que aparecen en el formulario y en los filtros)
# si agregas una aqui, aparece sola en el formulario y en los filtros
CATEGORIAS = ["Familia", "Escuela", "Trabajo", "Otro"]



class Usuario(UserMixin, db.Model):
    # cada persona que se registra en la app (es una tabla en la base)
    # UserMixin le regala a la clase las cosas que Flask-Login necesita, asi no se tiene que escribir a mano
    # nombre_usuario no se puede repetir (no hay dos "usuario1" en el mismo sistema),
    # y password_hash guarda la contraseña ya revuelta con encriptacion
    id = db.Column(db.Integer, primary_key=True)  # numero unico de cada usuario, lo asigna la base solita
    nombre_usuario = db.Column(db.String(50), unique=True, nullable=False)# unique=True: nadie puede repetir nombre
    password_hash = db.Column(db.String(255), nullable=False)# aqui va el hash, nunca la contraseña tal cual


class Contacto(db.Model):
    # un contacto de la agenda pertenece a un usuario.
    id = db.Column(db.Integer, primary_key=True)  # numero unico de cada contacto
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuario.id"), nullable=False)  # de quien es este contacto
    nombre = db.Column(db.String(100), nullable=False)
    codigo_pais = db.Column(db.String(6), default="+52")  # por defecto +52, porque creo que si estamos en México
    telefono = db.Column(db.String(20), nullable=False)  # texto y no número, para no perder el cero de la izquierda
    correo = db.Column(db.String(120), nullable=False)  # obligatorio si no se pone pues no se crea el contacto 
    categoria = db.Column(db.String(20), nullable=False, default="Otro") # familia, escuela, trabajo u otro, como dice ahi, por defecto "Otro"
    imagen = db.Column(db.Text, nullable=True) # La imagen se guarda como base64 (texto largo)


@login_manager.user_loader
def cargar_usuario(user_id):
    # Flask-Login la llama en cada peticion para saber quien es el usuario segun el id guardado en la sesión
    return db.session.get(Usuario, int(user_id))



def buscar_contacto(id):
    # busca un contacto del usuario actual.
    return Contacto.query.filter_by(id=id, usuario_id=current_user.id).first_or_404()


def llenar_contacto(contacto, form, archivo):
    # sacamos los datos del formulario y les quitamos los espacios sobrantes con strip()
    contacto.nombre = form.get("nombre", "").strip()
    contacto.codigo_pais = form.get("codigo_pais", "+52")
    contacto.telefono = form.get("telefono", "").strip()
    contacto.correo = form.get("correo", "").strip()
    contacto.categoria = form.get("categoria", "Otro")

    # revisamos que no vengan campos vacios (los espacios ya se fueron, asi que "   " cuenta como vacio)
    if not (contacto.nombre and contacto.telefono and contacto.correo):
        return "Llena nombre, teléfono y correo."

    # el teléfono solo puede tener 10 números (sin espacios ni letras)
    if not re.fullmatch(r"[0-9]{10}", contacto.telefono):
        return "El teléfono debe tener exactamente 10 números."

    if contacto.categoria not in CATEGORIAS:
        return "Elige una categoría válida."

    # si subieron una imagen nueva se convierte a base64
    if archivo and archivo.filename:
        # primero revisamos que sea imagen de verdad
        if archivo.mimetype not in TIPOS_IMAGEN:
            return "Solo se permiten imágenes PNG, JPG, GIF o WEBP."
        # leemos la foto y la convertimos a texto para guardarla en la base
        datos = base64.b64encode(archivo.read()).decode("utf-8")
        contacto.imagen = f"data:{archivo.mimetype};base64,{datos}"

    # un contacto nuevo siempre necesita imagen
    # (si ya tenia una de antes y no subieron otra, se queda la que tenia)
    if not contacto.imagen:
        return "Sube una imagen para el contacto."

    return None  # todo bien, ningun error (None es "nada que reportar")


@app.route("/login", methods=["GET", "POST"])
def login():
    # GET: muestra el formulario de login.
    # POST: busca el usuario y compara la contraseña con su hash. Si todo bien, adentro, si no, mensaje de error
    if request.method == "POST":
        usuario = Usuario.query.filter_by(nombre_usuario=request.form.get("nombre_usuario", "").strip()).first()
        if usuario and check_password_hash(usuario.password_hash, request.form.get("password", "")):
            login_user(usuario)  # le damos sesión a la persona
            return redirect(url_for("index"))
        # mensaje generico
        flash("Usuario o contraseña incorrectos.")
    return render_template("login.html")


@app.route("/registro", methods=["GET", "POST"])
def registro():
    # GET: muestra el formulario de registro.
    # POST: crea el usuario nuevo si cumple las reglas (nombre obligatorio, contraseña de 6 caracteres o mas, y nombre no repetido)
    if request.method == "POST":
        nombre = request.form.get("nombre_usuario", "").strip()
        password = request.form.get("password", "")

        if not nombre or len(password) < 6:
            flash("El usuario es obligatorio y la contraseña debe tener al menos 6 caracteres.")
        elif Usuario.query.filter_by(nombre_usuario=nombre).first():
            flash("Ese nombre de usuario ya existe.")  # ya hay alguien con ese nombre, toca elegir otro
        else:
            # la contraseña se guarda encriptada, nunca como se escribio
            usuario = Usuario(nombre_usuario=nombre, password_hash=generate_password_hash(password))
            db.session.add(usuario)  # lo metemos a la sesión de la base
            db.session.commit()  # y lo guardamos de verdad
            login_user(usuario)  # entra directo despues de registrarse
            return redirect(url_for("index"))

    return render_template("registro.html")


@app.route("/logout")
@login_required  # si no hay sesion, ni tiene caso cerrarla
def logout():
    # cierra la sesión y te manda de regreso al login
    logout_user()
    return redirect(url_for("login"))



@app.route("/")
@login_required  # la agenda es privada osea primero login
def index():
    # pagina principal, la lista de contactos
    # acepta filtros por la URL: ?q=texto para buscar y ?cat=Familia para filtrar por categoría (o algo asi)
    q = request.args.get("q", "").strip()  # lo que escribió en el buscador
    cat = request.args.get("cat", "").strip()  # la categoria elegida en el filtro

    # contactos del usuario actual
    consulta = Contacto.query.filter_by(usuario_id=current_user.id)

    # filtro por categoria
    if cat in CATEGORIAS:
        consulta = consulta.filter_by(categoria=cat)

    # buscador, busca en nombre, telefono o correo ilike no le hace caso a mayusculas ni minusculas
    if q:
        patron = f"%{q}%"  # el % significa "lo que sea", así que busca el texto en cualquier parte
        consulta = consulta.filter(
            db.or_(
                Contacto.nombre.ilike(patron),
                Contacto.telefono.ilike(patron),
                Contacto.correo.ilike(patron),
            )
        )

    # ordenados por nombre, como agenda de papel .all() ya los trae de la base
    contactos = consulta.order_by(Contacto.nombre).all()
    return render_template("agenda.html", contactos=contactos, q=q, cat=cat, categorias=CATEGORIAS)


@app.route("/contacto/nuevo", methods=["GET", "POST"])
@login_required
def nuevo_contacto():
    # GET: muestra el formulario vacío
    # POST: intenta guardar el contacto nuevo
    if request.method == "POST":
        # creamos el objeto del contacto, todavía no se guarda en la base
        contacto = Contacto(usuario_id=current_user.id)
        error = llenar_contacto(contacto, request.form, request.files.get("imagen"))
        if error:
            flash(error)  # si algo fallo, mensajito y se queda en el formulario
        else:
            db.session.add(contacto)  # lo metemos a la sesion
            db.session.commit()  # y ahora si, a la base de datos
            flash("Contacto guardado")  # mensaje de éxito
            return redirect(url_for("index"))

    # en GET o con error, vuelve a mostrar el formulario
    return render_template("contacto_form.html", titulo="Nuevo contacto", contacto=None,
                           codigos=CODIGOS, categorias=CATEGORIAS)


@app.route("/contacto/<int:id>/editar", methods=["GET", "POST"])
@login_required
def editar_contacto(id):
    # igual que "nuevo", pero primero trae el contacto que ya existe
    contacto = buscar_contacto(id)
    if request.method == "POST":
        error = llenar_contacto(contacto, request.form, request.files.get("imagen"))
        if error:
            flash(error)
        else:
            db.session.commit()  # como el contacto ya estaba en la base, con commit basta para guardar los cambios
            flash("Cambios guardados")
            return redirect(url_for("index"))

    return render_template("contacto_form.html", titulo="Editar contacto", contacto=contacto,
                           codigos=CODIGOS, categorias=CATEGORIAS)


@app.route("/contacto/<int:id>/eliminar", methods=["POST"])
@login_required
def eliminar_contacto(id):
    # borra el contacto. Solo acepta POST
    contacto = buscar_contacto(id)
    db.session.delete(contacto)  # lo marcamos para borrar
    db.session.commit()  # y se borra de verdad
    flash("Contacto eliminado :)")
    return redirect(url_for("index"))


def migrar_base():
    # agrega la columna "categoria" si la base de datos ya existía sin ella.
    # inspect lee las columnas actuales, si falta "categoria", la agregamos con SQL
    columnas = [c["name"] for c in inspect(db.engine).get_columns("contacto")]
    if "categoria" not in columnas:
        with db.engine.begin() as conexion:  # abre una conexion y hace commit al terminar
            conexion.execute(text(
                "ALTER TABLE contacto ADD COLUMN categoria VARCHAR(20) NOT NULL DEFAULT 'Otro'"
            ))


# crea las tablas al iniciar y revisa que la base este actualizada
# create_all solo crea las tablas que no existan, las que ya estan pues no las molesta
with app.app_context():  # necesitamos el "contexto" de la app para tocar la base fuera de una petición
    db.create_all()
    migrar_base()


if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)
