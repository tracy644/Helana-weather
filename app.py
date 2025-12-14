import streamlit as st
import requests
import pandas as pd
from dateutil import parser
from datetime import datetime, timedelta
import math
import re

# --- CONFIGURATION ---
st.set_page_config(page_title="Winter Logistics Pro", page_icon="🚛", layout="centered")

# Coordinates (for Alerts)
COORDINATES = {
    "4th of July Pass": "47.548,-116.503",
    "Lookout Pass": "47.456,-115.696",
    "Missoula Valley": "46.916,-114.090",
    "McDonald Pass": "46.586,-112.311"
}

# NWS Hourly Data Endpoints
LOCATIONS = {
    "4th of July Pass": "https://api.weather.gov/gridpoints/OTX/168,102/forecast/hourly",
    "Lookout Pass": "https://api.weather.gov/gridpoints/MSO/56,102/forecast/hourly",
    "Missoula Valley": "https://api.weather.gov/gridpoints/MSO/86,76/forecast/hourly",
    "McDonald Pass": "https://api.weather.gov/gridpoints/TFX/62,50/forecast/hourly"
}

# Route Orders
ORDER_EASTBOUND = ["4th of July Pass", "Lookout Pass", "Missoula Valley", "McDonald Pass"]
ORDER_WESTBOUND = ["McDonald Pass", "Missoula Valley", "Lookout Pass", "4th of July Pass"]

# Travel Windows
OUTBOUND_HOURS = [7, 8, 9, 10, 11, 12]
RETURN_HOURS = [12, 13, 14, 15, 16, 17, 18, 19]

# --- LOGIC ENGINE ---
@st.cache_data(ttl=900) 
def fetch_hourly_data(url):
    try:
        headers = {'User-Agent': '(winter-logistics-tool, contact@example.com)'}
        r = requests.get(url, headers=headers, timeout=5)
        r.raise_for_status()
        return r.json()['properties']['periods']
    except:
        return []

@st.cache_data(ttl=300)
def fetch_active_alerts(lat_lon_str):
    url = f"https://api.weather.gov/alerts/active?point={lat_lon_str}"
    try:
        headers = {'User-Agent': '(winter-logistics-tool, contact@example.com)'}
        r = requests.get(url, headers=headers, timeout=5)
        r.raise_for_status()
        data = r.json()
        alerts = []
        for f in data.get('features', []):
            event = f['properties']['event']
            # Filter for relevant alerts
            if any(x in event for x in ["Winter", "Wind", "Ice", "Blizzard", "Snow", "Flood", "Storm"]):
                alerts.append(event.upper())
        return list(set(alerts))
    except:
        return []

def get_int(val):
    if val is None: return 0
    if isinstance(val, dict) and 'value' in val: val = val['value']
    nums = re.findall(r'\d+', str(val))
    return int(nums[0]) if nums else 0

def add_weather_icon(forecast_text):
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
    if temp_f > 50 or speed_mph < 3: return temp_f
    return 35.74 + (0.6215 * temp_f) - (35.75 * math.pow(speed_mph, 0.16)) + (0.4275 * temp_f * math.pow(speed_mph, 0.16))

