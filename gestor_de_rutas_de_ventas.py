import streamlit as st
import pandas as pd
import numpy as np
import urllib.request
import urllib.parse
import json
import time
import re
import os
import folium
from streamlit_folium import st_folium

st.set_page_config(
    page_title="Gestor de Rutas Persistente - Los Ángeles",
    page_icon="🗺️",
    layout="wide"
)

st.title("🗺️ Optimización y Control de Rutas de Ventas")
st.subheader("Los Ángeles, Chile — Sistema de Caché Persistente y Mapa Interactivo")

# --- SISTEMA DE CACHÉ PERSISTENTE EN DISCO (JSON) ---
CACHE_FILE = "coordenadas_cache.json"

def load_coords_cache():
    """Carga la base de datos local de coordenadas desde el disco."""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_coords_cache(cache_data):
    """Guarda la base de datos local de coordenadas en el disco."""
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

# Inicializar caché en la sesión de Streamlit
if "coords_db" not in st.session_state:
    st.session_state["coords_db"] = load_coords_cache()

# --- FUNCIONES DE LIMPIEZA Y GEOLOCALIZACIÓN ACELERADA ---

def clean_address_text(address_raw):
    """Limpia y depura el texto de dirección del Excel."""
    if not isinstance(address_raw, str):
        return ""
    text = address_raw.upper()
    text = re.sub(r'\(.*?\)', '', text) # Eliminar paréntesis
    text = re.sub(r',.*', '', text)     # Eliminar textos tras comas
    text = re.sub(r'\b(N°|NN\.|N\.|#|POB\.|VILLA|SECTOR)\b', '', text)
    text = " ".join(text.split())
    return text

def geocode_address_fast(address_str, city="Los Angeles", country="Chile"):
    """
    Geocodifica con estrategia de caché local instantánea.
    Si la dirección ya fue consultada antes, la retorna en 0.001s.
    """
    cleaned_street = clean_address_text(address_str)
    cache_key = f"{cleaned_street}|{city}".upper()
    
    # 1. Verificar si existe en la Base de Datos Local de Caché
    if cache_key in st.session_state["coords_db"]:
        cached = st.session_state["coords_db"][cache_key]
        return cached["lat"], cached["lon"], cached["prec"]

    # 2. Si no está en caché, realizar consulta a API externa
    full_query = f"{cleaned_street}, {city}, {country}"
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({
        'q': full_query,
        'format': 'json',
        'limit': 1
    })
    
    headers = {'User-Agent': 'LosAngelesRouteFastApp/2.0'}
    lat_res, lon_res, prec_res = -37.4688, -72.3527, "Centro Los Ángeles (Aproximado)"
    found = False

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=2.5) as response:
            data = json.loads(response.read().decode('utf-8'))
            if data:
                lat_res, lon_res, prec_res = float(data[0]['lat']), float(data[0]['lon']), "Punto Exacto"
                found = True
    except Exception:
        pass
    
    # Fallback sin número si no se encontró el punto exacto
    if not found:
        street_words = [w for w in cleaned_street.split() if not w.isdigit()]
        street_query = " ".join(street_words)
        if street_query:
            fallback_query = f"{street_query}, {city}, {country}"
            url_fb = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({
                'q': fallback_query,
                'format': 'json',
                'limit': 1
            })
            try:
                req_fb = urllib.request.Request(url_fb, headers=headers)
                with urllib.request.urlopen(req_fb, timeout=2.5) as response:
                    data_fb = json.loads(response.read().decode('utf-8'))
                    if data_fb:
                        lat_res, lon_res, prec_res = float(data_fb[0]['lat']), float(data_fb[0]['lon']), "Eje de Calle"
            except Exception:
                pass

    # Guardar el resultado en la Base de Datos / Caché persistente
    st.session_state["coords_db"][cache_key] = {
        "lat": lat_res,
        "lon": lon_res,
        "prec": prec_res
    }
    save_coords_cache(st.session_state["coords_db"])
    
    return lat_res, lon_res, prec_res

