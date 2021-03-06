# mqtt broker where dsmr-reader publishes the dsmr/json topic
mqtt_broker = "127.0.0.1"

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

# Print debug messages?
debug = False
