# ==============================================================================
# APLICACIÓN WEB LIGERA DE GESTIÓN Y OPTIMIZACIÓN DE RUTAS DE VENTAS
# Ubicación Target: Los Ángeles, Chile
# Stack: Python, Streamlit, Pandas, OpenPyXL
# ==============================================================================

import io
import re
import pandas as pd
import streamlit as st

# ------------------------------------------------------------------------------
# 1. CONFIGURACIÓN DE LA PÁGINA STREAMLIT
# ------------------------------------------------------------------------------
st.set_page_config(
    page_title="Gestor de Rutas de Ventas - Los Ángeles",
    page_icon="🚚",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ------------------------------------------------------------------------------
# 2. DICCIONARIOS Y LÓGICA DE SECTORIZACIÓN Y CLASIFICACIÓN
# ------------------------------------------------------------------------------

# Mapeo de Ejes Viales y Calles de Los Ángeles por Sector Urbano
SECTORES_LOS_ANGELES = {
    "Centro": [
        "ALMAGRO", "ALCAZAR", "CAUPOLICAN", "OHIGGINS", "ERCILLA", "BALMASEDA",
        "BALMACEDA", "COLO COLO", "ARGENTINA", "TUCAPEL", "LOS CARRERA", "LOS CARRERAS",
        "MENDOZA", "FREIRE", "VILLAGRAN", "PATRICIO LYNCH", "LYNCH", "SUCRE", "CURICO",
        "DE LA CONSTITUCION", "CONSTITUCION", "RENGO", "RUIZ ALDEA", "SANTA FILOMENA",
        "SAN MARTIN", "SANTA FE", "VALDIVIA", "LATORRE"
    ],
    "Nororiente": [
        "SOR VICENTA", "GABRIELA MISTRAL", "MARCONI", "COMPAÑIA DE JESUS", "LAS LUCIERNAGAS",
        "SAN GABRIEL", "MONTREAL", "TAMARUGAL", "CAMINO ANTUCO", "LAS INDUSTRIAS",
        "PEDRO STARK", "AVDA ALEMANIA", "AV. ALEMANIA", "AVENIDA ALEMANIA", "AVDA. ALEMANIA"
    ],
    "Sur": [
        "FRANCISCO ENCINA", "ALBERTO POBLETE", "FRANCISCO RIOSECO", "BOMBERO RIOSECO",
        "ALFONSO CARRASCO", "LOS APACHES", "LOS CARDOS", "TOLPAN", "PEDRO PRADO",
        "BUENOS AIRES", "ALEJANDRO FLORES", "MATEO DE TORO", "PALO VERDE", "PALOS QUEMADOS",
        "RIO LEMPA", "RIO MAGDALENA", "RIO BIO BIO", "RENE ARAVENA", "LOS CANELOS",
        "COSTANERA", "CANTO CHILENO", "SAN JORGE", "PAILLIHUE", "VILLA GENESIS", "VILLA LOS PROFESORES"
    ],
    "Poniente": [
        "VICUÑA MACKENNA", "RICARDO VICUÑA", "PONIENTE", "SACRAMENTOS", "LOS MISIONEROS",
        "GALVARINO", "CHILE LINDO", "ALMIRANTE LA TORRE", "SANTIAGO", "VICTOR DOMINGO SILVA",
        "LOS QUIMBALLA", "LOS TINEBOS", "LOS PASTORES", "SALVADOR REYES", "RUCAPEQUEN",
        "EL CARIBE", "AVDA. ORIENTE", "AVDA ORIENTE", "AVENIDA ORIENTE", "LAUQUEN",
        "LA CUMBRE", "LA LLANURA", "LA POSADA", "LAGUNA LAJA", "LAGUNA VERDE", "LIMA",
        "SANTA ESTER", "ÑUBLE", "NAHUELBUTA", "FRONTERA", "LAS QUINTAS", "OJOS DEL CABURGA",
        "PEDREGAL", "GALILEA", "PARQUE LAUQUEN"
    ]
}

def identificar_sector(direccion: str) -> str:
    """Asigna un sector urbano de Los Ángeles basado en palabras clave en la dirección."""
    if not isinstance(direccion, str):
        return "Otro / Por Clasificar"
    
    dir_upper = direccion.upper()
    for sector, calles in SECTORES_LOS_ANGELES.items():
        for calle in calles:
            if calle in dir_upper:
                return sector
    return "Otro / Por Clasificar"

def clasificar_grupo(status: str) -> str:
    """Clasifica al cliente en uno de los 4 grupos estratégicos según su estado/resultado."""
    if not isinstance(status, str):
        return "3. Resto de Clientes"
    
    status_upper = status.upper().strip()
    
    # Grupo 4: Locales Cerrados e Inexistentes
    if any(k in status_upper for k in ["CERRADO", "NO EXISTE", "DIRECCION INCORRECTA", "NO ENCONTRADO"]):
        return "4. Locales Cerrados / Inexistentes"
    
    # Grupo 1: Ruta Prioritaria
    if any(k in status_upper for k in ["2° VISITA", "2A VISITA", "INTERESADO", "SE CREARA", "MUESTRAS", "PRIORITARIO", "PENDIENTE"]):
        return "1. Ruta Prioritaria (2° Visita e Interesados)"
        
    # Grupo 2: Nuevos con Compra
    if any(k in status_upper for k in ["NUEVO CON COMPRA", "CREADO CON COMPRA", "COMPRA REALIZADA"]):
        return "2. Nuevos con Compra"
        
    # Grupo 3: Resto
    return "3. Resto de Clientes"

def extraer_numero_orden(direccion: str) -> int:
    """Extrae el primer número de la dirección para ordenar secuencialmente la calle."""
    if not isinstance(direccion, str):
        return 99999
    nums = re.findall(r'\d+', direccion)
    return int(nums[0]) if nums else 99999

# ------------------------------------------------------------------------------
# 3. MÓDULO DE PROCESAMIENTO DE DATOS Y EXCEL
# ------------------------------------------------------------------------------

def procesar_dataframe(df: pd.DataFrame) -> tuple:
    """Limpia, clasifica y ordena el DataFrame cargado."""
    df = df.copy()
    
    # Normalización de nombres de columnas
    df.columns = [str(c).strip() for c in df.columns]
    
    # Búsqueda flexible de columnas obligatorias
    col_nombre = next((c for c in df.columns if "NOMBRE" in c.upper() or "CLIENTE" in c.upper()), df.columns[0])
    col_dir = next((c for c in df.columns if "DIR" in c.upper() or "CALLE" in c.upper()), df.columns[1] if len(df.columns)>1 else df.columns[0])
    col_status = next((c for c in df.columns if "STATUS" in c.upper() or "ESTADO" in c.upper() or "RESULTADO" in c.upper()), df.columns[-1])
    
    # Asignación de clasificaciones
    df["Grupo_Asignado"] = df[col_status].apply(clasificar_grupo)
    df["Sector_Urbano"] = df[col_dir].apply(identificar_sector)
    df["Num_Calle"] = df[col_dir].apply(extraer_numero_orden)
    
    # Columnas editables para la gestión en terreno
    if "Nuevo_Estado_Visita" not in df.columns:
        df["Nuevo_Estado_Visita"] = "Pendiente"
    if "Observaciones" not in df.columns:
        df["Observaciones"] = ""
        
    # Ordenamiento por Grupo, Sector y Número de Calle (Secuencia de Cercanía)
    df = df.sort_values(
        by=["Grupo_Asignado", "Sector_Urbano", col_dir, "Num_Calle"],
        ascending=[True, True, True, True]
    ).drop(columns=["Num_Calle"])
    
    return df, col_nombre, col_dir, col_status

def generar_excel_interactivo(df_procesado: pd.DataFrame) -> bytes:
    """Genera un archivo Excel con pestañas de Base de Datos y Dashboard de Métricas."""
    output = io.BytesIO()
    
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        # Pestaña 1: Base de Clientes
        df_procesado.to_excel(writer, sheet_name="Base_Clientes_Ruta", index=False)
        
        # Pestaña 2: Dashboard de Métricas
        resumen_grupo = df_procesado["Grupo_Asignado"].value_counts().reset_index()
        resumen_grupo.columns = ["Grupo de Clientes", "Cantidad"]
        resumen_grupo["% del Total"] = (resumen_grupo["Cantidad"] / len(df_procesado) * 100).round(2)
        
        resumen_sector = df_procesado["Sector_Urbano"].value_counts().reset_index()
        resumen_sector.columns = ["Sector Urbano", "Cantidad"]
        
        resumen_grupo.to_excel(writer, sheet_name="Dashboard_Metricas", startrow=1, startcol=1, index=False)
        resumen_sector.to_excel(writer, sheet_name="Dashboard_Metricas", startrow=10, startcol=1, index=False)
        
    return output.getvalue()

# ------------------------------------------------------------------------------
# 4. INTERFAZ DE USUARIO (STREAMLIT APP)
# ------------------------------------------------------------------------------

st.title("🚚 Gestor y Optimizador de Rutas de Ventas")
st.caption("Los Ángeles, Chile — Herramienta interactiva de sectorización y métricas de terreno.")

# Sidebar - Carga de Archivo
st.sidebar.header("📁 Carga de Datos")
uploaded_file = st.sidebar.file_uploader("Sube la planilla Excel (.xlsx)", type=["xlsx", "xls"])

if uploaded_file is not None:
    try:
        raw_df = pd.read_excel(uploaded_file)
        st.sidebar.success(f"Archivo cargado correctamente: {len(raw_df)} registros.")
        
        # Procesamiento inicial
        df_rutas, col_nom, col_dir, col_stat = procesar_dataframe(raw_df)
        
        # --- FILTROS EN SIDEBAR ---
        st.sidebar.header("🔍 Filtros de Visualización")
        
        grupos_disponibles = list(df_rutas["Grupo_Asignado"].unique())
        filtro_grupo = st.sidebar.multiselect("Filtrar por Grupo:", grupos_disponibles, default=grupos_disponibles)
        
        sectores_disponibles = list(df_rutas["Sector_Urbano"].unique())
        filtro_sector = st.sidebar.multiselect("Filtrar por Sector Urbano:", sectores_disponibles, default=sectores_disponibles)
        
        # Aplicación de Filtros
        df_filtrado = df_rutas[
            (df_rutas["Grupo_Asignado"].isin(filtro_grupo)) & 
            (df_rutas["Sector_Urbano"].isin(filtro_sector))
        ]
        
        # --- RESUMEN DE MÉTRICAS RÁPIDAS ---
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Base", len(df_rutas))
        col2.metric("Ruta Prioritaria (G1)", len(df_rutas[df_rutas["Grupo_Asignado"].str.startswith("1")]))
        col3.metric("Nuevos c/Compra (G2)", len(df_rutas[df_rutas["Grupo_Asignado"].str.startswith("2")]))
        col4.metric("Locales Cerrados (G4)", len(df_rutas[df_rutas["Grupo_Asignado"].str.startswith("4")]))
        
        st.divider()
        
        # --- TABLA INTERACTIVA DE EDICIÓN EN LÍNEA ---
        st.subheader("📝 Hoja de Ruta Interactiva (Edición Terreno)")
        st.info("Puedes modificar directamente los campos 'Nuevo_Estado_Visita' y 'Observaciones' en la tabla.")
        
        df_edited = st.data_editor(
            df_filtrado,
            column_config={
                "Nuevo_Estado_Visita": st.column_config.SelectboxColumn(
                    "Estado de Visita",
                    help="Resultado de la gestión de hoy",
                    options=["Pendiente", "Visitado - Venta Concretada", "Visitado - No Compra", "Local Cerrado", "Reagendado"],
                    required=True
                ),
                "Observaciones": st.column_config.TextColumn(
                    "Observaciones / Reasignación",
                    help="Notas del vendedor en terreno"
                ),
                "Grupo_Asignado": st.column_config.TextColumn("Grupo Estratégico", disabled=True),
                "Sector_Urbano": st.column_config.TextColumn("Sector Urbano", disabled=True),
            },
            hide_index=True,
            use_container_width=True,
            num_rows="fixed"
        )
        
        # --- SECCIÓN DE EXPORTACIÓN Y DESCARGA ---
        st.divider()
        st.subheader("💾 Exportar Planilla Actualizada")
        
        excel_bytes = generar_excel_interactivo(df_edited)
        
        st.download_button(
            label="📥 Descargar Excel con Formato y Métricas Actualizadas",
            data=excel_bytes,
            file_name="Ruta_Ventas_Actualizada_Los_Angeles.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        
    except Exception as e:
        st.error(f"Error al procesar la planilla: {e}")

else:
    st.info("👋 Por favor, sube una planilla Excel en la barra lateral para generar la ruta optimizada.")