def calculate_haversine_distance(lat1, lon1, lat2, lon2):
    """Calcula la distancia Haversine en metros."""
    R = 6371000
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    delta_phi = np.radians(lat2 - lat1)
    delta_lambda = np.radians(lon2 - lon1)
    a = np.sin(delta_phi/2.0)**2 + np.cos(phi1)*np.cos(phi2)*np.sin(delta_lambda/2.0)**2
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
    return R * c

def optimize_route_order(df_subset):
    """Algoritmo de optimización secuencial por menor distancia."""
    if len(df_subset) <= 1:
        df_res = df_subset.copy().reset_index(drop=True)
        df_res['Orden_Secuencial'] = range(1, len(df_res) + 1)
        return df_res

    unvisited = df_subset.copy().reset_index(drop=True)
    center_lat = unvisited['latitude'].mean()
    center_lon = unvisited['longitude'].mean()
    
    # Iniciar en el cliente más próximo al centroide urbano
    start_idx = 0
    min_center_dist = float('inf')
    for idx in range(len(unvisited)):
        d = calculate_haversine_distance(center_lat, center_lon, unvisited.loc[idx, 'latitude'], unvisited.loc[idx, 'longitude'])
        if d < min_center_dist:
            min_center_dist = d
            start_idx = idx

    ordered_indices = [start_idx]
    current_idx = start_idx
    
    while len(ordered_indices) < len(unvisited):
        last_lat = unvisited.loc[current_idx, 'latitude']
        last_lon = unvisited.loc[current_idx, 'longitude']
        min_dist = float('inf')
        next_idx = None
        
        for idx in range(len(unvisited)):
            if idx not in ordered_indices:
                dist = calculate_haversine_distance(
                    last_lat, last_lon,
                    unvisited.loc[idx, 'latitude'], unvisited.loc[idx, 'longitude']
                )
                if dist < min_dist:
                    min_dist = dist
                    next_idx = idx
                    
        if next_idx is not None:
            ordered_indices.append(next_idx)
            current_idx = next_idx
        else:
            break
            
    df_ordered = unvisited.iloc[ordered_indices].copy().reset_index(drop=True)
    df_ordered['Orden_Secuencial'] = range(1, len(df_ordered) + 1)
    return df_ordered

# --- INTERFAZ DE USUARIO ---

st.sidebar.header("⚙️ Estado de la Base de Datos Local")
total_cached = len(st.session_state["coords_db"])
st.sidebar.metric("Direcciones Guardadas en Caché", total_cached)

uploaded_file = st.file_uploader("Cargar archivo Excel de Clientes (.xlsx)", type=["xlsx"])

