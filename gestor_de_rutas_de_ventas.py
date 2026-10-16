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
from folium.plugins import MarkerCluster

st.set_page_config(
    page_title="Gestor de Rutas Persistente - Los Ángeles",
    page_icon="🗺️",
    layout="wide"
)

st.title("🗺️ Optimización y Control de Rutas de Ventas")
st.subheader("Los Ángeles, Chile — Mapa Interactivo con Desagregación de Puntos")

# --- CACHÉ PERSISTENTE EN DISCO ---
CACHE_FILE = "coordenadas_cache.json"

def load_coords_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_coords_cache(cache_data):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

if "coords_db" not in st.session_state:
    st.session_state["coords_db"] = load_coords_cache()

# --- LIMPIEZA Y GEOLOCALIZACIÓN ---

def clean_address_text(address_raw):
    """Limpia y depura la dirección eliminando textos de intersecciones o esquinas."""
    if not isinstance(address_raw, str):
        return ""
    text = address_raw.upper()
    text = re.sub(r'\(.*?\)', '', text)
    text = re.sub(r',.*', '', text)
    text = re.sub(r'\b(ESQ\.|ESQUINA|N°|NN\.|N\.|#|POB\.|VILLA|SECTOR|S/N)\b.*', '', text)
    text = " ".join(text.split())
    return text

def geocode_address_fast(address_str, city="Los Angeles", country="Chile"):
    cleaned_street = clean_address_text(address_str)
    cache_key = f"{cleaned_street}|{city}".upper()
    
    if cache_key in st.session_state["coords_db"]:
        cached = st.session_state["coords_db"][cache_key]
        return cached["lat"], cached["lon"], cached["prec"]

    full_query = f"{cleaned_street}, {city}, {country}"
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({
        'q': full_query,
        'format': 'json',
        'limit': 1
    })
    
    headers = {'User-Agent': 'LosAngelesRouteFastApp/3.0'}
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

    st.session_state["coords_db"][cache_key] = {
        "lat": lat_res,
        "lon": lon_res,
        "prec": prec_res
    }
    save_coords_cache(st.session_state["coords_db"])
    
    return lat_res, lon_res, prec_res

def add_jitter_to_duplicates(df):
    """
    Agrega una micro-dispersión (jittering) de unos metros a coordenadas 
    idénticas para evitar que se solapen exactamente en la misma capa.
    """
    df = df.copy()
    coords_seen = {}
    
    new_lats = []
    new_lons = []
    
    for idx, row in df.iterrows():
        lat = row['latitude']
        lon = row['longitude']
        key = (round(lat, 5), round(lon, 5))
        
        if key in coords_seen:
            coords_seen[key] += 1
            count = coords_seen[key]
            # Pequeño desplazamiento en espiral (~15 a 30 metros)
            angle = count * 0.8
            radius = 0.00015 * count
            lat += radius * np.cos(angle)
            lon += radius * np.sin(angle)
        else:
            coords_seen[key] = 0
            
        new_lats.append(lat)
        new_lons.append(lon)
        
    df['latitude_vis'] = new_lats
    df['longitude_vis'] = new_lons
    return df

def calculate_haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    delta_phi = np.radians(lat2 - lat1)
    delta_lambda = np.radians(lon2 - lon1)
    a = np.sin(delta_phi/2.0)**2 + np.cos(phi1)*np.cos(phi2)*np.sin(delta_lambda/2.0)**2
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
    return R * c

def optimize_route_order(df_subset):
    if len(df_subset) <= 1:
        df_res = df_subset.copy().reset_index(drop=True)
        df_res['Orden_Secuencial'] = range(1, len(df_res) + 1)
        return df_res

    unvisited = df_subset.copy().reset_index(drop=True)
    center_lat = unvisited['latitude'].mean()
    center_lon = unvisited['longitude'].mean()
    
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

# --- INTERFAZ ---

st.sidebar.header("⚙️ Base de Datos Local")
st.sidebar.metric("Coordenadas en Caché", len(st.session_state["coords_db"]))

