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
        return r.json().get('properties', {}).get('periods', [])
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
            event = f.get('properties', {}).get('event', '')
            if any(x in event for x in ["Winter", "Wind", "Ice", "Blizzard", "Snow", "Flood"]):
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
    if not forecast_text: return ""
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
    if temp_f is None or speed_mph is None: return temp_f
    if temp_f > 50 or speed_mph < 3: return temp_f
    return 35.74 + (0.6215 * temp_f) - (35.75 * math.pow(speed_mph, 0.16)) + (0.4275 * temp_f * math.pow(speed_mph, 0.16))

def analyze_hour(row, location_name, trip_direction):
    risk_score = 0
    alerts = []
    major_reasons = []
    
    # Safe Extraction
    temp = row.get('temperature', 32)
    short_forecast = row.get('shortForecast', '').lower()
    direction = row.get('windDirection', 'N')
    is_daytime = row.get('isDaytime', True)
    
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
        risk_score
