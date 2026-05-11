from flask import Flask, flash, render_template, request, redirect, url_for, make_response
import plotly
import plotly.graph_objects as go
import json
import sqlite3
import csv
import io
from datetime import datetime

# Inicializamos la aplicación Flask
app = Flask(__name__)

# Opcional: Desactivamos el caché para ver los cambios de inmediato
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

@app.after_request
def no_cache(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

# --- Funciones de la base de datos ---

def get_db_connection():
    """
    Establece la conexión a la base de datos SQLite.
    Crea la tabla si no existe.
    """
    conn = sqlite3.connect('gastos.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS registros (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo TEXT NOT NULL,
            categoria TEXT NOT NULL,
            fecha TEXT NOT NULL,
            monto REAL NOT NULL                  
        )
    ''')
    conn.commit()
    return conn


def normalize_date(date_str):
    """
    Normaliza una fecha a formato YYYY-MM-DD.
    Intenta parsear con varios formatos comunes.
    """
    if not date_str:
        raise ValueError("Fecha vacía")
    
    formats = [
        '%Y-%m-%d',  # Ya en el formato deseado
        '%d/%m/%Y',  # DD/MM/YYYY
        '%m/%d/%Y',  # MM/DD/YYYY
        '%Y/%m/%d',  # YYYY/MM/DD
        '%d-%m-%Y',  # DD-MM-YYYY
        '%m-%d-%Y',  # MM-DD-YYYY
    ]
    
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return dt.strftime('%Y-%m-%d')
        except ValueError:
            continue
    
    raise ValueError(f"Formato de fecha no reconocido: {date_str}")


def normalize_tipo(tipo_str):
    """
    Normaliza el tipo de registro a 'Ingreso' o 'Gasto'.
    Acepta variaciones en mayúsculas/minúsculas.
    """
    if not tipo_str:
        raise ValueError("Tipo vacío")
    
    tipo_lower = tipo_str.lower().strip()
    if tipo_lower in ['ingreso', 'ingresos', 'income', 'ing']:
        return 'Ingreso'
    elif tipo_lower in ['gasto', 'gastos', 'expense', 'exp']:
        return 'Gasto'
    else:
        raise ValueError(f"Tipo no reconocido: {tipo_str}")


# --- Rutas de la aplicación ---
# descarga el template para subir registros
@app.route("/download-template", methods=["GET"])
def download_template():
    """
    Descarga un CSV vacío con los encabezados de la tabla registros.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(registros)")
    columnas = [row["name"] for row in cursor.fetchall() if row["name"] != "id"]
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(columnas)
    contenido_csv = "\ufeff" + output.getvalue()  # BOM para compatibilidad con Excel

    response = make_response(contenido_csv)
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = "attachment; filename=template_registros.csv"
    return response

# descarga todos los registros de la tabla registros en un CSV, incluyendo el id y con todos los campos
@app.route("/download-registros", methods=["GET"])
def download_registros():
    """
    Descarga un CSV con todos los registros de la tabla registros.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(registros)")
    registros_completos = [row["name"] for row in cursor.fetchall() if row["name"]]
    cursor.execute("SELECT * FROM registros")
    registros = cursor.fetchall()   
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(registros_completos)
    writer.writerows([tuple(row) for row in registros])
    contenido_csv2 = "\ufeff" + output.getvalue()  # BOM para compatibilidad con Excel

    response = make_response(contenido_csv2)
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = "attachment; filename=bulk_registros.csv"
    return response



@app.route("/", methods=["GET", "POST"])
def index():
    """
    Maneja las peticiones GET y POST para la página principal.
    GET: Muestra el formulario y los registros.
    POST: Procesa los datos del formulario y los guarda en la base de datos.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    id_registro = None   #  siempre inicializado

    # --- POST: Insertar o Eliminar ---
    if request.method == "POST":
        archivo_bulk = request.files.get("bulk_file")
        if archivo_bulk and archivo_bulk.filename:
            try:
                contenido = archivo_bulk.stream.read().decode("utf-8-sig")
            except UnicodeDecodeError:
                conn.close()
                return redirect(url_for("index"))

            lector = csv.DictReader(io.StringIO(contenido))
            filas_a_insertar = []

            for fila in lector:
                tipo = (fila.get("tipo") or "").strip()
                categoria = (fila.get("categoria") or "").strip()
                fecha = (fila.get("fecha") or "").strip()
                monto_texto = (fila.get("monto") or "").strip()

                # Salta filas completamente vacias
                if not any([tipo, categoria, fecha, monto_texto]):
                    continue    

                try:
                    tipo = normalize_tipo(tipo)
                except ValueError:
                    continue

                if not categoria or categoria.isdigit() or not fecha:
                    continue

                try:
                    monto = float(monto_texto)
                except (ValueError, TypeError):
                    continue

                if monto == 0.0:
                    continue

                try:
                    fecha_normalizada = normalize_date(fecha)
                except ValueError:
                    continue

                filas_a_insertar.append((tipo, categoria, fecha_normalizada, monto))

            if filas_a_insertar:
                cursor.executemany(
                    "INSERT INTO registros (tipo, categoria, fecha, monto) VALUES (?, ?, ?, ?)",
                    filas_a_insertar
                )
                conn.commit()

            conn.close()
            return redirect(url_for("index"))

        id_registro = request.form.get("id")

        if id_registro:
            # Eliminar registro
            cursor.execute("DELETE FROM registros WHERE id = ?", (id_registro,))
            conn.commit()
            conn.close()
            return redirect(url_for("index"))
        else:
            # Insertar registro
            tipo = request.form.get("tipo_registro")
            try:
                tipo = normalize_tipo(tipo)
            except ValueError:
                conn.close()
                return redirect(url_for("index"))
            
            categoria = request.form.get("categoria", "").strip()
            categoria_desplegable = request.form.get("categoria_desplegable", "").strip()
            categoria_final = categoria if categoria else categoria_desplegable
            fecha = request.form.get("fecha")
            monto_str = request.form.get("monto")            
            

            # Validación categoría
            if not categoria_final or categoria_final.isdigit():
                print("ERROR: La categoría no es válida.")
                conn.close()
                return redirect(url_for("index"))

            # Validación monto
            try:
                monto = float(monto_str)
            except (ValueError, TypeError):
                monto = 0.0

            if monto != 0.0:
                try:
                    fecha_normalizada = normalize_date(fecha)
                except ValueError:
                    conn.close()
                    return redirect(url_for("index"))
                
                cursor.execute(
                    "INSERT INTO registros (tipo, categoria, fecha, monto) VALUES (?, ?, ?, ?)",
                    (tipo, categoria_final, fecha_normalizada, monto)
                )
                conn.commit()           

            conn.close()
            return redirect(url_for("index"))

    # --------------------------- GET: Mostrar registros con filtros -------------------------------------------#
    fecha_inicio = request.args.get("fecha_inicio")
    fecha_fin = request.args.get("fecha_fin")
    categoria_filtro = request.args.get("categoria_filtro")
    tipo_registro_fil = request.args.get("tipo_registro_fil")
    limit = request.args.get("limit")

    # Normalizar fechas de filtro
    if fecha_inicio:
        try:
            fecha_inicio = normalize_date(fecha_inicio)
        except ValueError:
            fecha_inicio = None
    
    if fecha_fin:
        try:
            fecha_fin = normalize_date(fecha_fin)
        except ValueError:
            fecha_fin = None

    query = "SELECT * FROM registros"
    query_ingresos = "SELECT SUM(monto) FROM registros WHERE tipo = 'Ingreso'"
    query_gastos = "SELECT SUM(monto) FROM registros WHERE tipo = 'Gasto'"
    


    condiciones = []
    parametros = []

    if tipo_registro_fil:
        condiciones.append("tipo = ?")
        parametros.append(tipo_registro_fil)

    if categoria_filtro:
        condiciones.append("categoria = ?")
        parametros.append(categoria_filtro)

    if fecha_inicio and fecha_fin:
        condiciones.append("fecha BETWEEN ? AND ?")
        parametros.append(fecha_inicio)
        parametros.append(fecha_fin)

    if condiciones:
        query += " WHERE " + " AND ".join(condiciones)

    if condiciones:
        query_ingresos += " AND " + " AND ".join(condiciones)
        query_gastos += " AND " + " AND ".join(condiciones)
    
    if limit == "25":
        query += " ORDER BY id DESC LIMIT 25"
    elif limit == "50":
        query += " ORDER BY id DESC LIMIT 50"
    elif limit == "100":
        query += " ORDER BY id DESC LIMIT 100"
    elif limit == "all":
        query += " ORDER BY id DESC"   # sin límite
    else:
        query += " ORDER BY id DESC LIMIT 15"  # valor por defecto

    # Totales
    cursor.execute(query_ingresos, parametros)
    total_ingresos = cursor.fetchone()[0] or 0

    cursor.execute(query_gastos, parametros)
    total_gastos = cursor.fetchone()[0] or 0

    cursor.execute(query, parametros)
    registros = cursor.fetchall()
    



    # Datos para gráficos de líneas - Ingresos y Gastos por fecha #

    # --- Datos dinÃ¡micos para el grÃ¡fico de líneas ---
    
    # 1. Definimos las consultas base
    query_ingresos_linea = """
        SELECT fecha, SUM(monto) AS total
        FROM registros
        WHERE tipo = 'Ingreso'
    """
    query_gastos_linea = """
        SELECT fecha, SUM(monto) AS total
        FROM registros
        WHERE tipo = 'Gasto'
    """

    # 2. Preparamos los parámetros comunes (Categoría y Fechas)
    parametros_linea = []

    # -- Filtro Categoría --
    if categoria_filtro:
        adicional = " AND categoria = ?"
        query_ingresos_linea += adicional
        query_gastos_linea += adicional
        parametros_linea.append(categoria_filtro)

    # -- Filtro Fechas --
    if fecha_inicio and fecha_fin:
        adicional = " AND fecha BETWEEN ? AND ?"
        query_ingresos_linea += adicional
        query_gastos_linea += adicional
        parametros_linea.extend([fecha_inicio, fecha_fin])

    # 3. Agrupamos por fecha (siempre necesario)
    agrupacion = " GROUP BY fecha ORDER BY fecha ASC"
    query_ingresos_linea += agrupacion
    query_gastos_linea += agrupacion

    # 4. EjecuciÃ³n Condicional (LA PARTE IMPORTANTE)
    
    # Inicializamos las listas vacías para evitar errores si no se entra al if
    ingresos_data = []
    gastos_data = []

    # Solo buscamos INGRESOS si el filtro es 'Ingreso' o si NO hay filtro (quiere ver todo)
    if not tipo_registro_fil or tipo_registro_fil == 'Ingreso':
        cursor.execute(query_ingresos_linea, parametros_linea)
        ingresos_data = cursor.fetchall()

    # Solo buscamos GASTOS si el filtro es 'Gasto' o si NO hay filtro (quiere ver todo)
    if not tipo_registro_fil or tipo_registro_fil == 'Gasto':
        cursor.execute(query_gastos_linea, parametros_linea)
        gastos_data = cursor.fetchall()
    
   

    # ---------------------------------------- GrÃ¡ficos con Plotly -----------------------------------------# 
    #-----GrÃ¡fico de barras-----#
    categorias_graph = ['Ingresos', 'Gastos']
    valores_graph = [total_ingresos, total_gastos]

    fig = go.Figure(data=[
    go.Bar(x=categorias_graph, y=valores_graph, marker_color=['#00cc96', '#ef553b'])
    ])
    fig.update_layout(        
        font=dict(
            family="Rubik, Arial, sans-serif",  # ðŸ‘ˆ cambia aquÃ­ la fuente
            size=16,                              # tamaño del texto base
            color="#333333"                       # color del texto
        ),
        xaxis_title="Tipo", 
        yaxis_title="Monto",
    )
    graph_json = json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)
    

     #-----GrÃ¡fico de LÃ­neas-----#
   
    fechas_ingresos = [row["fecha"] for row in ingresos_data]
    valores_ingresos = [row["total"] for row in ingresos_data]
    fechas_gastos = [row["fecha"] for row in gastos_data]
    valores_gastos = [row["total"] for row in gastos_data]


    
    fig1 = go.Figure()

    fig1.add_trace(go.Scatter(
        x=fechas_ingresos,
        y=valores_ingresos,
        mode='lines+markers',
        name='Ingresos',
        line=dict(color="#2af835", width=3),
        marker=dict(size=6)
    ))

    fig1.add_trace(go.Scatter(
        x=fechas_gastos,
        y=valores_gastos,
        mode='lines+markers',
        name='Gastos',
        line=dict(color='#ef553b', width=3),
        marker=dict(size=6)
    ))

    fig1.update_layout(
        title="Evolución de Ingresos y Gastos",
        xaxis_title="Fecha",
        yaxis_title="Monto",
        font=dict(
            family="Rubik, Arial, sans-serif",
            size=16,
            color="#333333"
        ),
        hovermode="x unified",
        template="plotly_white"
    )

    graph_json1 = json.dumps(fig1, cls=plotly.utils.PlotlyJSONEncoder)


    

    # ---------------------------------------- Estilos GrÃ¡ficos Con Plotly ----------------------------------------- #


    fig.add_trace(go.Bar(
        x=["Ingresos", "Gastos"],
        y=[290000, 0],
        marker_color=["#00C49F", "#FF7F0E"]
    ))

    


    # Categorías
    cursor.execute("""
        SELECT categoria, COUNT(categoria) AS frecuencia
        FROM registros
        GROUP BY categoria
        ORDER BY frecuencia DESC
    """)
    lista_categorias = [row[0] for row in cursor.fetchall()]

    conn.close()    

    return render_template(
        "index.html",
        registros=registros,
        total_ingresos=total_ingresos,
        total_gastos=total_gastos,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        lista_categorias=lista_categorias,
        categoria_filtro=categoria_filtro,
        tipo_registro_fil=tipo_registro_fil,
        id_registro=id_registro,
        limit=limit,
        graph_json=graph_json,
        categorias_graph = categorias_graph, 
        valores_graph = valores_graph,
        graph_json1=graph_json1
        
    )

# --- EjecuciÃ³n del servidor ---
if __name__ == "__main__":
    app.run(debug=True)
