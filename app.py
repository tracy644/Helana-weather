import streamlit as st
import requests
import pandas as pd
from dateutil import parser
from datetime import datetime, timedelta
import math
import re

# --- CONFIGURATION ---
st.set_page_config(page_title="Winter Logistics Pro", page_icon="🚛", layout="centered")

# NWS Hourly Endpoints
LOCATIONS = {
    "4th of July Pass": "https://api.weather.gov/gridpoints/OTX/168,102/forecast/hourly",
    "Lookout Pass": "https://api.weather.gov/gridpoints/MSO/56,102/forecast/hourly",
    "Missoula Valley": "https://api.weather.gov/gridpoints/MSO/86,76/forecast/hourly",
    "McDonald Pass": "https://api.weather.gov/gridpoints/TFX/62,50/forecast/hourly"
}

# Travel Windows
OUTBOUND_HOURS = [7, 8, 9, 10, 11, 12]
RETURN_HOURS = [13, 14, 15, 16, 17, 18]

# --- LOGIC ENGINE ---
@st.cache_data(ttl=900) 
def fetch_hourly_data(url):
    try:
        headers = {'User-Agent': '(winter-logistics-tool, contact@example.com)'}
        r = requests.get(url, headers=headers, timeout=5)
        r.raise_for_status()
        data = r.json()
        return data['properties']['periods']
    except:
        return []

def get_int(val):
    """Safely extracts integer from string or dict"""
    if val is None: return 0
    if isinstance(val, dict) and 'value' in val:
        val = val['value']
    nums = re.findall(r'\d+', str(val))
    if nums:
        return int(nums[0])
    return 0

def add_weather_icon(forecast_text):
    """Adds visual icons to text for faster reading"""
    text = forecast_text.lower()
    icon = ""
    if "snow" in text: icon = "🌨️"
    elif "rain" in text: icon = "🌧️"
    elif "shower" in text: icon = "🌦️"
    elif "cloud" in text: icon = "☁️"
    elif "clear" in text or "sunny" in text: icon = "☀️"
    elif "fog" in text: icon = "🌫️"
    elif "wind" in text: icon = "💨"
    
    return f"{icon} {forecast_text}"

def calculate_wind_chill(temp_f, speed_mph):
    if temp_f > 50 or speed_mph < 3:
        return temp_f
    return 35.74 + (0.6215 * temp_f) - (35.75 * math.pow(speed_mph, 0.16)) + (0.4275 * temp_f * math.pow(speed_mph, 0.16))

def analyze_hour(row, location_name):
    risk_score = 0
    alerts = []
    
    temp = row['temperature']
    short_forecast = row['shortForecast'].lower()
    direction = row['windDirection']
    
    # WIND LOGIC
    sustained = get_int(row.get('windSpeed', 0))
    gust = get_int(row.get('windGust', 0))
    effective_wind = max(sustained, gust)
    
    # PRECIP CHANCE
    pop = get_int(row.get('probabilityOfPrecipitation', 0))
    
    # 1. Road Surface Risk & Black Ice
    if "snow" in short_forecast or "ice" in short_forecast:
        if temp <= 32:
            risk_score += 2
            alerts.append("❄️ Icy Roads")
        else:
            risk_score += 1
            alerts.append("💧 Slush")
            
    elif "rain" in short_forecast:
        if temp <= 32:
            risk_score += 3
            alerts.append("🧊 FREEZING RAIN")
        elif temp <= 37:
            # BLACK ICE ZONE: Air is warm, ground might be frozen
            risk_score += 1
            alerts.append("🧊 Possible Black Ice")
        
    # 2. Wind Risk
    if effective_wind >= 45:
        risk_score += 2
        alerts.append(f"💨 GUSTS {effective_wind} MPH")
    elif effective_wind >= 30:
        risk_score += 1
        alerts.append(f"💨 Windy ({effective_wind})")
    elif "breezy" in short_forecast or "windy" in short_forecast:
        if effective_wind < 20: 
             alerts.append("💨 Breezy")

    # 3. Crosswind Specific
    if "McDonald" in location_name and effective_wind > 20:
        if direction in ['N', 'NNE', 'NNW', 'S', 'SSE', 'SSW']:
            risk_score += 1
            alerts.append("↔️ CROSSWIND")

    # 4. Wind Chill
    wc = calculate_wind_chill(temp, effective_wind)
    if wc < 0:
        risk_score += 1
        alerts.append(f"🥶 Chill {int(wc)}°")

    status = "🟢"
    if risk_score == 1: status = "🟡"
    if risk_score >= 2: status = "🟠"
    if risk_score >= 3: status = "🔴"
    
    return status, ", ".join(alerts), risk_score, effective_wind, pop

# --- UI START ---
st.title("🚛 Route Safety Commander")

