#!/usr/bin/python3 -u

import paho.mqtt.client as mqtt
import sys
import json
import time
from datetime import datetime
from math import radians, sin, cos, sqrt, atan2
import teslapy
from config import mqtt_broker, mqtt_p1_topic, mqtt_ev_topic, mqtt_ev_current, tesla_user, max_current, baseload, twc_min, twc_max, twc_safe, twc_latitude, twc_longitude, debug

# Initial values
current1 = current2 = current3 = -1
ev_current1 = ev_current2 = ev_current3 = -1
last_amps = twc_safe

def dprint(*objects, **argv):
  if debug:
    now=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(now, *objects, **argv)

def set_amps(vehicle, amps):
  try:
    # set it twice if < 5A, see https://github.com/tdorssers/TeslaPy/pull/42
    if amps < 5:
      vehicle.command('CHARGING_AMPS', charging_amps=amps)
      time.sleep(5)
    result = vehicle.command('CHARGING_AMPS', charging_amps=amps)
  except teslapy.HTTPError as e:
    print(f"{type(e).__name__} during CHARGING_AMPS: {str(e)}")
    result = {}
  # let things settle after changing amps
  time.sleep(15)
  return result

def set_safe_amps(vehicle):
  global last_amps
  now=datetime.now().strftime("%b %d %H:%M:%S")
  print(f"{now} Changing seems over, setting Tesla to {twc_safe:>2}A.", flush=True)
  last_amps = twc_safe
  set_amps(vehicle, twc_safe)

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

def on_p1_message(client, userdata, msg):
  global current1, current2, current3
  m_decode=str(msg.payload.decode("utf-8","ignore"))
  m=json.loads(m_decode)
  current1 = m.get('phase_power_current_l1', current1)
  current2 = m.get('phase_power_current_l2', current2)
  current3 = m.get('phase_power_current_l3', current3)

def mqtt_p1_init():
  client = mqtt.Client("P1")
  client.on_message=on_p1_message
  client.connect(mqtt_broker)
  client.subscribe(mqtt_p1_topic)
  client.loop_start()

def on_ev_message(client, userdata, msg):
  global ev_current1, ev_current2, ev_current3
  m_decode=str(msg.payload.decode("utf-8","ignore"))
  m=json.loads(m_decode)
  ev_current1 = m.get(mqtt_ev_current + 'L1', ev_current1)
  ev_current2 = m.get(mqtt_ev_current + 'L2', ev_current2)
  ev_current3 = m.get(mqtt_ev_current + 'L3', ev_current3)

def mqtt_ev_init():
  client = mqtt.Client("EV")
  client.on_message=on_ev_message
  client.connect(mqtt_broker)
  client.subscribe(mqtt_ev_topic)
  client.loop_start()

if __name__ == "__main__":
  mqtt_p1_init()
  if mqtt_ev_topic:
    mqtt_ev_init()
  with teslapy.Tesla(tesla_user) as tesla:
    try:
      tesla.fetch_token()
      vehicles = tesla.vehicle_list()
    except teslapy.HTTPError as e:
      print(f"{type(e).__name__}: {str(e)}")
      sys.exit(1)
    charging = False
    debounce = 0
    retry=0
    while True:
      current_max = max(current1, current2, current3)
      # could a Tesla charge session be going on?
      if current_max >= baseload + last_amps:
        # poll the Tesla for charging state
        try:
          vehicle_data = vehicles[0].get_vehicle_data()
          retry=0
        except Exception as e:
          now=datetime.now().strftime("%b %d %H:%M:%S")
          print(f"{now} {type(e).__name__}: {str(e)}")
          vehicle_data = {}
          if retry > 60:
            print(f"{now} Too many errors, exiting.")
            sys.exit(1)
          retry += 1
          time.sleep(30)
          continue
        # only actually do something if the Tesla is charging
        charge_state = vehicle_data.get('charge_state',{})
        if charge_state.get('charging_state') and charge_state['charging_state'] == "Charging":
          # is the Tesla within 500 meters from home?
          local_charge = get_distance(vehicle_data['drive_state']['latitude'], vehicle_data['drive_state']['longitude']) < 0.5
          if mqtt_ev_topic:
            tesla_amps = max(ev_current1, ev_current2, ev_current3)
          else:
            tesla_amps = charge_state['charger_actual_current']
          last_amps = tesla_amps
          charge_amps = charge_state['charge_amps']
          overshoot = current_max > max_current
          undershoot = current_max < max_current and charge_amps < twc_max and max_current - current_max > 1
          dprint(f"tesla_amps   = {tesla_amps}")
          dprint(f"current_max  = {current_max}")
          dprint(f"local_charge = {local_charge}")
          dprint(f"overshoot    = {overshoot}")
          dprint(f"undershoot   = {undershoot}")
          # is this a charge at home?
          if local_charge:
            charging = True
            # reset debounce counter
            debounce = 0
            # is there a need to adjust the charging speed?
            if overshoot or undershoot:
              new_amps = int(max_current - max(current_max,tesla_amps) + tesla_amps)
              dprint(f"new_amps     = {new_amps}")
              if overshoot:
                max_amps = max(new_amps, twc_min)
              else:
                max_amps = min(new_amps, twc_max)
              dprint(f"max_amps     = {max_amps}")
              now=datetime.now().strftime("%b %d %H:%M:%S")
              print(f"{now} Power usage is {current_max:>2}A, Tesla is using {tesla_amps:>2}A. Changing Tesla to {max_amps:>2}A.", flush=True)
              # set the new charging speed
              set_amps(vehicles[0], max_amps)
        else:
          # was a charging session just stopped?
          if charging and debounce > 3:
            # set safe amps in case load balancing is not running at next charge
            set_safe_amps(vehicles[0])
            charging = False
          # increase debounce counter
          debounce += 1
        # always wait at least 10 seconds between Tesla polls
        time.sleep(10)
      else:
        # was a charging session just stopped?
        if charging and debounce > 3:
          # set safe amps in case load balancing is not running at next charge
          set_safe_amps(vehicles[0])
          charging = False
        # increase debounce counter
        debounce += 1
        # Tesla was not polled, check DSMR data again soon
        time.sleep(2)
