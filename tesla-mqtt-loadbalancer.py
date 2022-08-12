#!/usr/bin/python3 -u

import paho.mqtt.client as mqtt
import sys
import json
import time
import math
from datetime import datetime
from math import radians, sin, cos, sqrt, atan2
import teslapy
import requests
from config import mqtt_broker, mqtt_p1_topic, mqtt_ev_topic, ev_meter_url, ev_current, tesla_user, max_current, baseload, twc_min, twc_max, twc_safe, twc_latitude, twc_longitude, debug

# Initial values
current1 = current2 = current3 = -1
ev_current1 = ev_current2 = ev_current3 = -1
p1_delivered = p1_returned = p1_voltage_sum = 0
last_amps = twc_safe

def dprint(*objects, **argv):
  if debug:
    now=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(now, *objects, **argv)

def set_amps(vehicle, amps):
  try:
    # set it twice if < 5A, see https://github.com/tdorssers/TeslaPy/pull/42
    if amps > 0 and amps < 5:
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
  global current1, current2, current3, p1_delivered, p1_returned, p1_voltage_sum
  m_decode=str(msg.payload.decode("utf-8","ignore"))
  m=json.loads(m_decode)
  current1 = m.get('phase_power_current_l1', current1)
  current2 = m.get('phase_power_current_l2', current2)
  current3 = m.get('phase_power_current_l3', current3)
  p1_delivered = float(m.get('electricity_currently_delivered', p1_delivered))
  p1_returned = float(m.get('electricity_currently_returned', p1_returned))
  v1 = float(m.get('phase_voltage_l1', 230))
  v2 = float(m.get('phase_voltage_l2', 230))
  v3 = float(m.get('phase_voltage_l3', 230))
  p1_voltage_sum = v1 + v2 + v3

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
  ev_current1 = m.get(ev_current + 'L1', ev_current1)
  ev_current2 = m.get(ev_current + 'L2', ev_current2)
  ev_current3 = m.get(ev_current + 'L3', ev_current3)

def mqtt_ev_init():
  client = mqtt.Client("EV")
  client.on_message=on_ev_message
  client.connect(mqtt_broker)
  client.subscribe(mqtt_ev_topic)
  client.loop_start()

def get_ev_current(url):
  global ev_current1, ev_current2, ev_current3
  try:
    result = requests.get(url, timeout=5)
  except requests.exceptions.ReadTimeout as e:
    return max(ev_current1, ev_current2, ev_current3)
  try:
    data = result.json()
  except Exception as e:
    print(f'{type(e).__name__}: {str(e)}')
    print(result.text)
    return max(ev_current1, ev_current2, ev_current3)
  current1 = data.get(ev_current + 'L1', ev_current1)
  current2 = data.get(ev_current + 'L2', ev_current2)
  current3 = data.get(ev_current + 'L3', ev_current3)
  ev_current1 = current1
  ev_current2 = current2
  ev_current3 = current3
  return math.ceil(max(current1, current2, current3))

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
      # or is there negative power use (PV production)?
      pv_production = p1_returned > 0.0 or p1_delivered * 1000 < last_amps * p1_voltage_sum
      if current_max >= baseload + last_amps or pv_production:
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
          if ev_meter_url:
            tesla_amps = get_ev_current(ev_meter_url)
          elif mqtt_ev_topic:
            tesla_amps = max(ev_current1, ev_current2, ev_current3)
          else:
            tesla_amps = charge_state['charger_actual_current']
          last_amps = tesla_amps
          charge_amps = charge_state['charge_amps']
          overshoot = current_max > max_current
          undershoot = current_max < max_current and charge_amps < twc_max and max_current - current_max > 1
          if pv_production:
            undershoot = int(p1_returned * 1000 / p1_voltage_sum) > 0
            overshoot = int(p1_delivered * 1000 / p1_voltage_sum) > 0
            dprint("PV production detected")
            dprint(f"returned     = {int(p1_returned * 1000 / p1_voltage_sum)}")
            dprint(f"delivered    = {int(p1_delivered * 1000 / p1_voltage_sum)}")
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
              if pv_production:
                if overshoot:
                  new_amps = last_amps - int(p1_delivered * 1000 / p1_voltage_sum)
                else:
                  new_amps = last_amps + int(p1_returned * 1000 / p1_voltage_sum)
              else:
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
