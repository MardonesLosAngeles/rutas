import streamlit as st
import pandas as pd
import numpy as np
import urllib.request
import urllib.parse
import json
import time
import re

st.set_page_config(
    page_title="Gestor de Rutas Georreferenciadas - Los Ángeles",
    page_icon="🗺️",
    layout="wide"
)

st.title("🗺️ Optimización y Control de Rutas de Ventas")
st.subheader("Los Ángeles, Chile — Mapa Interactivo y Hoja de Ruta Secuencial")

# --- FUNCIONES DE LIMPIEZA Y GEOLOCALIZACIÓN ---

def clean_address_text(address_raw):
    """
    Limpia y depura el texto de la dirección del Excel para mejorar 
    la geolocalización en Los Ángeles.
    """
    if not isinstance(address_raw, str):
        return ""
    
    text = address_raw.upper()
    text = re.sub(r'\(.*?\)', '', text) # Eliminar textos entre paréntesis
    text = re.sub(r',.*', '', text)     # Eliminar información tras la coma
    text = re.sub(r'\b(N°|NN\.|N\.|#|POB\.|VILLA|SECTOR)\b', '', text)
    text = " ".join(text.split())
    return text

@st.cache_data(show_spinner=False)
def geocode_address(address_str, city="Los Angeles", country="Chile"):
    """
    Obtiene coordenadas Lat/Lon usando Nominatim (OpenStreetMap)
    con estrategia de fallback por calle si el número no es encontrado.
    """
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
    
    # Fallback: Intentar con el nombre de la calle sin número
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

    # Coordenadas por defecto (Centro de Los Ángeles, Chile)
    return -37.4688, -72.3527, "Centro Los Ángeles (Aproximado)"

def calculate_haversine_distance(lat1, lon1, lat2, lon2):
    """Calcula distancia en metros entre dos coordenadas GPS"""
    R = 6371000 # Radio de la Tierra en metros
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    delta_phi = np.radians(lat2 - lat1)
    delta_lambda = np.radians(lon2 - lon1)
    a = np.sin(delta_phi/2.0)**2 + np.cos(phi1)*np.cos(phi2)*np.sin(delta_lambda/2.0)**2
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
    return R * c

def optimize_route_order(df_subset):
    """
    Algoritmo del Vecino Más Cercano (Nearest Neighbor)
    para ordenar los puntos secuencialmente por menor distancia.
    """
    if len(df_subset) <= 1:
        df_res = df_subset.copy().reset_index(drop=True)
        df_res['Orden_Secuencial'] = range(1, len(df_res) + 1)
        return df_res

    unvisited = df_subset.copy().reset_index(drop=True)
    ordered_indices = [0]
    
    current_idx = 0
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

# --- INTERFAZ DE USUARIO STREAMLIT ---

uploaded_file = st.file_uploader("Cargar archivo Excel de Clientes (.xlsx)", type=["xlsx"])

if uploaded_file is not None:
    df_raw = pd.read_excel(uploaded_file, sheet_name=0)
    df_clean = df_raw.iloc[1:].copy()
    df_clean.columns = ['ID', 'Nombre', 'Direccion', 'Comuna', 'Tipo', 'Status']
    df_clean = df_clean[['Nombre', 'Direccion', 'Comuna', 'Tipo', 'Status']].dropna(subset=['Nombre', 'Direccion'])
    
    st.success(f"✅ Archivo cargado correctamente ({len(df_clean)} clientes totales).")
    
    # Filtro de Grupo
    grupos = [
        "1. Ruta Prioritaria (2ª Visita / Interesados)", 
        "2. Nuevos con Compra", 
        "3. Resto de Clientes", 
        "4. Locales Cerrados / Inexistentes"
    ]
    selected_group = st.selectbox("Selecciona el Grupo de Clientes a Georreferenciar y Optimizar:", grupos)
    
    if st.button("🚀 Georreferenciar y Generar Mapa de Ruta"):
        with st.spinner("Filtrando grupo, geolocalizando en mapa y ordenando paradas..."):
            
            # 1. Filtrado de grupo estricto
            if "1." in selected_group:
                sub_df = df_clean[df_clean['Status'].astype(str).str.contains("VISITA|INTERESAD|SOLICITA|CREA", case=False, na=False)].copy()
            elif "2." in selected_group:
                sub_df = df_clean[df_clean['Status'].astype(str).str.contains("NUEVO|COMPRA", case=False, na=False)].copy()
            elif "4." in selected_group:
                sub_df = df_clean[df_clean['Status'].astype(str).str.contains("CERRADO|NO EXISTE", case=False, na=False)].copy()
            else:
                sub_df = df_clean[~df_clean['Status'].astype(str).str.contains("VISITA|INTERESAD|SOLICITA|CREA|NUEVO|COMPRA|CERRADO|NO EXISTE", case=False, na=False)].copy()
            
            if len(sub_df) == 0:
                st.warning("No se encontraron registros para el grupo seleccionado.")
            else:
                # 2. Geolocalización de los clientes del grupo seleccionado
                lats, lons, precs = [], [], []
                for idx, r in sub_df.iterrows():
                    lat, lon, prec = geocode_address(str(r['Direccion']))
                    lats.append(lat)
                    lons.append(lon)
                    precs.append(prec)
                    time.sleep(0.15)
                    
                sub_df['latitude'] = pd.to_numeric(lats, errors='coerce')
                sub_df['longitude'] = pd.to_numeric(lons, errors='coerce')
                sub_df['Precisión_GPS'] = precs
                
                # 3. Ordenamiento secuencial por cercanía (TSP)
                df_opt = optimize_route_order(sub_df)
                
                # Crear etiqueta identificadora para mapa y tabla
                df_opt['Etiqueta_Cliente'] = (
                    "#" + df_opt['Orden_Secuencial'].astype(str) + " - " + 
                    df_opt['Nombre'].astype(str) + " (" + df_opt['Direccion'].astype(str) + ")"
                )
                
                st.markdown(f"### 📍 Mapa de Ruta Interactivo ({len(df_opt)} Clientes Filtrados)")
                st.write("Haz clic sobre las casillas o usa la lista para identificar cada cliente:")
                
                # Mostrar tabla / selección
                st.map(df_opt[['latitude', 'longitude']])
                
                st.markdown("### 📋 Hoja de Ruta Secuencial (Ordenada por Cercanía)")
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
                        'Orden_Secuencial': 'Orden Visita',
                        'latitude': 'Latitud GPS',
                        'longitude': 'Longitud GPS'
                    }),
                    use_container_width=True
                )
else:
    st.info("Por favor sube el archivo Excel para comenzar el proceso de geolocalización.")