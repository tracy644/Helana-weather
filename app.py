import streamlit as st
import requests
import pandas as pd
from dateutil import parser
from datetime import datetime, timedelta
import math

# --- CONFIGURATION ---
st.set_page_config(page_title="Winter Logistics Pro", page_icon="🚛", layout="mobile")

# NWS Hourly Endpoints (Higher precision)
LOCATIONS = {
    "4th of July Pass": "https://api.weather.gov/gridpoints/OTX/168,102/forecast/hourly",
    "Lookout Pass": "https://api.weather.gov/gridpoints/MSO/56,102/forecast/hourly",
    "Missoula Valley": "https://api.weather.gov/gridpoints/MSO/86,76/forecast/hourly",
    "McDonald Pass": "https://api.weather.gov/gridpoints/TFX/62,50/forecast/hourly"
}

# Travel Windows (Approximate hours to filter for)
# Outbound: 7 AM to Noon
OUTBOUND_HOURS = [7, 8, 9, 10, 11, 12]
# Return: 1 PM to 6 PM
RETURN_HOURS = [13, 14, 15, 16, 17, 18]

# --- LOGIC ENGINE ---
@st.cache_data(ttl=1800) # Cache for 30 mins
def fetch_hourly_data(url):
    try:
        headers = {'User-Agent': '(winter-logistics-tool, contact@example.com)'}
        r = requests.get(url, headers=headers, timeout=5)
        r.raise_for_status()
        data = r.json()
        return data['properties']['periods']
    except:
        return []

def calculate_wind_chill(temp_f, speed_mph):
    """NWS Wind Chill Formula"""
    if temp_f > 50 or speed_mph < 3:
        return temp_f
    return 35.74 + (0.6215 * temp_f) - (35.75 * math.pow(speed_mph, 0.16)) + (0.4275 * temp_f * math.pow(speed_mph, 0.16))

def analyze_hour(row, location_name):
    """Returns a Risk Score (0-3) and a Status String"""
    risk_score = 0
    alerts = []
    
    temp = row['temperature']
    wind = int(row['windSpeed'].split()[0]) if 'windSpeed' in row else 0
    short_forecast = row['shortForecast'].lower()
    direction = row['windDirection']
    
    # 1. Road Surface Risk
    if "snow" in short_forecast or "ice" in short_forecast:
        if temp <= 32:
            risk_score += 2 # Accumulation likely
            alerts.append("❄️ Icy Roads")
        else:
            risk_score += 1 # Slush
            alerts.append("💧 Slush/Wet Snow")
    elif "rain" in short_forecast and temp <= 34:
        risk_score += 3 # Freezing Rain Risk
        alerts.append("🧊 FREEZING RAIN RISK")
        
    # 2. Wind Risk
    if wind > 30:
        risk_score += 1
        alerts.append(f"💨 Gusts {wind}+")
    
    # 3. Crosswind Specific (McDonald Pass)
    if "McDonald" in location_name and wind > 25:
        if direction in ['N', 'NNE', 'NNW', 'S', 'SSE', 'SSW']:
            risk_score += 1
            alerts.append("↔️ CROSSWIND")

    # 4. Survival Risk (Wind Chill)
    wc = calculate_wind_chill(temp, wind)
    if wc < 0:
        risk_score += 1
        alerts.append(f"🥶 Chill {int(wc)}°")

    status = "🟢"
    if risk_score == 1: status = "🟡"
    if risk_score >= 2: status = "🟠"
    if risk_score >= 3: status = "🔴"
    
    return status, ", ".join(alerts), risk_score

# --- UI START ---
st.title("🚛 Route Safety Commander")
st.caption(f"Last System Check: {datetime.now().strftime('%H:%M')}")

# 1. MASTER DATE SELECTOR
# We fetch one location to get the available dates
ref_data = fetch_hourly_data(LOCATIONS["McDonald Pass"])
if not ref_data:
    st.error("Offline. Check connection.")
    st.stop()