def analyze_hour(row, location_name, trip_direction):
    risk_score = 0
    alerts = []
    major_reasons = [] # These are collected for the top summary
    
    temp = row['temperature']
    short_forecast = row['shortForecast'].lower()
    direction = row['windDirection']
    is_daytime = row['isDaytime']
    
    # WIND
    sustained = get_int(row.get('windSpeed', 0))
    gust = get_int(row.get('windGust', 0))
    effective_wind = max(sustained, gust)
    pop = get_int(row.get('probabilityOfPrecipitation', 0))
    
    # 1. Road Surface
    if "snow" in short_forecast or "ice" in short_forecast:
        if temp <= 32:
            risk_score += 2
            alerts.append("❄️ Icy Roads")
            major_reasons.append("Icy Roads")
        else:
            risk_score += 1
            alerts.append("💧 Slush")
            major_reasons.append("Slush")
    elif "rain" in short_forecast:
        if temp <= 32:
            risk_score += 3
            alerts.append("🧊 FREEZING RAIN")
            major_reasons.append("FREEZING RAIN")
        elif temp <= 37:
            risk_score += 1
            alerts.append("🧊 Possible Black Ice")
            major_reasons.append("Black Ice Risk")
            
    # 2. Wind
    if effective_wind >= 45:
        risk_score += 2
        alerts.append(f"💨 GUSTS {effective_wind} MPH")
        major_reasons.append(f"High Winds ({effective_wind} mph)")
    elif effective_wind >= 30:
        risk_score += 1
        alerts.append(f"💨 Windy ({effective_wind})")
        major_reasons.append("Windy conditions")
    elif "breezy" in short_forecast or "windy" in short_forecast:
        if effective_wind < 20: alerts.append("💨 Breezy")

    # 3. Crosswind
    if "McDonald" in location_name and effective_wind > 20:
        if direction in ['N', 'NNE', 'NNW', 'S', 'SSE', 'SSW']:
            risk_score += 1
            alerts.append("↔️ CROSSWIND")
            major_reasons.append("Crosswinds")

    # 4. Sun Glare
    hour_int = parser.parse(row['startTime']).hour
    if "sunny" in short_forecast or "clear" in short_forecast:
        if trip_direction == "East" and 7 <= hour_int <= 10:
            alerts.append("😎 Sun Glare")
            major_reasons.append("Sun Glare")
        if trip_direction == "West" and 15 <= hour_int <= 18:
            alerts.append("😎 Sun Glare")
            major_reasons.append("Sun Glare")

    # 5. Wind Chill
    wc = calculate_wind_chill(temp, effective_wind)
    if wc < 0:
        risk_score += 1
        alerts.append(f"🥶 Chill {int(wc)}°")
        major_reasons.append("Dangerous Wind Chill")

    status = "🟢"
    if risk_score == 1: status = "🟡"
    if risk_score >= 2: status = "🟠"
    if risk_score >= 3: status = "🔴"
    
    return status, ", ".join(alerts), risk_score, effective_wind, pop, is_daytime, major_reasons

# --- UI START ---
st.title("🚛 Route Safety Commander")

# Timezone
try:
    now_pt = pd.Timestamp.now(tz='America/Los_Angeles')
    st.caption(f"Last System Check: {now_pt.strftime('%I:%M %p PT')}")
except:
    st.caption(f"Last System Check: {datetime.now().strftime('%I:%M %p UTC')}")

# Connection Check
ref_data = fetch_hourly_data(LOCATIONS["McDonald Pass"])
if not ref_data:
    st.error("Offline. Check connection.")
    st.stop()

# Date Logic
unique_dates = []
seen_dates = set()
for p in ref_data:
    dt = parser.parse(p['startTime'])
    date_str = dt.strftime('%A, %b %d')
    if date_str not in seen_dates:
        seen_dates.add(date_str)
        unique_dates.append(date_str)

selected_date_str = st.selectbox("📅 Plan for:", unique_dates[:5])

# --- PROCESSING ---
daily_risks = []
processed_data_out = {}
processed_data_ret = {}
summary_hazards = set()
official_alerts_found = []

for name, url in LOCATIONS.items():
    # Alerts
    lat_lon = COORDINATES.get(name)
    if lat_lon:
        active_alerts = fetch_active_alerts(lat_lon)
        if active_alerts:
            for alert in active_alerts:
                official_alerts_found.append(f"**{name}:** {alert}")
                # Force Max Risk for Warnings
                if "WARNING" in alert: daily_risks.append(3)
                elif "ADVISORY" in alert or "WATCH" in alert: daily_risks.append(2)

    # Hourly Data
    raw = fetch_hourly_data(url)
    if not raw: continue
    
    day_rows_out = []
    day_rows_ret = []
    max_risk = 0
    
    for hour in raw:
        dt = parser.parse(hour['startTime'])
        date_str = dt.strftime('%A, %b %d')
        
        if date_str == selected_date_str:
            h = dt.hour
            stat_o, alert_o, score_o, wind_o, pop_o, day_o, reasons_o = analyze_hour(hour, name, "East")
            stat_r, alert_r, score_r, wind_r, pop_r, day_r, reasons_r = analyze_hour(hour, name, "West")
            
            # Risk Summary Collection (Only for drive times)
            if h in OUTBOUND_HOURS:
                if score_o > max_risk: max_risk = score_o
                if score_o >= 1: 
                    for r in reasons_o: summary_hazards.add(f"{r} ({name})")
            
            if h in RETURN_HOURS:
                if score_r > max_risk: max_risk = score_r
                if score_r >= 1:
                    for r in reasons_r: summary_hazards.add(f"{r} ({name})")
            
            # Formatting
            weather_icon = add_weather_icon(hour['shortForecast'])
            wind_display = f"{wind_o} {hour['windDirection']}"
            time_display = dt.strftime('%I %p')
            if not day_o: time_display = f"🌑 {time_display}"
            else: time_display = f"☀️ {time_display}"

            row_data = {
                "Hour": dt.hour,
                "Time": time_display,
                "Temp": f"{hour['temperature']}°",
                "Precip %": f"{pop_o}%" if pop_o > 0 else "-",
                "Wind from": wind_display,
                "Weather": weather_icon,
                "Status (Out)": stat_o,
                "Alerts (Out)": alert_o,
                "Status (Ret)": stat_r,
                "Alerts (Ret)": alert_r
            }
            day_rows_out.append(row_data)
            day_rows_ret.append(row_data)
    
    processed_data_out[name] = pd.DataFrame(day_rows_out)
    processed_data_ret[name] = pd.DataFrame(day_rows_ret)
    daily_risks.append(max_risk)

