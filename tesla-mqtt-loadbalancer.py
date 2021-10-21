#!/usr/bin/python3

import paho.mqtt.client as mqtt
import sys
import json
import time
from datetime import datetime
from math import radians, sin, cos, sqrt, atan2
import teslapy
from config import mqtt_broker, tesla_user, max_current, baseload, twc_min, twc_max, twc_latitude, twc_longitude, debug

# Initial values
current1 = current2 = current3 = -1

def dprint(*objects, **argv):
  if debug:
    now=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(now, *objects, **argv)

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
      current_max = max(current1, current2, current3)
      # could a Tesla charge session be going on?
      if current_max >= baseload + twc_min:
        # poll the Tesla for charging state
        try:
          vehicle_data = vehicles[0].get_vehicle_data()
          retry=0
        except teslapy.HTTPError as e:
          print(f"{type(e).__name__}: {str(e)}")
          vehicle_data = {}
          if retry > 20:
            print("Too many errors, exiting.")
            sys.exit(1)
          retry += 1
        # only actually do something if the Tesla is charging
        charge_state = vehicle_data.get('charge_state',{})
        if charge_state.get('charging_state') and charge_state['charging_state'] == "Charging":
          # is the Tesla within 500 meters from home?
          local_charge = get_distance(vehicle_data['drive_state']['latitude'], vehicle_data['drive_state']['longitude']) < 0.5
          tesla_amps = charge_state['charger_actual_current']
          overshoot = current_max > max_current
          undershoot = current_max < max_current and tesla_amps < twc_max
          dprint(f"tesla_amps   = {tesla_amps}")
          dprint(f"current_max  = {current_max}")
          dprint(f"local_charge = {local_charge}")
          dprint(f"overshoot    = {overshoot}")
          dprint(f"undershoot   = {undershoot}")
          # is there a need to adjust the charging speed?
          if local_charge and (overshoot or undershoot):
            new_amps = int(max_current - max(current_max,tesla_amps) + tesla_amps)
            dprint(f"new_amps     = {new_amps}")
            if overshoot:
              max_amps = max(new_amps, twc_min)
            else:
              max_amps = min(new_amps, twc_max)
            dprint(f"max_amps     = {max_amps}")
            # set the new charging speed
            vehicles[0].command('CHARGING_AMPS', charging_amps=max_amps)
            # let things settle after changing amps
            time.sleep(20)
      time.sleep(10)
