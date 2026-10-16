import streamlit as st
import pandas as pd
import numpy as np
import urllib.request
import urllib.parse
import json
import time
import re
import folium
from streamlit_folium import st_folium

st.set_page_config(
    page_title="Gestor de Rutas Georreferenciadas - Los Ángeles",
    page_icon="🗺️",
    layout="wide"
)

st.title("🗺️ Optimización y Mapa Interactivo de Rutas de Ventas")
st.subheader("Los Ángeles, Chile — Identificación de Clientes y Secuencia de Visita")

# --- FUNCIONES DE LIMPIEZA Y GEOLOCALIZACIÓN ---

def clean_address_text(address_raw):
    """Limpia y depura la dirección para la API de geolocalización."""
    if not isinstance(address_raw, str):
        return ""
    text = address_raw.upper()
    text = re.sub(r'\(.*?\)', '', text)
    text = re.sub(r',.*', '', text)
    text = re.sub(r'\b(N°|NN\.|N\.|#|POB\.|VILLA|SECTOR)\b', '', text)
    text = " ".join(text.split())
    return text

@st.cache_data(show_spinner=False)
def geocode_address(address_str, city="Los Angeles", country="Chile"):
    """Obtiene latitud y longitud desde Nominatim (OpenStreetMap)."""
    cleaned_street = clean_address_text(address_str)
    full_query = f"{cleaned_street}, {city}, {country}"
    
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({
        'q': full_query,
        'format': 'json',
        'limit': 1
    })
    
    headers = {'User-Agent': 'LosAngelesRouteOptimizationApp/1.0'}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=3) as response:
            data = json.loads(response.read().decode('utf-8'))
            if data:
                return float(data[0]['lat']), float(data[0]['lon']), "Punto Exacto"
    except Exception:
        pass
    
    # Fallback sin número
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
            with urllib.request.urlopen(req_fb, timeout=3) as response:
                data_fb = json.loads(response.read().decode('utf-8'))
                if data_fb:
                    return float(data_fb[0]['lat']), float(data_fb[0]['lon']), "Eje de Calle"
        except Exception:
            pass

    # Coordenadas por defecto (Plaza de Armas / Centro de Los Ángeles, Chile)
    return -37.4688, -72.3527, "Centro Los Ángeles (Aproximado)"

def calculate_haversine_distance(lat1, lon1, lat2, lon2):
    """Calcula distancia en metros entre dos coordenadas GPS."""
    R = 6371000
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    delta_phi = np.radians(lat2 - lat1)
    delta_lambda = np.radians(lon2 - lon1)
    a = np.sin(delta_phi/2.0)**2 + np.cos(phi1)*np.cos(phi2)*np.sin(delta_lambda/2.0)**2
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
    return R * c

def optimize_route_order(df_subset):
    """
    Ordena secuencialmente los puntos partiendo desde el cliente
    más cercano al centro geográfico del grupo.
    """
    if len(df_subset) <= 1:
        df_res = df_subset.copy().reset_index(drop=True)
        df_res['Orden_Secuencial'] = range(1, len(df_res) + 1)
        return df_res

    unvisited = df_subset.copy().reset_index(drop=True)
    
    # Punto de inicio: Centroide de todas las coordenadas del grupo
    center_lat = unvisited['latitude'].mean()
    center_lon = unvisited['longitude'].mean()
    
    # Encontrar el primer cliente más cercano al centroide
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

# --- INTERFAZ STREAMLIT ---

uploaded_file = st.file_uploader("Cargar archivo Excel de Clientes (.xlsx)", type=["xlsx"])

if uploaded_file is not None:
    df_raw = pd.read_excel(uploaded_file, sheet_name=0)
    df_clean = df_raw.iloc[1:].copy()
    df_clean.columns = ['ID', 'Nombre', 'Direccion', 'Comuna', 'Tipo', 'Status']
    df_clean = df_clean[['Nombre', 'Direccion', 'Comuna', 'Tipo', 'Status']].dropna(subset=['Nombre', 'Direccion'])
    
    st.success(f"✅ Archivo cargado correctamente ({len(df_clean)} clientes totales).")
    
    grupos = [
        "1. Ruta Prioritaria (2ª Visita / Interesados)", 
        "2. Nuevos con Compra", 
        "3. Resto de Clientes", 
        "4. Locales Cerrados / Inexistentes"
    ]
    selected_group = st.selectbox("Selecciona el Grupo de Clientes a Georreferenciar y Optimizar:", grupos)
    
    if st.button("🚀 Georreferenciar y Generar Mapa Interactivo"):
        with st.spinner("Geolocalizando clientes y creando marcadores con identificación..."):
            
            # 1. Filtro estricto por grupo
            if "1." in selected_group:
                sub_df = df_clean[df_clean['Status'].astype(str).str.contains("VISITA|INTERESAD|SOLICITA|CREA", case=False, na=False)].copy()
            elif "2." in selected_group:
                sub_df = df_clean[df_clean['Status'].astype(str).str.contains("NUEVO|COMPRA", case=False, na=False)].copy()
            elif "4." in selected_group:
                sub_df = df_clean[df_clean['Status'].astype(str).str.contains("CERRADO|NO EXISTE", case=False, na=False)].copy()
            else:
                sub_df = df_clean[~df_clean['Status'].astype(str).str.contains("VISITA|INTERESAD|SOLICITA|CREA|NUEVO|COMPRA|CERRADO|NO EXISTE", case=False, na=False)].copy()
            
            if len(sub_df) == 0:
                st.warning("No se encontraron registros en el grupo seleccionado.")
            else:
                # 2. Geolocalización
                lats, lons, precs = [], [], []
                for idx, r in sub_df.iterrows():
                    lat, lon, prec = geocode_address(str(r['Direccion']))
                    lats.append(lat)
                    lons.append(lon)
                    precs.append(prec)
                    time.sleep(0.12)
                    
                sub_df['latitude'] = pd.to_numeric(lats, errors='coerce')
                sub_df['longitude'] = pd.to_numeric(lons, errors='coerce')
                sub_df['Precisión_GPS'] = precs
                
                # 3. Ordenamiento por cercanía
                df_opt = optimize_route_order(sub_df)
                
                # 4. Crear Mapa Folium Interactivo con Marcadores Nominados
                center_lat_map = df_opt['latitude'].mean()
                center_lon_map = df_opt['longitude'].mean()
                
                m = folium.Map(location=[center_lat_map, center_lon_map], zoom_start=13, tiles="OpenStreetMap")
                
                # Dibujar ruta (línea conectora secuencial)
                route_points = df_opt[['latitude', 'longitude']].values.tolist()
                folium.PolyLine(route_points, color="blue", weight=2.5, opacity=0.7, tooltip="Ruta Sugerida").add_to(m)
                
                # Agregar marcadores enumerados con Popups
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
                    
                    # Marcador enumerado
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
                
                st.markdown(f"### 📍 Mapa Interactivo de la Ruta ({len(df_opt)} Clientes)")
                st.info("💡 Haz clic o pasa el cursor sobre cada número (#1, #2, #3...) en el mapa para ver la información del cliente.")
                
                # Renderizar mapa en Streamlit
                st_folium(m, width="100%", height=500)
                
                st.markdown("### 📋 Hoja de Ruta Ordenada (Sincronizada con el Mapa)")
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