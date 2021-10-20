#!/usr/bin/python3

import paho.mqtt.client as mqtt
import sys
import json
import time
from math import radians, sin, cos, sqrt, atan2
import teslapy
from config import mqtt_broker, tesla_user, max_current, twc_min, twc_max, twc_latitude, twc_longitude, debug

# Initial values
current1 = current2 = current3 = -1

def dprint(*objects, **argv):
  if debug:
    print(*objects, **argv)

def get_distance(latitude, longitude):
  # https://www.kite.com/python/answers/how-to-find-the-distance-between-two-lat-long-coordinates-in-python
  R = 6373.0
  lat1 = radians(latitude)
  lon1 = radians(longitude)
  lat2 = radians(twc_latitude)
  lon2 = radians(twc_longitude)
  dlon = lon2 - lon1
  dlat = lat2 - lat1
  a = sin(dlat / 2)**2 + cos(lat1) * cos(lat2) * sin(dlon / 2)**2
  c = 2 * atan2(sqrt(a), sqrt(1 - a))
  distance = R * c
  dprint(f"distance = {distance}")
  return distance

def on_message(client, userdata, msg):
  global current1, current2, current3
  m_decode=str(msg.payload.decode("utf-8","ignore"))
  m=json.loads(m_decode)
  current1 = m.get('phase_power_current_l1', current1)
  current2 = m.get('phase_power_current_l2', current2)
  current3 = m.get('phase_power_current_l3', current3)

def mqtt_init():
  client = mqtt.Client("P1")
  client.on_message=on_message
  client.connect(mqtt_broker)
  client.subscribe("dsmr/json")
  client.loop_start()

if __name__ == "__main__":
  mqtt_init()
  with teslapy.Tesla(tesla_user) as tesla:
    try:
      tesla.fetch_token()
      vehicles = tesla.vehicle_list()
    except teslapy.HTTPError as e:
      print(f"{type(e).__name__}: {str(e)}")
      sys.exit(1)
    retry=0
    while True:
      try:
        vehicle_state = vehicles[0].get_vehicle_data()
        retry=0
      except teslapy.HTTPError as e:
        print(f"{type(e).__name__}: {str(e)}")
        vehicle_state = {}
        if retry > 20:
          print("Too many errors, exiting.")
          sys.exit(1)
        retry += 1
      charge_state = vehicle_state.get('charge_state',{})
      if charge_state.get('charging_state') and charge_state['charging_state'] == "Charging":
        local_charge = get_distance(vehicle_state['drive_state']['latitude'], vehicle_state['drive_state']['longitude']) < 0.5
        tesla_amps = charge_state['charger_actual_current']
        current_max = max(current1, current2, current3)
        overshoot = current_max > max_current
        undershoot = current_max < max_current and tesla_amps < twc_max
        dprint(f"tesla_amps   = {tesla_amps}")
        dprint(f"current_max  = {current_max}")
        dprint(f"local_charge = {local_charge}")
        dprint(f"overshoot    = {overshoot}")
        dprint(f"undershoot   = {undershoot}")
        if local_charge and (overshoot or undershoot):
          new_amps = int(max_current - max(current_max,tesla_amps) + tesla_amps)
          dprint(f"new_amps     = {new_amps}")
          if overshoot:
            max_amps = max(new_amps, twc_min)
          else:
            max_amps = min(new_amps, twc_max)
          dprint(f"max_amps     = {max_amps}")
          vehicles[0].command('CHARGING_AMPS', charging_amps=max_amps)
          # let things settle after changing amps
          time.sleep(20)
      time.sleep(10)