# Extract unique dates from the hourly feed
unique_dates = sorted(list(set([parser.parse(p['startTime']).strftime('%A, %b %d') for p in ref_data])))
selected_date_str = st.selectbox("📅 Plan for:", unique_dates[:5]) # Show next 5 days

# --- DATA PROCESSING ---
# We process the data into a clean structure for the selected day
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
            status, alert, score = analyze_hour(hour, name)
            
            # Keep track of max risk for the Summary
            # We only care about max risk during DRIVE TIMES
            h = dt.hour
            if h in OUTBOUND_HOURS or h in RETURN_HOURS:
                if score > max_risk: max_risk = score
            
            day_rows.append({
                "Hour": dt.hour,
                "Time": dt.strftime('%I %p'),
                "Temp": f"{hour['temperature']}°",
                "Weather": hour['shortForecast'],
                "Wind": f"{hour['windSpeed']} {hour['windDirection']}",
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
    st.caption("Conditions look standard for winter travel.")
elif overall_risk == 1:
    st.warning("⚠️ MISSION STATUS: CAUTION")
    st.caption("Standard winter hazards (slush, moderate wind) present.")
elif overall_risk == 2:
    st.error("🛑 MISSION STATUS: HIGH RISK")
    st.caption("Significant hazards (Ice, High Winds, or Heavy Snow) detected.")
else:
    st.error("🚨 MISSION STATUS: NO-GO / EXTREME")
    st.caption("Freezing Rain or Severe Blizzard conditions forecast.")
st.write("---")

# --- SECTION 2: THE DRIVE ---
tab_out, tab_ret, tab_full = st.tabs(["🚀 Outbound (AM)", "↩️ Return (PM)", "📋 Details"])

def render_trip_table(hours_filter, title):
    st.subheader(title)
    
    for name in LOCATIONS.keys():
        if name in processed_data:
            df = processed_data[name]
            # Filter for specific hours
            trip_df = df[df['Hour'].isin(hours_filter)]
            
            if not trip_df.empty:
                # Check for Red/Orange flags in this specific leg
                leg_risk = trip_df['Status'].astype(str).str.contains('🔴|🟠').any()
                header_icon = "⚠️" if leg_risk else "✅"
                
                with st.expander(f"{header_icon} {name}", expanded=leg_risk):
                    # Clean up table for mobile
                    display_df = trip_df[['Time', 'Temp', 'Status', 'Alerts', 'Weather']]
                    st.dataframe(display_df, hide_index=True, use_container_width=True)

with tab_out:
    render_trip_table(OUTBOUND_HOURS, f"Eastbound: {selected_date_str}")

with tab_ret:
    render_trip_table(RETURN_HOURS, f"Westbound: {selected_date_str}")
    
    # SURVIVAL / TRAP CHECK
    # Check if temps drop below 20F or wind chill < 0 during return
    mcd_df = processed_data.get("McDonald Pass")
    if mcd_df is not None:
        late_df = mcd_df[mcd_df['Hour'].isin([16, 17, 18, 19, 20])] # Evening hours
        if not late_df.empty:
            min_temp = int(late_df.iloc[0]['Temp'].replace('°',''))
            if min_temp < 20:
                st.toast("🥶 Temp drop warning for late return!")
                st.info(f"Note: McDonald Pass drops to {min_temp}°F by evening. Don't get stranded.")

with tab_full:
    st.write("Full 24-hour breakdown for all passes.")
    location_select = st.selectbox("Select Location", list(LOCATIONS.keys()))
    if location_select in processed_data:
        st.dataframe(processed_data[location_select][['Time', 'Temp', 'Wind', 'Weather', 'Alerts']], hide_index=True)

# --- FOOTER ---
st.markdown("---")
st.markdown("**Essential Links:** [Idaho 511](https://511.idaho.gov/) | [MDT Maps](https://www.mdt.mt.gov/travinfo/)")