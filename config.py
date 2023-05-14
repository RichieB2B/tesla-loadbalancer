# mqtt broker where dsmr-reader publishes the dsmr/json topic
mqtt_broker = "127.0.0.1"
# mqtt topic for dsmr-reader messages
mqtt_p1_topic = "dsmr/json"
# The order of reading the EV charging amps is:
#
# 1: use ev_meter_url if defined
# 2: use mqtt_ev_topic if defined
# 3: use Tesla API
#
# kWh meter API url for tools like mbmd, set to None to use MQTT or Tesla API
ev_meter_url = "http://localhost:8080/api/last/ORNO3P1.1"
# mqtt topic for EV Charger kWh meter, set to None to use Tesla API
mqtt_ev_topic = "mbmd/orno3p1-1"

# Tesla.com user name
tesla_user = "elon@tesla.com"

# Maximum current (amperage) your home connection supports
max_current = 25

# Current (amperage) that is always present in the home
# The Tesla will only be polled when amperage >= baseload + last_tesla_amps
baseload = 0

# Home charger settings: min/max current and location
# twc_safe: set amps to this level after charging session
twc_min = 1
twc_max = 24
twc_safe = 16
twc_latitude = 52.37821231816995
twc_longitude = 4.900513198963123

# Telsa sleep attempts in minutes
sleep = 15

# Track PV production?
# Valid values are: "normal", "pv" and "twcmanager"
# Can be overridden using web interface and in settings.json
pv_mode = "pv"

# mqtt topics to user for TWCManager when pv_mode is set to "twcmanager"
#mqtt_twc_chargenow_topic = "TWC/control/chargeNow"
#mqtt_twc_consumption_topic = "TWC/consumption"
#mqtt_twc_generation_topic = "TWC/generation"

# Flask web server
listen = "0.0.0.0"
port = 8088

# Print debug messages?
debug = False