# --- DASHBOARD ---
overall_risk = max(daily_risks) if daily_risks else 0

st.write("---")

# 1. OFFICIAL ALERTS
if official_alerts_found:
    st.error("🚨 **OFFICIAL NWS ALERTS ACTIVE:**")
    for alert in official_alerts_found:
        st.write(f"- {alert}")
    st.write("---")

# 2. STATUS RATING
if overall_risk == 0:
    st.success("✅ MISSION STATUS: GO")
    st.caption("No significant weather hazards detected.")
elif overall_risk == 1:
    st.warning("⚠️ MISSION STATUS: CAUTION")
elif overall_risk >= 2:
    st.error("🛑 MISSION STATUS: HIGH RISK")

# 3. HAZARD SUMMARY (Fixed)
if overall_risk > 0:
    if summary_hazards:
        hazard_list = sorted(list(summary_hazards))
        # Logic to keep summary concise
        if len(hazard_list) > 5:
            summary_text = ", ".join(hazard_list[:5]) + "..."
        else:
            summary_text = ", ".join(hazard_list)
        st.info(f"**⚠️ Hazard Summary:** {summary_text}")
    else:
        # Fallback if risk is high but logic didn't capture a reason string
        st.info("**⚠️ Hazard Summary:** General Winter Conditions detected (Wind/Precip).")

st.write("---")
st.info("🕒 **Note:** All times are **LOCAL** to that specific pass.")

# --- TABS ---
tab_out, tab_ret, tab_full = st.tabs(["🚀 Outbound (AM)", "↩️ Return (PM)", "📋 Details"])

def render_trip_table(hours_filter, title, location_order, direction_key):
    st.subheader(title)
    data_source = processed_data_out if direction_key == "Out" else processed_data_ret
    
    for name in location_order:
        if name in data_source:
            df = data_source[name]
            trip_df = df[df['Hour'].isin(hours_filter)].copy()
            
            if not trip_df.empty:
                status_col = f"Status ({direction_key})"
                alert_col = f"Alerts ({direction_key})"
                leg_risk = trip_df[status_col].astype(str).str.contains('🔴|🟠').any()
                header_icon = "⚠️" if leg_risk else "✅"
                trip_df = trip_df.rename(columns={status_col: "Status", alert_col: "Alerts"})
                
                with st.expander(f"{header_icon} {name}", expanded=leg_risk):
                    display_df = trip_df[['Time', 'Temp', 'Precip %', 'Wind from', 'Weather', 'Alerts']]
                    st.dataframe(display_df, hide_index=True, use_container_width=True)

with tab_out:
    render_trip_table(OUTBOUND_HOURS, f"Eastbound: {selected_date_str}", ORDER_EASTBOUND, "Out")

with tab_ret:
    render_trip_table(RETURN_HOURS, f"Westbound: {selected_date_str}", ORDER_WESTBOUND, "Ret")
    
    if "McDonald Pass" in processed_data_ret:
        mcd_df = processed_data_ret["McDonald Pass"]
        late_df = mcd_df[mcd_df['Hour'].isin([16, 17, 18, 19, 20])]
        if not late_df.empty:
            min_temp = int(late_df.iloc[0]['Temp'].replace('°',''))
            if min_temp < 20:
                st.toast("🥶 Temp drop warning for late return!")
                st.info(f"Note: McDonald Pass drops to {min_temp}°F by evening.")

with tab_full:
    st.write("Full 24-hour breakdown.")
    location_select = st.selectbox("Select Location", list(LOCATIONS.keys()))
    if location_select in processed_data_out:
        df = processed_data_out[location_select]
        df = df.rename(columns={"Status (Out)": "Status", "Alerts (Out)": "Alerts"})
        st.dataframe(df[['Time', 'Temp', 'Precip %', 'Wind from', 'Weather', 'Alerts']], hide_index=True)

st.markdown("---")
st.markdown("**Essential Links:** [Idaho 511](https://511.idaho.gov/) | [MDT Maps](https://www.mdt.mt.gov/travinfo/)")