uploaded_file = st.file_uploader("Cargar archivo Excel de Clientes (.xlsx)", type=["xlsx"])

if uploaded_file is not None:
    df_raw = pd.read_excel(uploaded_file, sheet_name=0)
    df_clean = df_raw.iloc[1:].copy()
    df_clean.columns = ['ID', 'Nombre', 'Direccion', 'Comuna', 'Tipo', 'Status']
    df_clean = df_clean[['Nombre', 'Direccion', 'Comuna', 'Tipo', 'Status']].dropna(subset=['Nombre', 'Direccion'])
    
    st.success(f"✅ Archivo cargado ({len(df_clean)} clientes totales).")
    
    grupos = [
        "1. Ruta Prioritaria (2ª Visita / Interesados)", 
        "2. Nuevos con Compra", 
        "3. Resto de Clientes", 
        "4. Locales Cerrados / Inexistentes"
    ]
    selected_group = st.selectbox("Selecciona el Grupo de Clientes a Georreferenciar y Optimizar:", grupos)
    
    if st.button("🚀 Procesar y Cargar Ruta (Acelerado por Caché)"):
        with st.spinner("Procesando direcciones y resolviendo solapamientos..."):
            
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
                progress_bar = st.progress(0)
                status_text = st.empty()
                total_items = len(sub_df)
                
                for idx, (_, r) in enumerate(sub_df.iterrows()):
                    lat, lon, prec = geocode_address_fast(str(r['Direccion']))
                    lats.append(lat)
                    lons.append(lon)
                    precs.append(prec)
                    
                    progress = (idx + 1) / total_items
                    progress_bar.progress(progress)
                    status_text.text(f"Procesando {idx + 1}/{total_items}: {r['Nombre']}")
                
                progress_bar.empty()
                status_text.empty()
                
                sub_df['latitude'] = pd.to_numeric(lats, errors='coerce')
                sub_df['longitude'] = pd.to_numeric(lons, errors='coerce')
                sub_df['Precisión_GPS'] = precs
                
                df_opt = optimize_route_order(sub_df)
                st.session_state["df_opt_active"] = add_jitter_to_duplicates(df_opt)

    if "df_opt_active" in st.session_state:
        df_opt = st.session_state["df_opt_active"]
        
        st.markdown(f"### 📍 Mapa Interactivo Desagregado ({len(df_opt)} Clientes)")
        
        center_lat_map = df_opt['latitude_vis'].mean()
        center_lon_map = df_opt['longitude_vis'].mean()
        
        m = folium.Map(location=[center_lat_map, center_lon_map], zoom_start=13, tiles="OpenStreetMap")
        
        # Conectar ruta secuencial
        route_points = df_opt[['latitude_vis', 'longitude_vis']].values.tolist()
        folium.PolyLine(route_points, color="blue", weight=2, opacity=0.6, tooltip="Trazado de Ruta").add_to(m)
        
        # Agrupador de marcadores para evitar que se encimen
        marker_cluster = MarkerCluster().add_to(m)
        
        for _, row in df_opt.iterrows():
            orden = int(row['Orden_Secuencial'])
            nombre = str(row['Nombre'])
            direccion = str(row['Direccion'])
            status = str(row['Status'])
            precision = str(row['Precisión_GPS'])
            
            popup_html = f"""
            <div style="font-family: Arial; font-size: 13px; width: 230px;">
                <b style="color: #1F4E79;">Parada #{orden}</b><br>
                <b>Cliente:</b> {nombre}<br>
                <b>Dirección:</b> {direccion}<br>
                <b>Precisión:</b> {precision}<br>
                <b>Estado:</b> <span style="color: #d9534f;">{status}</span>
            </div>
            """
            
            # Marcador individual desagregado
            folium.Marker(
                location=[row['latitude_vis'], row['longitude_vis']],
                popup=folium.Popup(popup_html, max_width=260),
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
                        font-size: 11px;">
                        {orden}
                    </div>
                    """
                )
            ).add_to(marker_cluster)
        
        st_folium(m, width="100%", height=530)
        
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