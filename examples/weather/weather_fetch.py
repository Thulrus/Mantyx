#!/usr/bin/env python3

import datetime
import sys

import requests

# ======================
# USER CONFIGURATION
# ======================

LATITUDE = 40.76
LONGITUDE = -111.89
TIMEZONE = "auto"

TELEGRAM_BOT_TOKEN = "8562459368:AAFXCWlbuyo6Xv_v1MlGywDzgUD4q1iDmJU"
TELEGRAM_CHAT_ID = "-4516468692"

# ======================
# OPEN-METEO WEATHER CODE MAP
# ======================

WEATHER_CODES = {
    0: "Clear skies",
    1: "Mostly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Foggy",
    48: "Icy fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Heavy drizzle",
    61: "Light rain",
    63: "Moderate rain",
    65: "Heavy rain",
    71: "Light snow",
    73: "Moderate snow",
    75: "Heavy snow",
    80: "Rain showers",
    81: "Heavy rain showers",
    82: "Violent rain showers",
    95: "Thunderstorms",
    99: "Thunderstorms with hail",
}

# ======================
# FUNCTIONS
# ======================


def fetch_weather():
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "daily": [
            "weathercode",
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_probability_max",
            "precipitation_sum",
            "windspeed_10m_max",
        ],
        "temperature_unit": "fahrenheit",
        "windspeed_unit": "mph",
        "precipitation_unit": "inch",
        "timezone": TIMEZONE,
    }

    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    return response.json()


def build_advice(temp_high, precip_prob, wind):
    advice = []

    if temp_high < 45:
        advice.append("It will be cold — dress warmly.")
    elif temp_high < 60:
        advice.append("A light jacket is a good idea.")
    elif temp_high > 85:
        advice.append("Expect heat — stay hydrated.")

    if precip_prob >= 60:
        advice.append("Rain is likely — bring an umbrella.")
    elif precip_prob >= 30:
        advice.append("There is a chance of rain later in the day.")

    if wind >= 20:
        advice.append("It will be quite windy.")

    return " ".join(advice)


def format_message_old(weather):
    daily = weather["daily"]
    idx = 0

    date = datetime.date.fromisoformat(daily["time"][idx])
    date_str = date.strftime("%A, %B %d")

    weather_code = daily["weathercode"][idx]
    conditions = WEATHER_CODES.get(weather_code, "Uncertain conditions")

    temp_high = daily["temperature_2m_max"][idx]
    temp_low = daily["temperature_2m_min"][idx]
    precip_prob = daily["precipitation_probability_max"][idx]
    precip_sum = daily["precipitation_sum"][idx]
    wind = daily["windspeed_10m_max"][idx]

    advice = build_advice(temp_high, precip_prob, wind)

    message = (
        f"Good morning.\n\n"
        f"Here is your weather forecast for {date_str}:\n\n"
        f"Conditions: {conditions}\n"
        f"High: {temp_high:.0f}°F\n"
        f"Low: {temp_low:.0f}°F\n"
        f"Wind: Up to {wind:.0f} mph\n"
        f"Chance of precipitation: {precip_prob}%\n"
        f"Expected precipitation: {precip_sum:.2f} in\n\n"
        f"{advice}"
    )

    return message.strip()


def format_message(weather):
    daily = weather["daily"]
    idx = 0

    date = datetime.date.fromisoformat(daily["time"][idx])
    date_str = date.strftime("%A, %B %d")

    weather_code = daily["weathercode"][idx]
    conditions = WEATHER_CODES.get(weather_code, "Mixed conditions")

    temp_high = daily["temperature_2m_max"][idx]
    temp_low = daily["temperature_2m_min"][idx]
    precip_prob = daily["precipitation_probability_max"][idx]
    precip_sum = daily["precipitation_sum"][idx]
    wind = daily["windspeed_10m_max"][idx]

    advice = build_advice(temp_high, precip_prob, wind)

    # Emoji selection
    if weather_code in (0, 1):
        sky_emoji = "☀️"
    elif weather_code in (2,):
        sky_emoji = "⛅"
    elif weather_code in (3, 45, 48):
        sky_emoji = "☁️"
    elif weather_code in (51, 53, 55, 61, 63, 65, 80, 81, 82):
        sky_emoji = "🌧️"
    elif weather_code in (71, 73, 75):
        sky_emoji = "❄️"
    elif weather_code in (95, 99):
        sky_emoji = "⛈️"
    else:
        sky_emoji = "🌤️"

    # Friendly summary line
    if precip_prob >= 60:
        headline = "A wet day ahead."
    elif temp_high >= 85:
        headline = "A warm one today."
    elif temp_high <= 45:
        headline = "A chilly day from start to finish."
    else:
        headline = "A pretty typical day overall."

    wind = "" if wind == 0 else (f"💨 Wind\n" f"Up to {wind:.0f} mph\n\n")

    rain = (
        ""
        if precip_prob == 0
        else (f"🌧️ Rain\n" f"Chance: {precip_prob}%\n" f"Expected: {precip_sum:.2f} in\n\n")
    )

    message = (
        f"{sky_emoji} Good morning!\n"
        f"{headline}\n\n"
        f"📅 {date_str}\n"
        f"{conditions}\n\n"
        f"🌡️ Temperatures\n"
        f"High: {temp_high:.0f}°F\n"
        f"Low: {temp_low:.0f}°F\n\n"
        f"{wind}"
        f"{rain}"
        f"💡 {advice}\n"
        f"Have a great day out there!"
    )

    return message


def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}

    response = requests.post(url, json=payload, timeout=10)
    response.raise_for_status()


# ======================
# MAIN
# ======================


def main():
    try:
        weather = fetch_weather()
        message = format_message(weather)
        send_telegram(message)
        # print(message)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