if uploaded_file is not None:
    df_raw = pd.read_excel(uploaded_file, sheet_name=0)
    df_clean = df_raw.iloc[1:].copy()
    df_clean.columns = ['ID', 'Nombre', 'Direccion', 'Comuna', 'Tipo', 'Status']
    df_clean = df_clean[['Nombre', 'Direccion', 'Comuna', 'Tipo', 'Status']].dropna(subset=['Nombre', 'Direccion'])
    
    st.success(f"✅ Archivo cargado ({len(df_clean)} clientes).")
    
    grupos = [
        "1. Ruta Prioritaria (2ª Visita / Interesados)", 
        "2. Nuevos con Compra", 
        "3. Resto de Clientes", 
        "4. Locales Cerrados / Inexistentes"
    ]
    selected_group = st.selectbox("Selecciona el Grupo de Clientes a Georreferenciar y Optimizar:", grupos)
    
    if st.button("🚀 Procesar y Cargar Ruta (Acelerado por Caché)"):
        with st.spinner("Procesando direcciones con almacenamiento local persistente..."):
            
            if "1." in selected_group:
                sub_df = df_clean[df_clean['Status'].astype(str).str.contains("VISITA|INTERESAD|SOLICITA|CREA", case=False, na=False)].copy()
            elif "2." in selected_group:
                sub_df = df_clean[df_clean['Status'].astype(str).str.contains("NUEVO|COMPRA", case=False, na=False)].copy()
            elif "4." in selected_group:
                sub_df = df_clean[df_clean['Status'].astype(str).str.contains("CERRADO|NO EXISTE", case=False, na=False)].copy()
            else:
                sub_df = df_clean[~df_clean['Status'].astype(str).str.contains("VISITA|INTERESAD|SOLICITA|CREA|NUEVO|COMPRA|CERRADO|NO EXISTE", case=False, na=False)].copy()
            
            if len(sub_df) == 0:
                st.warning("No se encontraron clientes para el grupo seleccionado.")
            else:
                lats, lons, precs = [], [], []
                
                # Progresbar interactiva para feedback visual
                progress_bar = st.progress(0)
                status_text = st.empty()
                total_items = len(sub_df)
                
                for idx, (_, r) in enumerate(sub_df.iterrows()):
                    lat, lon, prec = geocode_address_fast(str(r['Direccion']))
                    lats.append(lat)
                    lons.append(lon)
                    precs.append(prec)
                    
                    # Actualizar barra de progreso
                    progress = (idx + 1) / total_items
                    progress_bar.progress(progress)
                    status_text.text(f"Procesando {idx + 1}/{total_items}: {r['Nombre']}")
                
                progress_bar.empty()
                status_text.empty()
                
                sub_df['latitude'] = pd.to_numeric(lats, errors='coerce')
                sub_df['longitude'] = pd.to_numeric(lons, errors='coerce')
                sub_df['Precisión_GPS'] = precs
                
                # Guardar resultado procesado en la sesión activa para evitar reseteos al minimizar
                st.session_state["df_opt_active"] = optimize_route_order(sub_df)

    # Renderizar resultados si ya están en memoria de sesión
    if "df_opt_active" in st.session_state:
        df_opt = st.session_state["df_opt_active"]
        
        st.markdown(f"### 📍 Mapa Interactivo ({len(df_opt)} Clientes)")
        
        center_lat_map = df_opt['latitude'].mean()
        center_lon_map = df_opt['longitude'].mean()
        
        m = folium.Map(location=[center_lat_map, center_lon_map], zoom_start=13, tiles="OpenStreetMap")
        route_points = df_opt[['latitude', 'longitude']].values.tolist()
        folium.PolyLine(route_points, color="blue", weight=2.5, opacity=0.7, tooltip="Ruta Sugerida").add_to(m)
        
        for _, row in df_opt.iterrows():
            orden = int(row['Orden_Secuencial'])
            nombre = str(row['Nombre'])
            direccion = str(row['Direccion'])
            status = str(row['Status'])
            
            popup_html = f"""
            <div style="font-family: Arial; font-size: 13px; width: 220px;">
                <b style="color: #1F4E79;">Parada #{orden}</b><br>
                <b>Cliente:</b> {nombre}<br>
                <b>Dirección:</b> {direccion}<br>
                <b>Estado:</b> <span style="color: #d9534f;">{status}</span>
            </div>
            """
            
            folium.Marker(
                location=[row['latitude'], row['longitude']],
                popup=folium.Popup(popup_html, max_width=250),
                tooltip=f"#{orden}: {nombre}",
                icon=folium.DivIcon(
                    html=f"""
                    <div style="
                        background-color: #1F4E79; 
                        color: white; 
                        font-weight: bold; 
                        border-radius: 50%; 
                        width: 28px; 
                        height: 28px; 
                        display: flex; 
                        align-items: center; 
                        justify-content: center; 
                        border: 2px solid white;
                        box-shadow: 2px 2px 5px rgba(0,0,0,0.5);
                        font-size: 12px;">
                        {orden}
                    </div>
                    """
                )
            ).add_to(m)
        
        st_folium(m, width="100%", height=500)
        
        st.markdown("### 📋 Hoja de Ruta Secuencial Ordenada")
        st.dataframe(
            df_opt[[
                'Orden_Secuencial', 
                'Nombre', 
                'Direccion', 
                'Status', 
                'Precisión_GPS',
                'latitude',
                'longitude'
            ]].rename(columns={
                'Orden_Secuencial': 'Orden Visita (#)',
                'latitude': 'Latitud GPS',
                'longitude': 'Longitud GPS'
            }),
            use_container_width=True
        )
else:
    st.info("Por favor sube el archivo Excel para comenzar el proceso.")