# --- TIMEZONE FIX ---
try:
    now_pt = pd.Timestamp.now(tz='America/Los_Angeles')
    st.caption(f"Last System Check: {now_pt.strftime('%I:%M %p PT')}")
except:
    st.caption(f"Last System Check: {datetime.now().strftime('%I:%M %p UTC')}")

# 1. MASTER DATE SELECTOR
ref_data = fetch_hourly_data(LOCATIONS["McDonald Pass"])
if not ref_data:
    st.error("Offline. Check connection.")
    st.stop()

# --- DATE LOGIC ---
unique_dates = []
seen_dates = set()

for p in ref_data:
    dt = parser.parse(p['startTime'])
    date_str = dt.strftime('%A, %b %d')
    if date_str not in seen_dates:
        seen_dates.add(date_str)
        unique_dates.append(date_str)

selected_date_str = st.selectbox("📅 Plan for:", unique_dates[:5])

# --- DATA PROCESSING ---
daily_risks = []
processed_data = {}

for name, url in LOCATIONS.items():
    raw = fetch_hourly_data(url)
    if not raw: continue
    
    day_rows = []
    max_risk = 0
    
    for hour in raw:
        dt = parser.parse(hour['startTime'])
        date_str = dt.strftime('%A, %b %d')
        
        if date_str == selected_date_str:
            status, alert, score, wind_val, pop_val = analyze_hour(hour, name)
            
            h = dt.hour
            # Check risk only during drive times
            if h in OUTBOUND_HOURS or h in RETURN_HOURS:
                if score > max_risk: max_risk = score
            
            weather_display = add_weather_icon(hour['shortForecast'])
            
            day_rows.append({
                "Hour": dt.hour,
                "Time": dt.strftime('%I %p'),
                "Temp": f"{hour['temperature']}°",
                "Precip %": f"{pop_val}%" if pop_val > 0 else "-",
                "Wind": f"{wind_val} {hour['windDirection']}",
                "Weather": weather_display,
                "Status": status,
                "Alerts": alert
            })
    
    processed_data[name] = pd.DataFrame(day_rows)
    daily_risks.append(max_risk)

# --- SECTION 1: MISSION DASHBOARD ---
overall_risk = max(daily_risks) if daily_risks else 0

st.write("---")
if overall_risk == 0:
    st.success("✅ MISSION STATUS: GO")
elif overall_risk == 1:
    st.warning("⚠️ MISSION STATUS: CAUTION")
elif overall_risk >= 2:
    st.error("🛑 MISSION STATUS: HIGH RISK")
st.write("---")

# --- SECTION 2: THE DRIVE ---
tab_out, tab_ret, tab_full = st.tabs(["🚀 Outbound (AM)", "↩️ Return (PM)", "📋 Details"])

def render_trip_table(hours_filter, title):
    st.subheader(title)
    
    for name in LOCATIONS.keys():
        if name in processed_data:
            df = processed_data[name]
            trip_df = df[df['Hour'].isin(hours_filter)]
            
            if not trip_df.empty:
                leg_risk = trip_df['Status'].astype(str).str.contains('🔴|🟠').any()
                header_icon = "⚠️" if leg_risk else "✅"
                
                with st.expander(f"{header_icon} {name}", expanded=leg_risk):
                    # NEW COLUMN ORDER: Time | Temp | Precip % | Wind | Weather | Alerts
                    display_df = trip_df[['Time', 'Temp', 'Precip %', 'Wind', 'Weather', 'Alerts']]
                    st.dataframe(display_df, hide_index=True, use_container_width=True)

with tab_out:
    render_trip_table(OUTBOUND_HOURS, f"Eastbound: {selected_date_str}")

with tab_ret:
    render_trip_table(RETURN_HOURS, f"Westbound: {selected_date_str}")
    
    # SURVIVAL CHECK
    mcd_df = processed_data.get("McDonald Pass")
    if mcd_df is not None:
        late_df = mcd_df[mcd_df['Hour'].isin([16, 17, 18, 19, 20])]
        if not late_df.empty:
            min_temp = int(late_df.iloc[0]['Temp'].replace('°',''))
            if min_temp < 20:
                st.toast("🥶 Temp drop warning for late return!")
                st.info(f"Note: McDonald Pass drops to {min_temp}°F by evening.")

with tab_full:
    st.write("Full 24-hour breakdown for all passes.")
    location_select = st.selectbox("Select Location", list(LOCATIONS.keys()))
    if location_select in processed_data:
        st.dataframe(processed_data[location_select][['Time', 'Temp', 'Precip %', 'Wind', 'Weather', 'Alerts']], hide_index=True)

st.markdown("---")
st.markdown("**Essential Links:** [Idaho 511](https://511.idaho.gov/) | [MDT Maps](https://www.mdt.mt.gov/travinfo/)")
