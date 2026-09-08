"""
WER 20210624

First attempt at having a parallel dedicated agent for weather and enclosure.
This code should be as simple and reliable as possible, no hanging variables,
etc.

This would be a good place to log the weather data and any enclosure history,
once this code is stable enough to run as a service.

"""


import os
import signal
import json
import shelve
import time
import socket
from pathlib import Path
import math
import calendar
import requests
import traceback
import ephem
import ptr_config
from api_calls import API_calls
import wema_events
from devices.observing_conditions import ObservingConditions
from devices.enclosure import Enclosure
from global_yard import g_dev
#import logging
from wema_utility import plog
# from pyowm import OWM
# from pyowm.utils import config
# from pyowm.utils import timestamps
# from pyowm.utils.config import get_default_config
# from pyowm.commons.databoxes import SubscriptionType
#from requests.adapters import HTTPAdapter, Retry
from dotenv import load_dotenv
load_dotenv(".env")
from ptr_endpoints import PTR_STATUS_ROOT, PTR_JOBS_ROOT, PTR_LOGS_ROOT
from wema_config import get_enc_status_custom
from wema_config import get_ocn_status_custom
import csv
#from requests.auth import HTTPBasicAuth

from astropy.coordinates import EarthLocation, AltAz, SkyCoord, get_body

from astropy.time import Time
import astropy.units as u

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import copy

# from sentinelsat import SentinelAPI, read_geojson, geojson_to_wkt
# from datetime import date

# # Australian weather service
# from weather_au import api

#from func_timeout import func_timeout, FunctionTimedOut
import numpy as np
#import http.client
#http.client.HTTPConnection.debuglevel = 1
#logging.getLogger("urllib3").setLevel(logging.DEBUG)
#from sklearn.linear_model import LinearRegression

import matplotlib.pyplot as plt
import pandas as pd
# import sys
# from scipy.fft import fft, ifft, fftfreq
# import numpy as np
# from scipy.signal import correlate
import seaborn as sns
#from sklearn.model_selection import train_test_split#,cross_val_predict, KFold
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_squared_error, r2_score
#from sklearn.preprocessing import PolynomialFeatures

#import rasterio

close_headers = {
    "Connection": "close"  # Forces the server to close the connection after the response
}

import pytz
import datetime
from datetime import timezone



def fit_cloud_prediction_model(df, directory):
    
    #directory = directory + '/weatherfits'
    if not os.path.exists(directory):
        os.makedirs(directory)
    
    # daytime model
    if not os.path.exists(directory + '/nighttime'):
        os.makedirs(directory+ '/nighttime')
    if not os.path.exists(directory + '/daytime'):
        os.makedirs(directory+ '/daytime')    
    
    file_date_string = str(datetime.datetime.now()).replace(' ', '_').split('.')[0].replace(':', '-')
    
    daytime_model=None
    nighttime_model=None

    # Manually add polynomial terms for specific features
    df['sky-ambient^2'] = df['sky-ambient'] ** 2
    features = ['sky_temp_C', 'sky-ambient',  'sky-ambient^2']#'phase_of_day', 'sky-ambient^2', 'sin_hour', 'cos_hour'] 'dew_point_depression',

    for part_of_day in ['daytime','nighttime']:        
        
        region_df=copy.deepcopy(df)
        
        if part_of_day == 'daytime':
            region_df = region_df[(region_df['sun_altitude'] > 0) ].copy()
            number_of_daytime_weather_observations=len(region_df)
        else:    
            region_df = region_df[(region_df['sun_altitude'] < 0) ].copy()  
            number_of_nighttime_weather_observations=len(region_df)
        
        # Trim the extreme values off... realistically MOST of the time it can be clear or cloudy
        # and we even aren't too particularly interested in the extremes... more the range
        # But only if there is enough observations within that range.
        filtered_df = region_df[(region_df['avg_forecast_cloudcover'] >= 5) & (region_df['avg_forecast_cloudcover'] <= 95)].copy()

        if len(filtered_df) >= 50:
            region_df = filtered_df.copy()  # apply the filter
        
        # Only consider those values where all the forecasts tend to agree on it.
        
        region_df['clouds_row_stdev'] = region_df[
            ['OWM_clouds', 'openmeteo_clouds', 
             'OWMClouds_inanhour', 'openmeteoclouds_inanhour', 
             'tomorrowio_nowclouds', 'tomorrowio_nexthourclouds',
             'pirate_clouds_now', 'pirate_clouds_inanhour', 
             'metocean_clouds_now', 'metocean_clouds_inanhour', 
             'worldweather_clouds_now', 'worldweather_clouds_inanhour']
        ].std(axis=1).copy()
        
        # Split the weather stuff into cloud ranges to apply threshholds        
        
        # Create masks for each range
        try:
            low_clouds = region_df['avg_forecast_cloudcover'].between(0, 20)
            mid_clouds = region_df['avg_forecast_cloudcover'].between(20, 80)
            high_clouds = region_df['avg_forecast_cloudcover'].between(80, 100)
                    
            # Compute thresholds
            low_cloud_thresh  = np.quantile(np.asarray(region_df.loc[low_clouds, 'clouds_row_stdev']), 0.2)
            mid_cloud_thresh  = np.quantile(np.asarray(region_df.loc[mid_clouds, 'clouds_row_stdev']), 0.2)
            high_cloud_thresh = np.quantile(np.asarray(region_df.loc[high_clouds, 'clouds_row_stdev']), 0.2)
            
            region_df = region_df[
                (low_clouds  & (region_df['clouds_row_stdev'] <= low_cloud_thresh)) |
                (mid_clouds  & (region_df['clouds_row_stdev'] <= mid_cloud_thresh)) |
                (high_clouds & (region_df['clouds_row_stdev'] <= high_cloud_thresh))
            ].copy()
        except:
            plog ("failed at splitting dataset by cloud levels... usually we don't have good coverage yet.")




        # 1) grab x and y
        x = region_df['avg_forecast_cloudcover'].to_numpy()
        y = region_df['sky_temp_C'].to_numpy()        
        
        # initial mask: everyone in
        mask = np.ones_like(y, dtype=bool)
        
        n_sigma   = 2.0     # how many σ out to reject
        max_iters = 5       # maximum number of cycles
        
        for i in range(max_iters):
            # 1) fit to the current inliers
            slope, intercept = np.polyfit(x[mask], y[mask], 1)
        
            # 2) compute residuals of all points to that fit
            resid = y - (slope*x + intercept)
        
            # 3) measure the scatter on the CURRENT inliers
            sigma = np.std(resid[mask])
        
            # 4) build a new mask
            new_mask = np.abs(resid) <= n_sigma * sigma
        
            # 5) if nothing changed, stop early
            if new_mask.sum() == mask.sum():
                break
            mask = new_mask
        
        # prepare your fit‐line for plotting
        x_line = np.linspace(x.min(), x.max(), 200)
        y_line = slope*x_line + intercept
        
        plt.figure(figsize=(6,4))
        plt.scatter(x[mask],    y[mask],    alpha=0.7, label='Inliers')
        plt.scatter(x[~mask],   y[~mask],   color='red', alpha=0.7, label='Outliers')
        plt.plot(x_line, y_line, color='black', linewidth=2, label=f'{n_sigma}σ fit')
        plt.legend()
        # plt.title('Sky Temperature vs Forecast Cloud Cover with Regression Line')
        # plt.xlabel('Average Forecast Cloud Cover (%)')
        # plt.ylabel('Sky Temperature (°C)')
        # plt.savefig(directory + '/' + part_of_day + '/skytempvsclouds_' + str(file_date_string) + '.png', dpi=300, bbox_inches='tight')
        # … set labels, title, save …    
        # plt.figure(figsize=(6, 4)) 
        # sns.regplot(x='avg_forecast_cloudcover', y='sky_temp_C', data=region_df)
        plt.title('Sky Temperature vs Forecast Cloud Cover with Regression Line')
        plt.xlabel('Average Forecast Cloud Cover (%)')
        plt.ylabel('Sky Temperature (°C)')
        plt.savefig(directory + '/' + part_of_day + '/skytempvsclouds_' + str(file_date_string) + '.png', dpi=300, bbox_inches='tight')

    
        # 1) grab x and y
        x = region_df['avg_forecast_cloudcover'].to_numpy()
        y = region_df['sky-ambient'].to_numpy()        
        
        # initial mask: everyone in
        mask = np.ones_like(y, dtype=bool)
        
        n_sigma   = 2.0     # how many σ out to reject
        max_iters = 5       # maximum number of cycles
        
        for i in range(max_iters):
            # 1) fit to the current inliers
            slope, intercept = np.polyfit(x[mask], y[mask], 1)
        
            # 2) compute residuals of all points to that fit
            resid = y - (slope*x + intercept)
        
            # 3) measure the scatter on the CURRENT inliers
            sigma = np.std(resid[mask])
        
            # 4) build a new mask
            new_mask = np.abs(resid) <= n_sigma * sigma
        
            # 5) if nothing changed, stop early
            if new_mask.sum() == mask.sum():
                break
            mask = new_mask
        
        # prepare your fit‐line for plotting
        x_line = np.linspace(x.min(), x.max(), 200)
        y_line = slope*x_line + intercept
        
        plt.figure(figsize=(6,4))
        plt.scatter(x[mask],    y[mask],    alpha=0.7, label='Inliers')
        plt.scatter(x[~mask],   y[~mask],   color='red', alpha=0.7, label='Outliers')
        plt.plot(x_line, y_line, color='black', linewidth=2, label=f'{n_sigma}σ fit')
        plt.legend()
        #sns.regplot(x='avg_forecast_cloudcover', y='sky-ambient', data=region_df)
        plt.xlabel('Average Forecast Cloud Cover (%)')
        plt.ylabel('Sky Temperature - Ambient Temperature (°C)')
        plt.title('Sky - Ambient Temperature vs Forecast Cloud Cover')
        
        
        plt.savefig(directory + '/' + part_of_day + '/skyminusambientvsclouds_' + str(file_date_string) + '.png', dpi=300, bbox_inches='tight')
    
    
        # 1) grab x and y
        x = region_df['avg_forecast_cloudcover'].to_numpy()
        y = region_df['sky-ambient^2'].to_numpy()        
        
        # initial mask: everyone in
        mask = np.ones_like(y, dtype=bool)
        
        n_sigma   = 2.0     # how many σ out to reject
        max_iters = 5       # maximum number of cycles
        
        for i in range(max_iters):
            # 1) fit to the current inliers
            slope, intercept = np.polyfit(x[mask], y[mask], 1)
        
            # 2) compute residuals of all points to that fit
            resid = y - (slope*x + intercept)
        
            # 3) measure the scatter on the CURRENT inliers
            sigma = np.std(resid[mask])
        
            # 4) build a new mask
            new_mask = np.abs(resid) <= n_sigma * sigma
        
            # 5) if nothing changed, stop early
            if new_mask.sum() == mask.sum():
                break
            mask = new_mask
        
        # prepare your fit‐line for plotting
        x_line = np.linspace(x.min(), x.max(), 200)
        y_line = slope*x_line + intercept
        
        plt.figure(figsize=(6,4))
        plt.scatter(x[mask],    y[mask],    alpha=0.7, label='Inliers')
        plt.scatter(x[~mask],   y[~mask],   color='red', alpha=0.7, label='Outliers')
        plt.plot(x_line, y_line, color='black', linewidth=2, label=f'{n_sigma}σ fit')
        plt.legend()

        # plt.figure(figsize=(6, 4)) 
        # sns.regplot(x='avg_forecast_cloudcover', y='sky-ambient^2', data=region_df)
        plt.xlabel('Average Forecast Cloud Cover (%)')
        plt.ylabel('Sky-Ambient^2 Temperature (°C)')
        plt.title('Sky-Ambient^2 Temperature vs Forecast Cloud Cover')
        
        plt.savefig(directory + '/' + part_of_day + '/skyminusambientsquaredvsclouds_' + str(file_date_string) + '.png', dpi=300, bbox_inches='tight')
    
        
    
        # Now remove ALL these outliers from the actual model fit
        def sigma_clip_mask(x, y, n_sigma=2.0, max_iters=5):
            """
            Iterative σ–clipping mask: returns a boolean array (True=inlier).
            """
            mask = np.ones_like(y, dtype=bool)
            for _ in range(max_iters):
                # fit only to current inliers
                m, b = np.polyfit(x[mask], y[mask], 1)
                resid = y - (m*x + b)
                sigma = np.std(resid[mask])
                new_mask = np.abs(resid) <= n_sigma*sigma
                if new_mask.sum() == mask.sum():
                    break
                mask = new_mask
            return mask
        
        # --- prepare x once ---
        x = region_df['avg_forecast_cloudcover'].to_numpy()
        
        # --- get masks for each y-series ---
        m1 = sigma_clip_mask(x, region_df['sky_temp_C'].to_numpy())
        m2 = sigma_clip_mask(x, region_df['sky-ambient'].to_numpy())
        m3 = sigma_clip_mask(x, region_df['sky-ambient^2'].to_numpy())
        
        # --- combine: only keep rows that are inliers in *all* three ---
        keep = m1 & m2 & m3
        
        # --- filter your original DataFrame ---
        region_df = region_df.loc[keep].copy()           
    
           
        X = region_df[features].copy()
        y = region_df['avg_forecast_cloudcover'].copy()        
    
        try:
    
            ### ✅ First Pass: Fit Model and Remove Outliers
            gb_model = GradientBoostingRegressor(n_estimators=100, learning_rate=0.1, random_state=42)
            gb_model.fit(X, y)
            y_pred = gb_model.predict(X)
        
            # Outlier rejection - First Pass
            residuals = y - y_pred
            mask = np.abs(residuals) <= 30  # Remove large outliers (> 30 units)
            X = X[mask].copy()
            y = y[mask].copy()
        
            plog(f"First pass removed {len(residuals) - len(y)} outliers.")
        
            ### ✅ Second Pass: Refit Model and Remove Outliers Again
            gb_model.fit(X, y)
            y_pred = gb_model.predict(X)
        
            residuals = y - y_pred
            mask = np.abs(residuals) <= 30  # Remove outliers a second time
            X = X[mask].copy()
            y = y[mask].copy()
        
            plog(f"Second pass removed {len(residuals) - len(y)} outliers.")
        
            ### ✅ Final Fit: Fit Model on Cleaned Data
            gb_model.fit(X, y)
            y_pred = gb_model.predict(X)
        
            ### ✅ Plot predicted vs actual values
            plt.figure(figsize=(8, 6))
            plt.scatter(y, y_pred, alpha=0.7, color='black', marker='o')
            plt.plot([y.min(), y.max()], [y.min(), y.max()], '--', color='red')
            plt.xlabel('Actual average weather report clouds')
            plt.ylabel('Predicted average weather report clouds')
            plt.title('Predicted vs Actual Clouds')
        
            plt.savefig(directory + '/' + part_of_day + '/ActualVSPredicted_' + str(file_date_string) + '.png', dpi=300, bbox_inches='tight')
        
            ### ✅ Heatmap of correlation between factors
            plt.figure(figsize=(8, 6))
            sns.heatmap(pd.DataFrame(X).join(pd.Series(y, name='avg_forecast_cloudcover')).corr(), annot=True, cmap='coolwarm', fmt='.2f', linewidths=0.5)
            plt.title('Correlation Heatmap')
            plt.savefig(directory + '/' + part_of_day + '/Correlation_' + str(file_date_string) + '.png', dpi=300, bbox_inches='tight')
        
            ### ✅ Evaluate performance
            mse = mean_squared_error(y, y_pred)
            rmse = np.sqrt(mse)
            r2 = r2_score(y, y_pred)
        
            ### ✅ plog performance metrics
            plog (part_of_day)
            plog(f"Mean Squared Error: {mse:.2f}")
            plog(f"Root Mean Squared Error: {rmse:.2f}")
            plog(f"R² Score: {r2:.2f}")
            
            if part_of_day=='daytime':
                daytime_model=copy.deepcopy(gb_model)
            else:
                nighttime_model=copy.deepcopy(gb_model)
        
            ### ✅ Save updated dataframe with predictions
            region_df.loc[X.index, 'predicted_clouds'] = y_pred
            region_df.to_csv(directory + '/' + part_of_day + '/WeatherData_' + str(file_date_string) + '.csv', index=False)
    
        except:
            plog("failed to do model?")
            
            plog(traceback.format_exc())
            
    
    
    return daytime_model, nighttime_model, number_of_daytime_weather_observations,number_of_nighttime_weather_observations

def correct_dome_azimuth(telescope_az, telescope_alt, side_of_pier, dome_radius, telescope_offset):#, dome_slit_offset=0):
    """
    Corrects the dome azimuth based on telescope pointing and side of the pier.

    Parameters:
        telescope_az (float): Telescope azimuth in degrees (0-360).
        telescope_alt (float): Telescope altitude in degrees (0-90).
        side_of_pier (str): 'E' for East, 'W' for West.
        dome_radius (float): Radius of the dome in meters.
        telescope_offset (float): Lateral offset of the telescope from the dome center in meters.
        dome_slit_offset (float, optional): Empirical offset to keep the telescope centered in the dome slit (default 0).

    Returns:
        float: Corrected dome azimuth in degrees (0-360).
    """

    # Convert to radians for calculations
    #az_rad = np.radians(telescope_az)
    alt_rad = np.radians(telescope_alt)

    # Compute the small offset angle due to the telescope offset inside the dome
    if dome_radius > 0:
        offset_angle = np.degrees(np.arctan2(telescope_offset * np.cos(alt_rad), dome_radius))
    else:
        offset_angle = 0  # Avoid division by zero

    # Adjust azimuth based on the side of the pier
    if side_of_pier.upper() == 'E':
        dome_az = (telescope_az + offset_angle) % 360
    elif side_of_pier.upper() == 'W':
        dome_az = (telescope_az - offset_angle) % 360
    else:
        raise ValueError("side_of_pier must be 'E' or 'W'")

    # # Apply an empirical dome slit offset
    # dome_az = (dome_az + dome_slit_offset) % 360

    return dome_az


# FIXME: This needs attention once we figure out the restart_obs script.
def terminate_restart_observer(site_path, no_restart=False):
    """Terminates obs-platform code if running and restarts obs."""
    if no_restart is False:
        return

    camShelf = shelve.open(site_path + "ptr_night_shelf/" + "pid_obs")
    pid = camShelf["pid_obs"]  # a 9 character string
    camShelf.close()
    try:
        plog("Terminating:  ", pid)
        os.kill(pid, signal.SIGTERM)
    except:
        plog("No observer process was found, starting a new one.")
    # The above routine does not return but does start a process.
    parentPath = Path.cwd()
    os.system("cmd /c " + str(parentPath) + "\restart_obs.bat")

    return


def send_status(obsy, status_type, status_to_send):
    """Sends a status update to AWS."""
    
    uri_status = f"{PTR_STATUS_ROOT}/{obsy}/status/"
    # NB None of the strings can be empty. Otherwise this POST faults.
    payload = {"statusType": str(status_type), "status": status_to_send}
    data = json.dumps(payload)
    
    try:
        response = requests.post(uri_status, data=data, timeout=20, allow_redirects=False, headers=close_headers)
        if response.ok:
            plog(f"~ sent latest {status_type} status")  # clearer success log including the type that was sent
        else:
            plog(f"Failed! Status code: {response.status_code}, Response: {response.text}")
    except Exception as e:
        plog(f"Request exception: {str(e)}")


def fitzgerald_number(humidity, clouds, wind_speed, description, pop):
    """Score how unfit a period is for observing. Lower is better.

    Wayne's scale: 0 is clear, under 100 good, under 600 dodgy, above that not
    worth opening for. Any single disqualifying factor adds 101, so one bad
    ingredient is enough to put a period out of range on its own.

    Pulled out of the hourly loop so the daily forecast is graded on the same
    thresholds rather than a second set that could drift from it.
    """
    score = 0

    if 80 < humidity <= 85:
        score += 4
    elif 85 < humidity <= 90:
        score += 20
    elif 90 < humidity <= 100:
        score += 101

    if 20 < clouds <= 40:
        score += 10
    elif 40 < clouds <= 60:
        score += 40
    elif 60 < clouds <= 80:
        score += 60
    elif 80 < clouds <= 100:
        score += 101

    if 8 < wind_speed <= 12:
        score += 1
    elif 12 < wind_speed <= 15:
        score += 4
    elif 15 < wind_speed <= 20:
        score += 40
    elif 20 < wind_speed:
        score += 101

    if 'rain' in description or 'storm' in description or pop > 0:
        score += 101

    return score


def weather_quality_number(fitz):
    """The Fitzgerald number as the five bands the interface colours by."""
    fitz = float(fitz)
    if fitz < 11:
        return 1
    if fitz < 21:
        return 2
    if fitz < 41:
        return 3
    if fitz < 101:
        return 4
    return 5


def _pct(value, places=1):
    """Format a forecast percentage that may be missing.

    Providers we have no subscription for, or that did not answer, leave their
    value at None. Rounding that raises, which used to abort the whole forecast
    summary, so one missing provider hid every other reading. Missing values
    now read 'n/a' and the rest of the summary still prints.
    """
    if value is None:
        return "n/a"
    try:
        return str(round(value, places)) + "%"
    except TypeError:
        return str(value)


class WxEncAgent:
    """A class for weather enclosure functionality."""
    
    """
    Re-working ARO Weather 20231226 WER.  Currently the Wema-attached external 
n    SkyAlert is failing so we are picking up Weather from the ARO-0m30 Skyalert 
    provided by a reflection from AWS -- and we have an inside skyalert which
    measures the underside roof temp during the day!  Unfortunately the AWS
    style reflection gets stale so I am putting in a redis based way to pass
    the ARO-0m30 weather information over to the Wema.  No Weather decisions
    are made at ARO-0m30 except to convert to metric and compute the 15 minute 
    wind-gust value.
    
    In the event the redis data is stale -- we may use the AWS supplied data if
    we can figure out how to verify it is not stale.
    
    NOTE  ARO-0m30 passes its weather line through skyalert\weatherdata_nw.txt
    
    Status as sent to GUI does go through AWS however.
    
    The whole Weather Hold system has been bypassed and semi-replaced with the OWM
    rework.  I plan to revisit this once I am satsified it serves a useful purpose.
    for ARO late afternoon winds are common but they tend to abate.  Some wind-
    shake during eve skyflats causes no harm so we can be more tolerant.
    """

    def __init__(self, name, config):

        self.name=name        

        self.api = API_calls()
        self.command_interval = 30
        self.status_interval = 30
        self.config = config
        g_dev["wema"] = self

        # Initialise location
        self.latitude=self.config["latitude"]
        self.longitude=self.config["longitude"]
        self.height=0        
        self.observer_location = EarthLocation(lat=self.latitude*u.deg, lon=self.longitude*u.deg, height=self.height*u.m)


        self.opens_during_nighttime=self.config['opens_during_nighttime']
        self.opens_during_daytime=self.config['opens_during_daytime']

        # Load up the secrets and passwords
        with open('secrets.txt', "r") as file:
            secrets=json.load(file)


        self.number_of_nighttime_weather_observations = 0 # Just initialising
        
        self.smtp_server=secrets["smtp_server"]
        self.smtp_port=secrets["smtp_port"]
        self.sender_email=secrets["sender_email"]
        self.email_password=secrets["email_password"]
        
        self.owm_api_key=secrets["OWM_Key"]
        self.tomorrowio_APIkey=secrets['tomorrowio_Key']
        self.weather_to_emails=secrets["weather_to_emails"]
        self.pirateapi_key=secrets["pirateapi_Key"]
        self.metocean_apikey=secrets["metocean_key"]
        self.worldweather_key=secrets["worldweather_key"]
        
        self.daytime_cloud_model=None
        self.nighttime_cloud_model=None
        self.ocn_status=None
        self.enc_status=None

        self.current_owm_humidity=-1
        self.current_owm_ambient_temperature=0
        self.current_owm_dewpoint=0

        self.cloud_tracker=[]
        self.median_cloud_estimate=0

        # Initialise this variable
        self.open_and_enabled_to_observe=False

        self.debug_flag = self.config['debug_mode']
        self.admin_only_flag = self.config['admin_owner_commands_only']
        if self.debug_flag:
            self.debug_lapse_time = time.time() + self.config['debug_duration_sec']
            g_dev['debug'] = True
        else:
            self.debug_lapse_time = 0.0
            g_dev['debug'] = False

        self.hostname = socket.gethostname()
        if self.hostname in self.config["wema_hostname"]:
            self.is_wema = True
        else:
            # This host is a client.   What does this mean??  This IS wema code.
            self.is_wema = False  # This is a client.
        self.wema_path = config["wema_path"]
        g_dev["wema_write_share_path"] = self.wema_path
        #self.site_path = self.wema_path  #  No longer used


        # THIS IS JUST THE FIRST OF SOME DOMES
        # NEED TO MAKE THIS A CONFIG ITEM
        try:
            self.dome_offset = self.config['enclosure']['enclosure1']['dome_offset_in_degrees'] ### THIS IS PURELY FOR LCS
        except:
            plog ("Couldn't load dome offset. mayhaps not a dome")


        self.last_request = None
        self.stopped = False
        self.site_message = "-"
        #self.site_mode = config['site_enclosures_default_mode']
        self.device_types = config["wema_types"]
        self.astro_events = wema_events.Events(self.config)
        self.astro_events.compute_day_directory()
        self.astro_events.calculate_events()
        self.astro_events.display_events()

        self.dome_check_timer=time.time()
        self.dome_check_timer_period=5

        self.wema_pid = os.getpid()
        plog("Fresh WEMA_PID:  ", self.wema_pid)
        
        self.update_config()
        self.create_devices(config)
        self.time_last_status = time.time() - 60  #forces early status on startup.
        self.loud_status = False
        self.blocks = None
        self.projects = None
        self.events_new = None
        immed_time = time.time()
        self.obs_time = immed_time
        self.wema_start_time = immed_time
        self.cool_down_latch = False

        obs_win_begin, sunZ88Op, sunZ88Cl, ephem_now = self.astro_events.getSunEvents()
        self.nightly_weather_report_complete = False
        self.weather_report_run_timer=time.time()-3600
        self.local_pytz_timezone=pytz.timezone(self.config['TZ_database_name'])
        

        self.owm_active=config['OWM_active']
        self.local_weather_active=config['local_weather_active']
        
        self.enclosure_status_check_period=config['enclosure_status_check_period']
        self.weather_status_check_period = config['weather_status_check_period']
        self.safety_status_check_period = config['safety_status_check_period']
        self.scan_requests_check_period = 4
        self.wema_settings_upload_period = 10
        self.error_fault_clear_timer=time.time()

        # Timers rather than time.sleeps
        self.enclosure_status_check_timer=time.time() - 2*self.enclosure_status_check_period
        self.weather_status_check_timer = time.time() - 2*self.weather_status_check_period
        self.safety_check_timer=time.time() - 2*self.safety_status_check_period
        self.scan_requests_timer=time.time() -2 * self.scan_requests_check_period
        self.wema_settings_upload_timer=time.time() -2 * self.wema_settings_upload_period

        # This is a flag that enables or disables observing for all OBS in the WEMA.
        self.observing_mode = 'active'
        self.rain_limit_quiet=False
        self.local_cloud_limit_quiet=False
        self.forecast_cloud_limit_quiet=False
        self.humidity_limit_quiet=False
        self.windspeed_limit_quiet=False
        self.lightning_limit_quiet=False
        self.temp_minus_dew_quiet=False
        self.sky_minus_ambient_limit_quiet=False
        self.sky_temperature_limit_quiet=False
        self.hightemp_limit_quiet=False
        self.lowtemp_limit_quiet=False

        if self.config['observing_conditions']['observing_conditions1']['driver'] == None:
            self.ocn_exists=False
        else:
            self.ocn_exists=True

        # This variable prevents the roof being called to open every loop...        
        self.enclosure_next_open_time = time.time()
        # This keeps a track of how many times the roof has been open this evening
        # Which is really a measure of how many times the enclosure has
        # attempted to observe but been shut on....
        # If it is too many, then it shuts down for the whole evening. 
        self.opens_this_evening = 0
        self.local_weather_ok = None
        # The structured report published on the owm_report lane.
        self.owm_report_payload = {}
        self.hourly_report_rows = []
        self.times_to_open = []
        self.times_to_close = []
        self.weather_report_open_at_start = False
        self.nightly_reset_complete = False  
        self.keep_open_all_night = False
        self.keep_closed_all_night   = False          
        self.open_at_specific_utc = False
        self.specific_utc_when_to_open = -1.0  
        self.manual_weather_hold_set = False
        self.manual_weather_hold_duration = -1.0    
        self.wema_has_roof_control=config['wema_has_control_of_roof']
        
        # Obs under WEMA guidance
        self.obs_ids=self.config['obsp_ids']
        self.morning_flats_finished=False


        self.owm_cloud_cover=None
        self.open_meteo_cloud_cover=None
        self.open_meteo_cloud_cover_next_hour=None
        self.medianforecast_current_cloud_cover=None
        self.tomorrowio_cloud_now=None
        self.tomorrowio_cloud_inanhour=None

        # This prevents commands from previous nights/runs suddenly running
        # when wema.py is booted (has happened a bit!)
        url_job = f"{PTR_JOBS_ROOT}/getnewjobs"
        body = {"site": self.config['wema_name']}
        
        try:

            requests.request("POST", url_job, data=json.dumps(body), timeout=30, allow_redirects=False, headers=close_headers, stream=False).json()
        except:
            plog ("Connection glitch in getnewjobs")
            plog(traceback.format_exc())
            

        
        if not os.path.exists(self.wema_path):
            os.makedirs(self.wema_path)
        if not os.path.exists(self.wema_path + "ptr_night_shelf"):
            os.makedirs(self.wema_path + "ptr_night_shelf")
        
        self.wema_settings_shelf_filename = self.wema_path + "ptr_night_shelf/" + str(self.config['wema_name'])+"_wema_stored_settings"
    
        #######################
        # THIS AREA JUST GETS DELETED ONCE WE HAVE AN ONLINE ADJUSTABLE WEMA SETTINGS
        # UNTIL THEN IT WILL LOAD THE VALUES FROM THE CONFIG
        #######################
        
        plog ("Loading limits from config: TO BE DEPRECATED ONCE WE HAVE AN ONLINE LIMIT SYSTEM")
        try:
            wema_settings_shelf = shelve.open(self.wema_settings_shelf_filename)
            
            self.rain_limit_setting = self.config['rain_limit']
            self.humidity_limit_setting = self.config['humidity_limit']
            self.windspeed_limit_setting = self.config['windspeed_limit']
            self.lightning_limit_setting = self.config['lightning_limit']
            self.temp_minus_dew_setting = self.config['temperature_minus_dewpoint_limit']
            self.sky_minus_ambient_limit_setting = self.config['sky_minus_ambient_limit']
            
            self.sky_temperature_limit_setting = self.config['sky_temperature_limit']
            self.local_cloud_cover_limit_setting = self.config['local_cloud_cover_limit']
            self.forecast_cloud_cover_limit_setting = self.config['forecast_cloud_cover_limit']
            self.lowest_temperature_setting = self.config['lowest_ambient_temperature']
            self.highest_temperature_setting = self.config['highest_ambient_temperature']

            self.warning_rain_limit_setting = self.config['warning_rain_limit']
            self.warning_humidity_limit_setting = self.config['warning_humidity_limit']
            self.warning_windspeed_limit_setting = self.config['warning_windspeed_limit']
            self.warning_lightning_limit_setting = self.config['warning_lightning_limit']
            self.warning_temp_minus_dew_setting = self.config['warning_temperature_minus_dewpoint_limit']
            self.warning_sky_minus_ambient_limit_setting = self.config['warning_sky_minus_ambient_limit']
            self.warning_sky_temperature_limit_setting = self.config['warning_sky_temperature_limit']
            self.warning_local_cloud_cover_limit_setting = self.config['warning_local_cloud_cover_limit']
            self.warning_forecast_cloud_cover_limit_setting = self.config['warning_forecast_cloud_cover_limit']
            self.warning_lowest_temperature_setting = self.config['warning_lowest_ambient_temperature']
            self.warning_highest_temperature_setting = self.config['warning_highest_ambient_temperature']

            self.rain_limit_on = self.config['rain_limit_on']
            self.humidity_limit_on = self.config['humidity_limit_on']
            self.windspeed_limit_on = self.config['windspeed_limit_on']
            self.lightning_limit_on = self.config['lightning_limit_on']
            self.temp_minus_dew_on = self.config['temperature_minus_dewpoint_limit_on']
            self.sky_minus_ambient_limit_on = self.config['sky_minus_ambient_limit_on']
            
            self.sky_temperature_limit_on = self.config['sky_temperature_limit_on']
            self.local_cloud_cover_limit_on = self.config['local_cloud_cover_limit_on']
            self.forecast_cloud_cover_limit_on = self.config['forecast_cloud_cover_limit_on']
            self.lowest_temperature_on = self.config['lowest_ambient_temperature_on']
            self.highest_temperature_on = self.config['highest_ambient_temperature_on']
                    
            wema_settings_shelf['rain_limit_on'] = self.rain_limit_on
            wema_settings_shelf['warning_rain_limit_setting'] = self.warning_rain_limit_setting
            wema_settings_shelf['rain_limit_setting'] = self.rain_limit_setting
            
            wema_settings_shelf['local_cloud_cover_limit_on'] = self.local_cloud_cover_limit_on
            wema_settings_shelf['forecast_cloud_cover_limit_on'] = self.forecast_cloud_cover_limit_on
            wema_settings_shelf['warning_local_cloud_cover_limit_setting'] = self.warning_local_cloud_cover_limit_setting
            wema_settings_shelf['warning_forecast_cloud_cover_limit_setting'] = self.warning_forecast_cloud_cover_limit_setting
            wema_settings_shelf['local_cloud_cover_limit_setting'] = self.local_cloud_cover_limit_setting
            wema_settings_shelf['forecast_cloud_cover_limit_setting'] = self.forecast_cloud_cover_limit_setting
            
            
            wema_settings_shelf['humidity_limit_on'] = self.humidity_limit_on
            wema_settings_shelf['warning_humidity_limit_setting'] = self.warning_humidity_limit_setting
            wema_settings_shelf['humidity_limit_setting'] = self.humidity_limit_setting
            
            wema_settings_shelf['windspeed_limit_on'] = self.windspeed_limit_on
            wema_settings_shelf['warning_windspeed_limit_setting'] = self.warning_windspeed_limit_setting
            wema_settings_shelf['windspeed_limit_setting'] = self.windspeed_limit_setting
            
            wema_settings_shelf['lightning_limit_on'] = self.lightning_limit_on
            wema_settings_shelf['warning_lightning_limit_setting'] = self.warning_lightning_limit_setting
            wema_settings_shelf['lightning_limit_setting'] = self.lightning_limit_setting
            
            wema_settings_shelf['temp_minus_dew_on'] = self.temp_minus_dew_on
            wema_settings_shelf['warning_temp_minus_dew_setting'] = self.warning_temp_minus_dew_setting
            wema_settings_shelf['temp_minus_dew_setting'] = self.temp_minus_dew_setting
            
            wema_settings_shelf['sky_minus_ambient_limit_on'] = self.sky_minus_ambient_limit_on
            wema_settings_shelf['warning_sky_minus_ambient_limit_setting'] = self.warning_sky_minus_ambient_limit_setting
            wema_settings_shelf['sky_minus_ambient_limit_setting'] = self.sky_minus_ambient_limit_setting
            
            wema_settings_shelf['sky_temperature_limit_on'] = self.sky_temperature_limit_on
            wema_settings_shelf['warning_sky_temperature_limit_setting'] = self.warning_sky_temperature_limit_setting
            wema_settings_shelf['sky_temperature_limit_setting'] = self.sky_temperature_limit_setting
            
            wema_settings_shelf['lowest_ambient_temperature'] = self.lowest_temperature_setting
            wema_settings_shelf['highest_ambient_temperature'] = self.highest_temperature_setting

            wema_settings_shelf['lowest_ambient_temperature_on'] = self.lowest_temperature_on
            wema_settings_shelf['highest_ambient_temperature_on']= self.highest_temperature_on
            
            wema_settings_shelf['hightemperature_limit_warning_level'] = self.warning_highest_temperature_setting
            #status['wema_settings']['hightemperature_limit_danger_level'] = self.highest_temperature_setting
            
            # status['wema_settings']['lowtemperature_limit_on']  = self.lowest_temperature_on
            # status['wema_settings']['lowtemperature_limit_quiet'] = self.lowtemp_limit_quiet
            wema_settings_shelf['lowtemperature_limit_warning_level'] = self.warning_lowest_temperature_setting
            
            #pid = camShelf["pid_obs"]  # a 9 character string
            wema_settings_shelf.close()
        except:
            plog ("Startup shelf load failed.")
            plog(traceback.format_exc())
        
        plog ("passed startup shelf load")
        #######################
        # ^^^^^^^^^^^^^^ THIS AREA JUST GETS DELETED ONCE WE HAVE AN ONLINE ADJUSTABLE WEMA SETTINGS
        # UNTIL THEN IT WILL LOAD THE VALUES FROM THE CONFIG
        #######################
    
    
    
    
        
        if os.path.exists(self.wema_settings_shelf_filename + '.dat'):       
        
            wema_settings_shelf = shelve.open(self.wema_settings_shelf_filename)
            
            #plog ("woo")
            
            #plog (wema_settings_shelf['local_weather_active'])
            
            g_dev['enc'].mode =wema_settings_shelf['mode']
            self.observing_mode=wema_settings_shelf['observing_mode']
            self.local_weather_active=wema_settings_shelf['local_weather_active']
            self.owm_active=wema_settings_shelf['owm_active']
            self.keep_open_all_night=wema_settings_shelf['keep_open_all_night']
            self.keep_closed_all_night=wema_settings_shelf['keep_closed_all_night']
            if self.ocn_exists:
                try:
                    self.rain_limit_on=wema_settings_shelf['rain_limit_on']
                    self.warning_rain_limit_setting=wema_settings_shelf['warning_rain_limit_setting']
                    self.rain_limit_setting=wema_settings_shelf['rain_limit_setting']
                    
                    self.local_cloud_cover_limit_on=wema_settings_shelf['local_cloud_cover_limit_on']
                    self.forecast_cloud_cover_limit_on=wema_settings_shelf['forecast_cloud_cover_limit_on']
                    self.warning_cloud_cover_limit_setting=wema_settings_shelf['warning_cloud_cover_limit_setting']
                    self.local_cloud_cover_limit_setting=wema_settings_shelf['local_cloud_cover_limit_setting']
                    self.forecast_cloud_cover_limit_setting=wema_settings_shelf['forecast_cloud_cover_limit_setting']
                    
                    self.humidity_limit_on=wema_settings_shelf['humidity_limit_on']
                    self.warning_humidity_limit_setting=wema_settings_shelf['warning_humidity_limit_setting']
                    self.humidity_limit_setting=wema_settings_shelf['humidity_limit_setting']
                    
                    self.windspeed_limit_on=wema_settings_shelf['windspeed_limit_on']
                    self.warning_windspeed_limit_setting=wema_settings_shelf['warning_windspeed_limit_setting']
                    self.windspeed_limit_setting=wema_settings_shelf['windspeed_limit_setting']
                    
                    self.lightning_limit_on=wema_settings_shelf['lightning_limit_on']
                    self.warning_lightning_limit_setting=wema_settings_shelf['warning_lightning_limit_setting']
                    self.lightning_limit_setting=wema_settings_shelf['lightning_limit_setting']
                    
                    self.temp_minus_dew_on=wema_settings_shelf['temp_minus_dew_on']
                    self.warning_temp_minus_dew_setting=wema_settings_shelf['warning_temp_minus_dew_setting']
                    self.temp_minus_dew_setting=wema_settings_shelf['temp_minus_dew_setting']
                    
                    self.sky_minus_ambient_limit_on=wema_settings_shelf['sky_minus_ambient_limit_on']
                    self.warning_sky_minus_ambient_limit_setting=wema_settings_shelf['warning_sky_minus_ambient_limit_setting']
                    self.sky_minus_ambient_limit_setting=wema_settings_shelf['sky_minus_ambient_limit_setting']
                    
                    self.sky_temperature_limit_on=wema_settings_shelf['sky_temperature_limit_on']
                    self.warning_sky_temperature_limit_setting=wema_settings_shelf['warning_sky_temperature_limit_setting']
                    self.sky_temperature_limit_setting=wema_settings_shelf['sky_temperature_limit_setting']
                    
                    self.lowest_temperature_setting =  wema_settings_shelf['lowest_ambient_temperature']
                    self.highest_temperature_setting =  wema_settings_shelf['highest_ambient_temperature']
                    self.lowest_temperature_on =  wema_settings_shelf['lowest_ambient_temperature_on']
                    self.highest_temperature_on =  wema_settings_shelf['highest_ambient_temperature_on']
                    
                    self.warning_highest_temperature_setting=wema_settings_shelf['highest_ambient_temperature_on']
                    #status['wema_settings']['hightemperature_limit_danger_level'] = self.highest_temperature_setting
                    
                    # status['wema_settings']['lowtemperature_limit_on']  = self.lowest_temperature_on
                    # status['wema_settings']['lowtemperature_limit_quiet'] = self.lowtemp_limit_quiet
                    self.warning_lowest_temperature_setting=wema_settings_shelf['lowest_ambient_temperature_on']
                    
                    
                    
                except:
                    plog ("Probably has not formed a shelf yet, forming a shelf from the config.")
                    plog(traceback.format_exc())
                    
                    
                    
                    self.rain_limit_setting = self.config['rain_limit']
                    self.humidity_limit_setting = self.config['humidity_limit']
                    self.windspeed_limit_setting = self.config['windspeed_limit']
                    self.lightning_limit_setting = self.config['lightning_limit']
                    self.temp_minus_dew_setting = self.config['temperature_minus_dewpoint_limit']
                    self.sky_minus_ambient_limit_setting = self.config['sky_minus_ambient_limit']
                    
                    self.sky_temperature_limit_setting = self.config['sky_temperature_limit']
                    self.local_cloud_cover_limit_setting = self.config['local_cloud_cover_limit']                    
                    self.forecast_cloud_cover_limit_setting = self.config['forecast_cloud_cover_limit']
                    self.lowest_temperature_setting = self.config['lowest_ambient_temperature']
                    self.highest_temperature_setting = self.config['highest_ambient_temperature']

                    self.warning_rain_limit_setting = self.config['warning_rain_limit']
                    self.warning_humidity_limit_setting = self.config['warning_humidity_limit']
                    self.warning_windspeed_limit_setting = self.config['warning_windspeed_limit']
                    self.warning_lightning_limit_setting = self.config['warning_lightning_limit']
                    self.warning_temp_minus_dew_setting = self.config['warning_temperature_minus_dewpoint_limit']
                    self.warning_sky_minus_ambient_limit_setting = self.config['warning_sky_minus_ambient_limit']
                    
                    self.warning_sky_temperature_limit_setting = self.config['warning_sky_temperature_limit']
                    self.warning_local_cloud_cover_limit_setting = self.config['warning_local_cloud_cover_limit']
                    self.warning_forecast_cloud_cover_limit_setting = self.config['warning_forecast_cloud_cover_limit']
                    
                    self.warning_lowest_temperature_setting = self.config['warning_lowest_ambient_temperature']
                    self.warning_highest_temperature_setting = self.config['warning_highest_ambient_temperature']

                    self.rain_limit_on = self.config['rain_limit_on']
                    self.humidity_limit_on = self.config['humidity_limit_on']
                    self.windspeed_limit_on = self.config['windspeed_limit_on']
                    self.lightning_limit_on = self.config['lightning_limit_on']
                    self.temp_minus_dew_on = self.config['temperature_minus_dewpoint_limit_on']
                    self.sky_minus_ambient_limit_on = self.config['sky_minus_ambient_limit_on']
                    
                    self.sky_temperature_limit_on = self.config['sky_temperature_limit_on']
                    self.local_cloud_cover_limit_on = self.config['local_cloud_cover_limit_on']
                    self.forecast_cloud_cover_limit_on = self.config['forecast_cloud_cover_limit_on']
                    self.lowest_temperature_on = self.config['lowest_ambient_temperature_on']
                    self.highest_temperature_on = self.config['highest_ambient_temperature_on']
                                        
                    wema_settings_shelf['rain_limit_on'] = self.rain_limit_on
                    wema_settings_shelf['warning_rain_limit_setting'] = self.warning_rain_limit_setting
                    wema_settings_shelf['rain_limit_setting'] = self.rain_limit_setting
                    
                    wema_settings_shelf['local_cloud_cover_limit_on'] = self.local_cloud_cover_limit_on
                    wema_settings_shelf['forecast_cloud_cover_limit_on'] = self.forecast_cloud_cover_limit_on
                    wema_settings_shelf['warning_local_cloud_cover_limit_setting'] = self.warning_local_cloud_cover_limit_setting
                    wema_settings_shelf['warning_forecast_cloud_cover_limit_setting'] = self.warning_forecast_cloud_cover_limit_setting
                    wema_settings_shelf['local_cloud_cover_limit_setting'] = self.local_cloud_cover_limit_setting
                    wema_settings_shelf['forecast_cloud_cover_limit_setting'] = self.forecast_cloud_cover_limit_setting
                    
                    
                    wema_settings_shelf['humidity_limit_on'] = self.humidity_limit_on
                    wema_settings_shelf['warning_humidity_limit_setting'] = self.warning_humidity_limit_setting
                    wema_settings_shelf['humidity_limit_setting'] = self.humidity_limit_setting
                    
                    wema_settings_shelf['windspeed_limit_on'] = self.windspeed_limit_on
                    wema_settings_shelf['warning_windspeed_limit_setting'] = self.warning_windspeed_limit_setting
                    wema_settings_shelf['windspeed_limit_setting'] = self.windspeed_limit_setting
                    
                    wema_settings_shelf['lightning_limit_on'] = self.lightning_limit_on
                    wema_settings_shelf['warning_lightning_limit_setting'] = self.warning_lightning_limit_setting
                    wema_settings_shelf['lightning_limit_setting'] = self.lightning_limit_setting
                    
                    wema_settings_shelf['temp_minus_dew_on'] = self.temp_minus_dew_on
                    wema_settings_shelf['warning_temp_minus_dew_setting'] = self.warning_temp_minus_dew_setting
                    wema_settings_shelf['temp_minus_dew_setting'] = self.temp_minus_dew_setting
                    
                    wema_settings_shelf['sky_minus_ambient_limit_on'] = self.sky_minus_ambient_limit_on
                    wema_settings_shelf['warning_sky_minus_ambient_limit_setting'] = self.warning_sky_minus_ambient_limit_setting
                    wema_settings_shelf['sky_minus_ambient_limit_setting'] = self.sky_minus_ambient_limit_setting
                    
                    wema_settings_shelf['sky_temperature_limit_on'] = self.sky_temperature_limit_on
                    wema_settings_shelf['warning_sky_temperature_limit_setting'] = self.warning_sky_temperature_limit_setting
                    wema_settings_shelf['sky_temperature_limit_setting'] = self.sky_temperature_limit_setting
                    
                    wema_settings_shelf['lowest_ambient_temperature'] = self.lowest_temperature_setting
                    wema_settings_shelf['highest_ambient_temperature'] = self.highest_temperature_setting

                    wema_settings_shelf['lowest_ambient_temperature_on'] = self.lowest_temperature_on
                    wema_settings_shelf['highest_ambient_temperature_on']= self.highest_temperature_on
                    
                    wema_settings_shelf['hightemperature_limit_warning_level'] = self.warning_highest_temperature_setting
                    #status['wema_settings']['hightemperature_limit_danger_level'] = self.highest_temperature_setting
                    
                    # status['wema_settings']['lowtemperature_limit_on']  = self.lowest_temperature_on
                    # status['wema_settings']['lowtemperature_limit_quiet'] = self.lowtemp_limit_quiet
                    wema_settings_shelf['lowtemperature_limit_warning_level'] = self.warning_lowest_temperature_setting
                    
            #pid = camShelf["pid_obs"]  # a 9 character string
            wema_settings_shelf.close()
            
            self.update_status()
        
        plog ("booted up and got status from ocn device")

        # The LCS dome loses it's position if the wema code gets restarted.
        # If the WEMA code is restarted while the shutter is open, it needs to rehome
        # to figure out where it is. 
        
        
        
        if 'MaxDome' in g_dev['enc'].config['enclosure']['enclosure1']['driver']:
            home_on_boot=True
            
            enc_status=g_dev['enc'].get_status()
            
            if enc_status is not None:
                if enc_status['shutter_status'] in ['Open', 'Sim Open']:
                    if home_on_boot:
                        try:
                            g_dev['enc'].enclosure.FindHome()
                            enc_status = g_dev['enc'].get_status()
                            self.send_enclosure_status(enc_status, [])
                            
                            home_wait_timeout=time.time()
                            while not g_dev['enc'].enclosure.AtHome  and (time.time()-home_wait_timeout < 300):
                                plog ("Waiting for Home")
                                time.sleep(5)
                                
                            g_dev['enc'].enclosure.SyncToAzimuth(self.config['enclosure']['enclosure1']['dome_home_azimuth']) # If shutter home at 194, then park at 100.
                            
                            enc_status = g_dev['enc'].get_status()
                            self.send_enclosure_status(enc_status, [])
                            
                            plog ("Successfully found Home. Ready to observe")
                        except:
                            plog(traceback.format_exc())
                            plog ("DOME COMMAND GLITCHED OUT.")
                        
        
            
        
        



    def create_devices(self, config: dict):
        self.all_devices = {}
        for (
            dev_type
        ) in self.device_types:  # This has been set up for wema to be ocn and enc.
            self.all_devices[dev_type] = {}
            devices_of_type = config.get(dev_type, {})
            device_names = devices_of_type.keys()
            if dev_type == "camera":
                pass
            for name in device_names:
                driver = devices_of_type[name]["driver"]
 
                if dev_type == "observing_conditions" and not self.config['observing_conditions']['observing_conditions1']['ocn_is_custom']:

                    device = ObservingConditions(
                        driver, name, self.config, self.astro_events
                    )
                    self.ocn_status_custom=False
                elif dev_type == "observing_conditions" and self.config['observing_conditions']['observing_conditions1']['ocn_is_custom']:
                    
                    device=None
                    self.ocn_status_custom=True
                    
                
                
                elif dev_type == "enclosure" and not self.config['enclosure']['enclosure1']['encl_is_custom']:
                    device = Enclosure(driver, name, self.config, self.astro_events)
                    self.enc_status_custom=False
                elif dev_type == "enclosure" and self.config['enclosure']['enclosure1']['encl_is_custom']:
                    
                    device=None
                    self.enc_status_custom=True
                   
                else:
                    plog(f"Unknown device: {name}")
                self.all_devices[dev_type][name] = device
        plog("Finished creating devices.")

    def update_config(self):
        """Sends the config to AWS."""

        uri = f"{self.config['wema_name']}/config/"
        self.config["events"] = g_dev["events"]
        response = self.api.authenticated_request("PUT", uri, self.config)
        if response:
            plog("\n\nConfig uploaded successfully.")
            
    def get_sun_and_moon_info(self):
        # Get current time
        obstime = Time.now()            
        # Define the AltAz frame
        altaz_frame = AltAz(obstime=obstime, location=self.observer_location)            
        # Get the Sun's position
        sun = get_body("sun", obstime)    #get_sun(obstime)  Will be depricated          
        # Transform to AltAz
        sun_altaz = sun.transform_to(altaz_frame)            
        # Get the altitude
        sun_altitude = sun_altaz.alt
        sun_azimuth = sun_altaz.az
        plog(f"Current Sun altitude: {sun_altitude:.2f}")           

        #moon = get_moon(obstime, location=self.observer_location)  Deprication warning
        moon = get_body('moon',obstime, location=self.observer_location )

        moon_altaz = moon.transform_to(altaz_frame)
        moon_altitude = moon_altaz.alt       
        # altitude = moon_altaz.alt
        
        # Skip if below horizon
        if moon_altitude < 0 * u.deg:
            plog("Moon is below the horizon — no flux on ground.")
            moon_illumination=0
            flux_ground=0
        else:
            # Illumination estimate (simplified using elongation)
            sun = get_body('sun', obstime)
            elongation = sun.separation(moon)
            moon_illumination = (1 + np.cos(elongation)) / 2
            
            # Apparent magnitude scaling (very approximate)
            full_moon_mag = -12.74
            moon_mag = full_moon_mag + 2.5 * np.log10(1 / moon_illumination)
            
            # Flux above atmosphere (visible range)
            F0 = 3.6e-8  # W/m² for mag 0
            F_top = F0 * 10**(-0.4 * moon_mag)
            
            # Air mass approximation
            zenith_angle = 90 * u.deg - moon_altitude
            airmass = 1 / np.cos(zenith_angle.to(u.rad))
            
            # Atmospheric extinction (assuming extinction coefficient k ~ 0.2 mag/airmass)
            k = 0.2  # typical in visual band
            transmission = 10**(-0.4 * k * airmass)
            
            # Flux on ground
            flux_ground = F_top * transmission * np.sin(moon_altitude.to(u.rad))
        
        plog(f"Moon altitude: {moon_altitude:.2f}")
        plog(f"Moon illumination: {moon_illumination:.2%}")
        plog(f"Approx. moon flux on ground: {flux_ground:.2e} W/m²")
        
        return sun_altitude, moon_altitude, moon_illumination, flux_ground, sun_azimuth
     
 

    def scan_requests(self):
        """
        
        This can pick up owner/admin Shutdown and Automatic request but it 
        would need to be a custom api endpoint.
        
        Not too many useful commands: Shutdown, Automatic, Immediate close,
        BadWxSimulate event (ie a 15 min shutdown)

        For a wema this can be used to capture commands to the wema once the
        AWS side knows how to redirect from any mount/telescope to the common
        Wema.
        This should be changed to look into the site command queue to pick up
        any commands directed at the Wx station, or if the agent is going to
        always exist lets develop a seperate command queue for it.
        
        NB NB NB should this be on some sort of timeout so that if AWS
        connection goes away the code can deal with that case?
        """


        url_job = f"{PTR_JOBS_ROOT}/getnewjobs"
        body = {"site": self.config['wema_name']}
        cmd = {}
        # Get a list of new jobs to complete (this request
        # marks the commands as "RECEIVED")
        #plog ("scanning requests")
        try:
            unread_commands = requests.request(
                "POST", url_job, data=json.dumps(body), timeout=20, allow_redirects=False, headers=close_headers, stream=False
            ).json()
        except:
            plog(traceback.format_exc())
            plog("problem gathering scan requests. Likely just a connection glitch.")
            unread_commands = []
        # Make sure the list is sorted in the order the jobs were issued
        # Note: the ulid for a job is a unique lexicographically-sortable id.
        if len(unread_commands) > 0:
            try:
                unread_commands.sort(key=lambda x: x["timestamp_ms"])
                # Process each job one at a time
                for cmd in unread_commands:
                    if 'action' in cmd:
                        plog(cmd)
                        if cmd['action']=='open':
                            plog ("open enclosure command received")
                 
                            self.open_enclosure({}, {})     #WER added missing dicts 10142023 WER

                            self.enclosure_status_check_timer=time.time() - 2*self.enclosure_status_check_period
                            self.update_status()
                            
                        if cmd['action']=='close':
                            plog ("command enclosure command received")
                           
                            self.park_enclosure_and_close()
                            self.enclosure_status_check_timer=time.time() - 2*self.enclosure_status_check_period
                            self.update_status()
                        
                        
                        if cmd['action']=='simulate_weather_hold':
                            plog("simulate weather hold button doesn't do anything yet")
                        
                        if cmd['action']=='open_no_earlier_than_owm_plan':
                            plog("open no earlier than owm button doesn't do anything yet")
                        
                        # Change in Enclosure mode
                        if cmd['action']=='set_enclosure_mode':
                            plog ("set enclosure mode command received")
                            g_dev['enc'].mode = cmd['required_params']['enclosure_mode']
                            self.enclosure_status_check_timer =time.time() - 2* self.enclosure_status_check_period
                            self.update_status()
                            
                        
                        if cmd['action']=='set_observing_mode':
                            plog ("set observing mode command received")
                            self.observing_mode=cmd['required_params']['observing_mode']
                            self.enclosure_status_check_timer =time.time() - 2* self.enclosure_status_check_period
                            self.update_status()
                            
                        if cmd['action']=='configure_active_weather_report':
                            plog ("configure weather settings command received")
                            if cmd['required_params']["weather_type"] == 'local':
                                if cmd['required_params']["weather_type_value"] == 'on':
                                    self.local_weather_active=True
                                if cmd['required_params']["weather_type_value"] == 'off':
                                    self.local_weather_active=False
                             
                            if cmd['required_params']["weather_type"] == 'owm':
                                if cmd['required_params']["weather_type_value"] == 'on':
                                    self.owm_active=True
                                if cmd['required_params']["weather_type_value"] == 'off':
                                    self.owm_active=False
                            
                            self.wema_settings_upload_timer=time.time() -2 * self.wema_settings_upload_period
                            self.update_status()
                            
                            
                        if cmd['action']=='force_roof_state':
                            if cmd['required_params']["force_roof_state"] == 'open':
                                plog ("keep roof open all night command received")
                                self.keep_open_all_night = True
                                self.keep_closed_all_night = False
                            
                            if cmd['required_params']["force_roof_state"] == 'closed':
                                
                                plog ("keep roof closed all night command received")
                                self.keep_closed_all_night= True
                                self.keep_open_all_night = False
                            
                            if cmd['required_params']["force_roof_state"] == 'auto':
                                
                                plog ("Remove roof force command received")
                                self.keep_closed_all_night= False
                                self.keep_open_all_night = False
                            
                            self.wema_settings_upload_timer=time.time() -2 * self.wema_settings_upload_period
                            self.update_status()
                            
                        if cmd['action']=='set_weather_values': 
                            tempval=cmd['required_params']['weather_values']
                            
                            self.rain_limit_on='on' in tempval['rain']['status']
                            self.warning_rain_limit_setting=tempval['rain']['warning_level']
                            self.rain_limit_setting=tempval['rain']['danger_level']
                            
                            self.local_cloud_cover_limit_on='on' in tempval['local_clouds']['status']
                            self.warning_local_cloud_cover_limit_setting=tempval['local_clouds']['warning_level']
                            self.local_cloud_cover_limit_setting=tempval['local_clouds']['danger_level']
                            
                            self.forecast_cloud_cover_limit_on='on' in tempval['forecast_clouds']['status']
                            self.warning_forecast_cloud_cover_limit_setting=tempval['forecast_clouds']['warning_level']
                            self.forecast_cloud_cover_limit_setting=tempval['forecast_clouds']['danger_level']
                            
                            self.humidity_limit_on='on' in tempval['humidity']['status']
                            self.warning_humidity_limit_setting=tempval['humidity']['warning_level']
                            self.humidity_limit_setting=tempval['humidity']['danger_level']
                            
                            self.windspeed_limit_on='on' in tempval['windspeed']['status']
                            self.warning_windspeed_limit_setting=tempval['windspeed']['warning_level']
                            self.windspeed_limit_setting=tempval['windspeed']['danger_level']
                            
                            self.lightning_limit_on='on' in tempval['lightning']['status']
                            self.warning_lightning_limit_setting=tempval['lightning']['warning_level']
                            self.lightning_limit_setting=tempval['lightning']['danger_level']
                            
                            self.temp_minus_dew_on='on' in tempval['tempDew']['status']
                            self.warning_temp_minus_dew_setting=tempval['tempDew']['warning_level']
                            self.temp_minus_dew_setting=tempval['tempDew']['danger_level']
                            
                            self.sky_minus_ambient_limit_on='on' in tempval['skyTempLimit']['status']
                            self.warning_sky_minus_ambient_limit_setting=tempval['skyTempLimit']['warning_level']
                            self.sky_minus_ambient_limit_setting=tempval['skyTempLimit']['danger_level']
                            
                            self.sky_temperature_limit_on='on' in tempval['skyTempLimit']['status']
                            self.warning_sky_temperature_limit_setting=tempval['skyTempLimit']['warning_level']
                            self.sky_temperature_limit_setting=tempval['skyTempLimit']['danger_level']
                            
                            
                            self.wema_settings_upload_timer=time.time() -2 * self.wema_settings_upload_period
                            self.update_status()
                            
                    else:
                        plog ("orphanned command?")
                        plog(cmd)
                
                # Open and store the settings in the wema settings shelf
                wema_settings_shelf = shelve.open(self.wema_settings_shelf_filename)
                
                
                wema_settings_shelf['mode']=g_dev['enc'].mode 
                wema_settings_shelf['observing_mode']=self.observing_mode
                wema_settings_shelf['local_weather_active']=self.local_weather_active
                wema_settings_shelf['owm_active']=self.owm_active
                wema_settings_shelf['keep_open_all_night']=self.keep_open_all_night
                wema_settings_shelf['keep_closed_all_night']=self.keep_closed_all_night
                if self.ocn_exists:
                    wema_settings_shelf['rain_limit_on']=self.rain_limit_on
                    wema_settings_shelf['warning_rain_limit_setting']=self.warning_rain_limit_setting
                    wema_settings_shelf['rain_limit_setting']=self.rain_limit_setting
                    
                    wema_settings_shelf['local_cloud_cover_limit_on']=self.local_cloud_cover_limit_on
                    wema_settings_shelf['warning_local_cloud_cover_limit_setting']=self.warning_local_cloud_cover_limit_setting
                    wema_settings_shelf['local_cloud_cover_limit_setting']=self.local_cloud_cover_limit_setting
                    
                    wema_settings_shelf['forecastl_cloud_cover_limit_on']=self.forecast_cloud_cover_limit_on
                    wema_settings_shelf['warning_forecast_cloud_cover_limit_setting']=self.warning_forecast_cloud_cover_limit_setting
                    wema_settings_shelf['forecast_cloud_cover_limit_setting']=self.forecast_cloud_cover_limit_setting
                    
                    
                    wema_settings_shelf['humidity_limit_on']=self.humidity_limit_on
                    wema_settings_shelf['warning_humidity_limit_setting']=self.warning_humidity_limit_setting
                    wema_settings_shelf['humidity_limit_setting']=self.humidity_limit_setting
                    
                    wema_settings_shelf['windspeed_limit_on']=self.windspeed_limit_on
                    wema_settings_shelf['warning_windspeed_limit_setting']=self.warning_windspeed_limit_setting
                    wema_settings_shelf['windspeed_limit_setting']=self.windspeed_limit_setting
                    
                    wema_settings_shelf['lightning_limit_on']=self.lightning_limit_on
                    wema_settings_shelf['warning_lightning_limit_setting']=self.warning_lightning_limit_setting
                    wema_settings_shelf['lightning_limit_setting']=self.lightning_limit_setting
                    
                    wema_settings_shelf['temp_minus_dew_on']=self.temp_minus_dew_on
                    wema_settings_shelf['warning_temp_minus_dew_setting']=self.warning_temp_minus_dew_setting
                    wema_settings_shelf['temp_minus_dew_setting']=self.temp_minus_dew_setting
                    
                    wema_settings_shelf['sky_minus_ambient_limit_on']=self.sky_minus_ambient_limit_on
                    wema_settings_shelf['warning_sky_minus_ambient_limit_setting']=self.warning_sky_minus_ambient_limit_setting
                    wema_settings_shelf['sky_minus_ambient_limit_setting']=self.sky_minus_ambient_limit_setting
                    
                    wema_settings_shelf['sky_temperature_limit_on']=self.sky_temperature_limit_on
                    wema_settings_shelf['warning_sky_temperature_limit_setting']=self.warning_sky_temperature_limit_setting
                    wema_settings_shelf['sky_temperature_limit_setting']=self.sky_temperature_limit_setting
              
                    wema_settings_shelf['lowest_ambient_temperature'] = self.lowest_temperature_setting
                    wema_settings_shelf['highest_ambient_temperature'] = self.highest_temperature_setting

                    wema_settings_shelf['lowest_temperature_on'] = self.lowest_temperature_on
                    wema_settings_shelf['highest_temperature_on']= self.highest_temperature_on  
                    
                    
                    wema_settings_shelf['hightemperature_limit_warning_level'] = self.warning_highest_temperature_setting
                    #status['wema_settings']['hightemperature_limit_danger_level'] = self.highest_temperature_setting
                    
                    # status['wema_settings']['lowtemperature_limit_on']  = self.lowest_temperature_on
                    # status['wema_settings']['lowtemperature_limit_quiet'] = self.lowtemp_limit_quiet
                    wema_settings_shelf['lowtemperature_limit_warning_level'] = self.warning_lowest_temperature_setting
                    # status['wema_settings']['lowtemperature_limit_danger_level'] = self.lowest_temperature_setting

              
                #pid = camShelf["pid_obs"]  # a 9 character string
                wema_settings_shelf.close()
                

            except:
                if 'Internal server error' in str(unread_commands):
                    plog("AWS server glitch reading unread_commands")
                else:
                    plog(traceback.format_exc())
                    plog("unread commands")
                    plog(unread_commands)
                    plog("MF trying to find whats happening with this relatively rare bug!")

        return



    def update_status(self):
        """
        Collect status from weather and enclosure devices and sends an
        update to AWS. Each device class is responsible for implementing the
        method 'get_status()', which returns a dictionary.
        """


        enc_status = None
        ocn_status = None
        wema = self.config['wema_name']  
        sync_obs= self.config['obsp_ids'][0]
        
        # For those domes not synced by ascom, check in with telescope      
        
        # pointing and rotate dome accordingly
        # This needs a config item at some stage
        # Only bother checking if the shutter is open
        enc_status=g_dev['enc'].get_status()
        
        if enc_status is not None:
            if enc_status['shutter_status'] in ['Open', 'Sim Open']:
            #if True:
                if 'MaxDome' in g_dev['enc'].config['enclosure']['enclosure1']['driver']:
                    
                    if time.time() > (self.dome_check_timer + self.dome_check_timer_period):
                        #plog (time.time() - self.dome_check_timer)
                        self.dome_check_timer=time.time()
                        
                        dome_at_scope=False
                        
                        while not dome_at_scope:
                            report_timer=time.time() - 31
                            try:
                                slew_timeout_timer=time.time()
                                while g_dev['enc'].enclosure.Slewing and time.time()-slew_timeout_timer < 300:
                                    if time.time() - report_timer > 10:
                                        plog("Waiting for dome to stop slewing")
                                        report_timer=time.time()
                                    #self.send_enclosure_status(self.enc_status, self.ocn_status)
                                    time.sleep(0.25)
                            except:
                                plog(traceback.format_exc())
                                plog ("DOME COMMAND GLITCHED OUT.")
                            
                            enc_status = g_dev['enc'].get_status()
                            self.send_enclosure_status(enc_status, [])
                            
                            
                            # Call out to aws to get current main scope pointing and ra and dec
                            
                            uri_status = f"{PTR_STATUS_ROOT}/{sync_obs}/device"
                            try:
                                #plog ("Grabbing obs status")


                                main_obs_status=requests.get(uri_status, timeout=20, allow_redirects=False, headers=close_headers, stream=False)
                                #try:
                                #main_obs_status = func_timeout(10, requests.get, args=(uri_status,), kwargs={"timeout": 20, "allow_redirects": False, "headers": close_headers, "stream": False})
                                #except:
                                
                                #plog ("Got obs status")
                            
                                    
                                obs_mount_name=list(main_obs_status.json()['status']['mount'].keys())[0]
                                
                                obs_mount_status=main_obs_status.json()['status']['mount'][obs_mount_name]
                                
                                
                                # Where is scope currently pointing?
                                obs_mount_ra=obs_mount_status['right_ascension']['val']
                                obs_mount_dec=obs_mount_status['declination']['val']
                                
                                
                                # Figure out the implied azimuth for that ra and dec at this location                      
                                observation_time=Time.now()
                                
                                sky_coord=SkyCoord(ra=obs_mount_ra*15*u.deg, dec=obs_mount_dec*u.deg)
                                # Convert to AltAz frame
                                altaz_frame = AltAz(obstime=observation_time, location=self.observer_location)
                                altaz_coords = sky_coord.transform_to(altaz_frame)
                                
                                #obs_current_altitude = altaz_coords.alt.deg
                                obs_current_azimuth = altaz_coords.az.deg
                                
                                
                                
                                
                                
                                slave_directly_to_telescope_pointing=False
                                if slave_directly_to_telescope_pointing:
                                    obs_mount_ra=obs_mount_status['right_ascension']['val']
                                    obs_mount_dec=obs_mount_status['declination']['val']
                                    
                                    
                                    # Figure out the implied azimuth for that ra and dec at this location                      
                                    observation_time=Time.now()
                                    
                                    sky_coord=SkyCoord(ra=obs_mount_ra*15*u.deg, dec=obs_mount_dec*u.deg)
                                    # Convert to AltAz frame
                                    altaz_frame = AltAz(obstime=observation_time, location=self.observer_location)
                                    altaz_coords = sky_coord.transform_to(altaz_frame)
                                    
                                    # Extract altitude and azimuth
                                    #obs_altitude = altaz_coords.alt.deg
                                    obs_target_azimuth = altaz_coords.az.deg
                                    obs_target_altitude = altaz_coords.alt.deg
                                
                                else:
                                    obs_target_azimuth=obs_mount_dec=obs_mount_status['target_az']['val']
                                    obs_target_altitude=obs_mount_dec=obs_mount_status['target_alt']['val']
                                
                                #### At this stage, we actually want to adjust the requested azimuth
                                #### To move the dome slightly west or east depending on the 
                                #### pierside of the telescope
                                
                                if obs_target_azimuth == -500:
                                    #plog ("Target Azimuth for Scope not an actual skytarget, so not moving dome")
                                    #plog(f"Actual Azimuth: {obs_current_azimuth:.2f} degrees")
                                    dome_at_scope=True
                                    pass
                                else:
                                    
                                    plog ("Requested Azmituh: " + str(obs_target_azimuth))
                                    
                                    
                                    
                                    correct_dome_for_pier_effect=True
                                    if correct_dome_for_pier_effect:
                                        # Example usage
                                        telescope_azimuth = obs_target_azimuth  # Example telescope azimuth
                                        telescope_altitude = obs_target_altitude   # Example telescope altitude
                                        if obs_mount_status['pier_side']['val'] == 1:
                                            side_of_pier = 'W'        # 'E' or 'W'
                                        else:
                                            side_of_pier = 'E'        # 'E' or 'W'
                                        dome_radius = g_dev['enc'].config['enclosure']['enclosure1']['dome_radius']           # Example dome radius in meters
                                        telescope_offset = g_dev['enc'].config['enclosure']['enclosure1']['offset_from_ota_to_axis']     # Telescope offset from the center in meters
                                        #dome_slit_offset =       # Small additional offset in degrees
                                        
                                        target_dome_azimuth = correct_dome_azimuth(telescope_azimuth, telescope_altitude, side_of_pier, dome_radius, telescope_offset)#, dome_slit_offset)
    
                                        #plog ("Corrected Azmituh: " + str(corrected_dome_az))
                                    else:
                                        target_dome_azimuth=obs_target_azimuth
                                    
                                    
                                    #plog(f"Time: {observation_time.iso}")
                                    plog ("Primary Obs Pointing")
                                    #plog(f"Altitude: {obs_altitude:.2f} degrees")
                                    
                                    plog(f"Target Telescope Azimuth: {obs_target_azimuth:.2f} degrees")
                                    
                                    plog(f"Actual Telescope Azimuth: {obs_current_azimuth:.2f} degrees")
                                    
                                    plog(f"Target Dome Azimuth: {target_dome_azimuth:.2f} degrees")
                                                                    
                                    # Temporary hack - 
                                    target_azimuth = obs_target_azimuth + self.dome_offset
                                    if target_azimuth > 360:
                                        target_azimuth=target_azimuth - 360
                                    if target_azimuth < 0:
                                        target_azimuth=target_azimuth + 360
                                    
                                    try:
                                        current_dome_azimuth= g_dev['enc'].enclosure.Azimuth
                                    except:
                                        plog(traceback.format_exc())
                                        plog ("DOME COMMAND GLITCHED OUT.")
                                    
                                    plog(f"Current Dome Azimuth: {current_dome_azimuth:.2f} degrees")
                                    
                                    dome_out_by=abs (current_dome_azimuth-target_dome_azimuth)
                                    if dome_out_by > 180:
                                        dome_out_by=abs(dome_out_by-360)                                   
                                    
                                    plog ("Dome out by: " + str (dome_out_by))
                                    if abs (dome_out_by) > 1:                       
                                        plog ("Moving Dome")
                                    
                                        try:                                            
                                            g_dev['enc'].enclosure.SlewToAzimuth(target_dome_azimuth)
                                            enc_status = g_dev['enc'].get_status()
                                            self.send_enclosure_status(enc_status, [])
                                            
                                            dome_at_scope=False
                                            #time.sleep(10)
                                        except:
                                            plog(traceback.format_exc())
                                            plog ("DOME COMMAND GLITCHED OUT.")
                                            
                                    else:
                                        plog ("Leaving Dome as it is")
                                        dome_at_scope=True
                            except:
                                plog(traceback.format_exc())
                                plog ("failed getting the obs status probably, but also might be a dome thing in the dome position area")
                                

        loud = False
        while time.time() < self.time_last_status + self.status_interval:
            return        

        # Hourly Weather Report
        if time.time() > (self.weather_report_run_timer + 3600):
            self.weather_report_run_timer=time.time()
            if self.enc_status_custom:
                enc_status={}
                enc_status['enclosure']={}

                enc_status['enclosure']['enclosure1']= get_enc_status_custom()
                self.run_nightly_weather_report(enc_status=enc_status['enclosure']['enclosure1'], ocn_status=g_dev['ocn'].get_status())
            else:
                
                self.run_nightly_weather_report(enc_status=g_dev['enc'].get_status(), ocn_status=g_dev['ocn'].get_status())
        
        
        # Enclosure and Weather Status
        if time.time() > self.enclosure_status_check_timer + self.enclosure_status_check_period:
            self.enclosure_status_check_timer = time.time()
            status = {}
            status["timestamp"] = round(time.time(), 1)
            status['enclosure']={}

            if self.enc_status_custom==False:
                device=self.all_devices.get('enclosure', {})['enclosure1']
                status['enclosure']['enclosure1'] = device.get_status()
                enc_status = {"enclosure": status.pop("enclosure")}
            else:
                #This is SRO mode
                enc_status={}
                enc_status['enclosure']={}

                enc_status['enclosure']['enclosure1']= get_enc_status_custom()
            
            self.send_enclosure_status(enc_status, ocn_status)

    

        if time.time() > self.weather_status_check_timer + self.weather_status_check_period:
            self.weather_status_check_timer=time.time()
            status = {}
            status["timestamp"] = round(time.time(), 1)
            status['observing_conditions'] = {}
            if self.ocn_status_custom==False:
                device = self.all_devices.get('observing_conditions', {})['observing_conditions1']
                if device == None:
                    status['observing_conditions']['observing_conditions1'] = None
                else:
                    status['observing_conditions']['observing_conditions1'] = device.get_status()
                    ocn_status = {"observing_conditions": status.pop("observing_conditions")}
            else:
                ocn_status={}
                ocn_status['observing_conditions']={}
                ocn_status['observing_conditions']['observing_conditions1'] = get_ocn_status_custom()

            if ocn_status is None or ocn_status['observing_conditions']['observing_conditions1']  == None:   #20230709 Changed from not None
                ocn_status = {}
                ocn_status['observing_conditions'] = {}
                ocn_status['observing_conditions']['observing_conditions1'] = dict(wx_ok='Unknown',
                                                                                       wx_hold='no',
                                                                                       hold_duration=0)


            ocn_status['observing_conditions']['observing_conditions1']['weather_report_good'] = self.weather_report_open_at_start
            try:
                ocn_status['observing_conditions']['observing_conditions1']['fitzgerald_number'] = self.night_fitzgerald_number  # uninit Variable
            except:
                pass

            
            # Here is where we actually make the decision about the weather
            # Independantly of the actual observing conditions device        
            # THE WAYNE ROSING BRAND WEATHER DECISION DESK!!! Made from the status, not in the device

            quick_status=ocn_status['observing_conditions']['observing_conditions1']
            
            if self.ocn_exists:
                try:

                    if quick_status['humidity_%'] == -1:
                        plog ("local weather station not reporting humidity, using last owm report")
                        ocn_status['observing_conditions']['observing_conditions1']['humidity_%']=self.current_owm_humidity
                        quick_status['humidity_%'] = self.current_owm_humidity
    
                        plog ("OWM Humidity: " + str(self.current_owm_humidity))      

                except:
                    pass
            
            
            
            #self.lightning_limit_on = self.config['lightning_limit_on']
            
            
            
            # if self.rain_limit_on:
            #     try:
            #         rain_limit = quick_status['rain_rate'] > self.rain_limit_setting
            #     except:
            #         rain_limit = False
            #     if rain_limit:
            #         plog("Reported rain rate in mm/hr:  ", quick_status['rain_rate'])
            #         wx_reasons.append('Rain > ' + str(self.rain_limit_setting))

            
            # Simply override cloud_cover for the moment
            quick_status['forecast_cloud_cover_%']=self.medianforecast_current_cloud_cover
            
            if self.number_of_nighttime_weather_observations < 250:
                plog ("We haven't built up enough data points yet to be confident in predicting local clouds yet. Not using Local Cloud Cover yet.")
                quick_status['local_cloud_cover_%']=None 

            
            
            else:
                try:           
                    quick_status['local_cloud_cover_%']=self.predicted_clouds[0]
                    #plog ("goog " + str(self.predicted_clouds[0]))
                except:
                    plog ("Can't use predicted clouds for local cloud cover... usually because this is booting up and hasn't run a model yet. Temporarily approximating it using the forecast values.")
                    quick_status['local_cloud_cover_%']=self.medianforecast_current_cloud_cover            
                
            wx_reasons = []            
            
            
            if self.ocn_exists:
                if self.rain_limit_on:
                    rain_limit = quick_status['rain_rate'] > self.rain_limit_setting
                    if rain_limit:
                        plog("Reported rain rate in mm/hr:  ", quick_status['rain_rate'])
                        wx_reasons.append('Rain > ' + str(self.rain_limit_setting))
                        # Also here move the next allowed open time to much later
                        # Like until 45 minutes later. If there is rain around
                        # We have to be safe. This should continually update as the status
                        # is updated such that the enclosure won't be able to open until
                        # at least 45 minutes after the last reported rain fall
                        self.enclosure_next_open_time = time.time() + 2700
                else:
                    rain_limit=False
                
                if self.humidity_limit_on:
                    humidity_limit = quick_status['humidity_%'] < self.humidity_limit_setting
                    if not humidity_limit:
                        wx_reasons.append('Humidity >= ' + str(self.humidity_limit_setting) + '%')
                else:
                    humidity_limit=True
                
                if self.windspeed_limit_on:
                    wind_limit = (
                            quick_status['wind_m/s']*0.2778 < self.windspeed_limit_setting
                    )  # sky_monitor reports km/h, Clarity may report in MPH
                    if not wind_limit:
                        wx_reasons.append('Wind > ' + str(self.windspeed_limit_setting) + ' km/h')
                else:
                    wind_limit=True
                
                if self.temp_minus_dew_on:
                    dewpoint_gap = (
                        not (quick_status['temperature_C']- quick_status['dewpoint_C']) < self.temp_minus_dew_setting
                    )
                    if not dewpoint_gap:
                        wx_reasons.append('Ambient - Dewpoint < ' + str(self.temp_minus_dew_setting) + 'C')
                else:
                    dewpoint_gap=True
                
                if self.sky_minus_ambient_limit_on:
                    sky_amb_limit = (
                                            quick_status['sky_temp_C']- quick_status['temperature_C']
                                    ) < self.sky_minus_ambient_limit_setting  # NB THIS NEEDS ATTENTION, Sky alert defaults to -17
                    if not sky_amb_limit:
                        wx_reasons.append('(sky - amb) > ' + str(self.sky_minus_ambient_limit_setting) + 'C')
                else:
                    sky_amb_limit=True
                    
                if self.sky_temperature_limit_on:
                    sky_temp_limit = (
                                            quick_status['sky_temp_C']
                                    ) < self.sky_temperature_limit_setting  # NB THIS NEEDS ATTENTION, Sky alert defaults to -17
                    if not sky_temp_limit:
                        wx_reasons.append('(sky temperature) > ' + str(self.sky_temperature_limit_setting) + 'C')
                else:
                    sky_temp_limit=True
                
                if self.local_cloud_cover_limit_on:                
                    try:
                        local_cloud_cover_value = float(quick_status['local_cloud_cover_%'])
                        #status['cloud_cover_%'] = round(cloud_cover_value, 0)
                        if local_cloud_cover_value == None:
                            local_cloud_cover = False
                        
                        elif local_cloud_cover_value <= self.local_cloud_cover_limit_setting:
                            local_cloud_cover = False
                            #wx_reasons.append('>=' + str(self.cloud_cover_limit_setting) + '% Cloudy')
                    
                        else:
                            local_cloud_cover = True
                            wx_reasons.append('>=' + str(self.local_cloud_cover_limit_setting) + '% Cloudy Local Sensor')
                    except:
                        #status['cloud_cover_%'] = "no report"
                        plog ("failed to get local cloud cover... usually the model is not ready yet due to lack of weather data points.")
                        local_cloud_cover = False  # We cannot use this signal to force a wX hold or close
                else:
                    local_cloud_cover = False
                
                
                if self.lowest_temperature_on:
                    low_temp_bound=not quick_status['temperature_C'] < self.lowest_temperature_setting
                else: 
                    low_temp_bound=True
                
                if self.highest_temperature_on:
                    high_temp_bound=not quick_status['temperature_C'] > self.highest_temperature_setting
                else:
                    high_temp_bound=True
                    
                temp_bounds=True
                if not low_temp_bound or not high_temp_bound:
                    temp_bounds=False
                    wx_reasons.append('amb temp out of range')
                
            if self.forecast_cloud_cover_limit_on:
                try:
                    forecast_cloud_cover_value = float(quick_status['forecast_cloud_cover_%'])
                    #status['cloud_cover_%'] = round(cloud_cover_value, 0)
                    if forecast_cloud_cover_value <= self.forecast_cloud_cover_limit_setting:
                        forecast_cloud_cover = False
                        #wx_reasons.append('>=' + str(self.cloud_cover_limit_setting) + '% Cloudy')
                
                    else:
                        forecast_cloud_cover = True
                        wx_reasons.append('>=' + str(self.forecast_cloud_cover_limit_setting) + '% Cloudy Forecast')
                except:
                    #status['cloud_cover_%'] = "no report"
                    forecast_cloud_cover = True  # We cannot use this signal to force a wX hold or close
            else:
                forecast_cloud_cover = False
            
            
            
            
            if self.ocn_exists:
                self.local_weather_ok = dewpoint_gap and temp_bounds and wind_limit and sky_amb_limit  and sky_temp_limit and humidity_limit and not rain_limit and not local_cloud_cover and not forecast_cloud_cover 
            else:
                self.local_weather_ok =  not forecast_cloud_cover 

            # An ok-to-open monitor reporting unsafe overrides the readings:
            # it exists precisely to say no when the numbers look fine. Only
            # an explicit No vetoes, so a missing or unreadable monitor cannot
            # quietly hold the roof shut.
            try:
                safety_monitor_ok = ocn_status['observing_conditions'][
                    'observing_conditions1'].get('safety_monitor_ok')
            except Exception:
                safety_monitor_ok = None
            if safety_monitor_ok == 'No':
                self.local_weather_ok = False
                wx_reasons.append('Safety monitor reports unsafe.')
            
            
            
            if self.local_weather_ok:
                ocn_status['observing_conditions']['observing_conditions1']["local_weather_ok"] = "Yes"
            else:
                ocn_status['observing_conditions']['observing_conditions1']["local_weather_ok"] = "No"    
    
            ocn_status['observing_conditions']['observing_conditions1']["OWM_weather_ok"] = self.weather_report_open_at_start
            
            if self.owm_active and not self.weather_report_open_at_start:
                wx_reasons.append("OpenWeatherMap Report negative.")
    
            if self.local_weather_active and self.owm_active:
                combined_weather_ok = self.local_weather_ok and self.weather_report_open_at_start
            elif  self.owm_active:
                combined_weather_ok = self.weather_report_open_at_start
            elif self.local_weather_active:
                combined_weather_ok = self.local_weather_ok
            else:
                combined_weather_ok = 'Not considered'
                            
            ocn_status['observing_conditions']['observing_conditions1']["wx_ok"] = combined_weather_ok
            plog('Wx Ok: ', combined_weather_ok, wx_reasons)
    
            
            #######
            # ONCE WE HAVE FIGURED ALL THAT OUT, THEN SEND THE STATUS
            ################
            
            if self.enclosure_next_open_time - time.time() > 0:
                ocn_status['observing_conditions']['observing_conditions1']['hold_duration'] = round(self.enclosure_next_open_time - time.time(), 1)
            else:
                ocn_status['observing_conditions']['observing_conditions1']['hold_duration'] = 0
            
            ocn_status['observing_conditions']['observing_conditions1']["wx_hold"] = not combined_weather_ok
    
            if ocn_status is not None:
                lane = "weather"
                try:
                    send_status(wema, lane, ocn_status)
                except:
                    plog('could not send weather status')                  

            loud = False
            if loud:
                plog("\n\n > Status Sent:  \n", ocn_status)
            
            self.ocn_status=ocn_status

        # WEMA Settings
        if time.time() > self.wema_settings_upload_timer + self.wema_settings_upload_period:
            self.wema_settings_upload_timer = time.time()

            status = {}
            status['wema_settings']={}
            status['wema_settings']['OWM_active']=self.owm_active
            status['wema_settings']['local_weather_active']=self.local_weather_active
            status['wema_settings']['keep_roof_open_all_night'] = self.keep_open_all_night
            status['wema_settings']['keep_roof_closed_all_night']  = self.keep_closed_all_night
            
            status['wema_settings']['open_at_specific_utc'] = self.open_at_specific_utc
            status['wema_settings']['specific_utc_when_to_open'] = self.specific_utc_when_to_open
            
            status['wema_settings']['manual_weather_hold_set'] = self.manual_weather_hold_set
            status['wema_settings']['manual_weather_hold_duration'] = self.manual_weather_hold_duration
            status['wema_settings']['observing_mode'] =self.observing_mode
                    
            if self.ocn_exists:
                # Local Weather Limits
                status['wema_settings']['rain_limit_on'] = self.rain_limit_on
                status['wema_settings']['rain_limit_quiet'] = self.rain_limit_quiet
                status['wema_settings']['rain_limit_warning_level'] = self.warning_rain_limit_setting
                status['wema_settings']['rain_limit_danger_level'] = self.rain_limit_setting
                
                status['wema_settings']['local_cloud_limit_on'] = self.local_cloud_cover_limit_on
                status['wema_settings']['local_cloud_limit_quiet'] = self.local_cloud_limit_quiet
                status['wema_settings']['local_cloud_limit_warning_level'] = self.warning_local_cloud_cover_limit_setting
                status['wema_settings']['local_cloud_limit_danger_level'] = self.local_cloud_cover_limit_setting
                
                status['wema_settings']['forecast_cloud_limit_on'] = self.forecast_cloud_cover_limit_on
                status['wema_settings']['forecast_cloud_limit_quiet'] = self.forecast_cloud_limit_quiet
                status['wema_settings']['forecast_cloud_limit_warning_level'] = self.warning_forecast_cloud_cover_limit_setting
                status['wema_settings']['forecast_cloud_limit_danger_level'] = self.forecast_cloud_cover_limit_setting
                
                
                status['wema_settings']['humidity_limit_on']  = self.humidity_limit_on
                status['wema_settings']['humidity_limit_quiet'] = self.humidity_limit_quiet
                status['wema_settings']['humidity_limit_warning_level'] = self.warning_humidity_limit_setting
                status['wema_settings']['humidity_limit_danger_level'] = self.humidity_limit_setting
                
                status['wema_settings']['windspeed_limit_on']  = self.windspeed_limit_on
                status['wema_settings']['windspeed_limit_quiet'] = self.windspeed_limit_quiet
                status['wema_settings']['windspeed_limit_warning_level'] = self.warning_windspeed_limit_setting
                status['wema_settings']['windspeed_limit_danger_level'] = self.windspeed_limit_setting
                
                status['wema_settings']['lightning_limit_on']  = self.lightning_limit_on
                status['wema_settings']['lightning_limit_quiet'] = self.lightning_limit_quiet
                status['wema_settings']['lightning_limit_warning_level'] = self.warning_lightning_limit_setting
                status['wema_settings']['lightning_limit_danger_level'] =  self.lightning_limit_setting
                
                status['wema_settings']['tempminusdew_limit_on']  = self.temp_minus_dew_on
                status['wema_settings']['tempminusdew_limit_quiet'] = self.temp_minus_dew_quiet
                status['wema_settings']['tempminusdew_limit_warning_level'] = self.warning_temp_minus_dew_setting
                status['wema_settings']['tempminusdew_limit_danger_level'] = self.temp_minus_dew_setting
                
                status['wema_settings']['sky_minus_ambient_limit_on']  = self.sky_minus_ambient_limit_on
                status['wema_settings']['sky_minus_ambient_limit_quiet'] = self.sky_minus_ambient_limit_quiet
                status['wema_settings']['sky_minus_ambient_limit_warning_level'] = self.warning_sky_minus_ambient_limit_setting
                status['wema_settings']['sky_minus_ambient_limit_danger_level'] = self.sky_minus_ambient_limit_setting
                
                status['wema_settings']['sky_temperature_limit_on']  = self.sky_temperature_limit_on
                status['wema_settings']['sky_temperature_limit_quiet'] = self.sky_temperature_limit_quiet
                status['wema_settings']['sky_temperature_limit_warning_level'] = self.warning_sky_temperature_limit_setting
                status['wema_settings']['sky_temperature_limit_danger_level'] = self.sky_temperature_limit_setting
                
                status['wema_settings']['hightemperature_limit_on']  = self.highest_temperature_on
                status['wema_settings']['hightemperature_limit_quiet'] = self.hightemp_limit_quiet
                status['wema_settings']['hightemperature_limit_warning_level'] = self.warning_highest_temperature_setting
                status['wema_settings']['hightemperature_limit_danger_level'] = self.highest_temperature_setting
                
                status['wema_settings']['lowtemperature_limit_on']  = self.lowest_temperature_on
                status['wema_settings']['lowtemperature_limit_quiet'] = self.lowtemp_limit_quiet
                status['wema_settings']['lowtemperature_limit_warning_level'] = self.warning_lowest_temperature_setting
                status['wema_settings']['lowtemperature_limit_danger_level'] = self.lowest_temperature_setting

            lane = "wema_settings"
            try:                
                send_status(wema, lane, status)
            except:
                plog('could not send wema_settings status') 
                    
    def send_enclosure_status(self, enc_status, ocn_status):

        if enc_status is not None:
            
            # Reformulate a short enclosure status - bit of a hack for the moment.
            try: 
                plog (enc_status['enclosure']['enclosure1']['shutter_status'] )
                plog ("good")
            except:
                enc_status_extended={}

                enc_status_extended['enclosure'] ={}

                enc_status_extended['enclosure']['enclosure1'] ={}
                
                enc_status_extended['enclosure']['enclosure1'] = enc_status
                
                enc_status=enc_status_extended
                plog ("bad")
            
            # New Tim Entries
            if enc_status['enclosure']['enclosure1']['shutter_status']  is not None:
                if enc_status['enclosure']['enclosure1']['shutter_status'] in ['Open', 'Sim Open']:
                    enc_status['enclosure']['enclosure1']['enclosure_is_open'] = True
                    enc_status['enclosure']['enclosure1']['shut_reason_bad_weather'] = False
                    enc_status['enclosure']['enclosure1']['shut_reason_daytime'] = False
                    enc_status['enclosure']['enclosure1']['shut_reason_manual_mode'] = False
            else:
                enc_status['enclosure']['enclosure1']['enclosure_is_open'] = False
                if not enc_status['enclosure']['enclosure1']['enclosure_mode'] == 'Automatic':
                    enc_status['enclosure']['enclosure1']['shut_reason_manual_mode'] = True
                else:
                    enc_status['enclosure']['enclosure1']['shut_reason_manual_mode'] = False
                if ocn_status is not None:  #NB NB ocn status has never been established first time this is envoked after startup -WER
                    if ocn_status['observing_conditions']['observing_conditions1']['wx_ok'] == 'Unknown':
                        enc_status['enclosure']['enclosure1']['shut_reason_bad_weather'] = False
                    elif ocn_status['observing_conditions']['observing_conditions1']['wx_ok'] == 'No' or not self.weather_report_open_at_start:
                        enc_status['enclosure']['enclosure1']['shut_reason_bad_weather'] = True
                elif not self.weather_report_open_at_start:
                    enc_status['enclosure']['enclosure1']['shut_reason_bad_weather'] = True
                else:
                    enc_status['enclosure']['enclosure1']['shut_reason_bad_weather'] = False

                    # NEED TO INCLUDE WEATHER REPORT AND FITZ NUMBER HERE

                if g_dev['events']['Cool Down, Open'] < ephem.now() or ephem.now() < g_dev['events'][
                    'Close and Park'] > ephem.now():
                    enc_status['enclosure']['enclosure1']['shut_reason_daytime'] = True
                else:
                    enc_status['enclosure']['enclosure1']['shut_reason_daytime'] = False
                    
            if 'MaxDome' in g_dev['enc'].config['enclosure']['enclosure1']['driver']:   
                # Remove the dome_offset
                try:
                    actual_azimuth = g_dev['enc'].enclosure.Azimuth - self.dome_offset
                    if actual_azimuth > 360:
                        actual_azimuth=actual_azimuth - 360
                    if actual_azimuth < 0:
                        actual_azimuth=actual_azimuth + 360
                    
                    enc_status['enclosure']['enclosure1']['dome_azimuth'] = actual_azimuth
                    plog ("reported dome az: " + str(actual_azimuth))
                except:
                    plog(traceback.format_exc())
                    plog ("DOME COMMAND GLITCHED OUT.")
                
            else:
                enc_status['enclosure']['enclosure1']['dome_azimuth'] = 0
            
            
            # If the observing mode is set to off, append a noobs to prevent the obs from observing   #Why have this in the WEMA?  
            #  There is a more intersting thing to deal with -- opening into a night with no observations scheduled, or having
            #  a long blank spot ofter an early night of observing.
            if self.observing_mode == 'inactive':
                enc_status['enclosure']['enclosure1']['shutter_status'] += '/NoObs'

            if enc_status is not None:
                lane = "enclosure"
                wema = self.config['wema_name']  
                try:                        
                    send_status(wema, lane, enc_status)
                except:
                    plog('could not send enclosure status')   
                    plog(traceback.format_exc())



    def update(self):     ## NB NB NB This is essentially the Manager/Sequencer for the
                          ## enclosures managed by the WEMA
        try:
            self.update_status()
        except:
            
            plog(traceback.format_exc())
            plog ("failed to update status")


        if time.time() > self.scan_requests_timer + self.scan_requests_check_period:
            self.scan_requests_timer=time.time()
            self.scan_requests()


        if time.time() > self.safety_check_timer + self.safety_status_check_period:
            try:
                self.safety_check_timer=time.time()
    
                # Here it runs through the various checks and decides whether to open or close the roof or not.
                # Check for delayed opening of the enclosure and act accordingly.
                
                
    
                # If the enclosure is simply delayed until opening, then wait until then, then attempt to start up the enclosure
                obs_win_begin, sunZ88Op, sunZ88Cl, ephem_now = self.astro_events.getSunEvents()
                
                if (g_dev['events']['Cool Down, Open'] <= ephem_now) or \
                    (g_dev['events']['Close and Park'] <= ephem_now):
                    self.nightly_reset_complete = False
    
                #This is used to access SRO weather and Enclosure shares.
    
                if self.ocn_status_custom==False:                            
                    ocn_status = g_dev['ocn'].get_status()
                else:
                    ocn_status = get_ocn_status_custom()
                if self.enc_status_custom==False:                
                    enc_status = g_dev['enc'].get_status()
                else:
                    enc_status = get_enc_status_custom()
    
                plog("***************************************************************")
                plog("Current time             : " + str(time.asctime()))
                plog("Enclosure Mode           : " + str(enc_status['enclosure_mode']))
                plog("Shutter Status           : " + str(enc_status['shutter_status']))
                
                if ocn_status == None:
                    plog("This WEMA does not report observing conditions")
                else:
                    plog("Observing Conditions      : " +str(ocn_status))
                    
                if self.local_weather_ok == None:
                    plog("No information on local weather available.")
                else:
                    plog("Local Weather Ok to Observe  : " + str(self.local_weather_ok))
                    if not self.local_weather_active:
                        plog ("However, Local Weather control is set off")
                
                if g_dev['enc'].mode == 'Manual':
                    plog ("Weather Considerations overriden due to being in Manual or debug mode: ")
                
                plog("OWM Weather Report Good to Observe: " + str(self.weather_report_open_at_start))
                plog("Time until Cool and Open      : " + str(round(( g_dev['events']['Cool Down, Open'] - ephem_now) * 24,2)) + " hours")
                plog("Time until Close and Park     : "+ str(round(( g_dev['events']['Close and Park'] - ephem_now) * 24,2)) + " hours")
                plog("Time until Nightly Reset      : " + str(round((g_dev['events']['Nightly Reset'] - ephem_now) * 24, 2)) + " hours")
                plog("Nightly Reset Complete        : " + str(self.nightly_reset_complete))
                plog("\n")
    
                if not self.owm_active:
                    plog("OWM is off. OWM information is advisory only, it is currently inactive.")
    
                if self.owm_active:
                    plog("OWM is on. OWM predicts it will set to open/close the roof at these times.")
    
                if not self.local_weather_active:
                    plog("Reacting to local weather is *OFF*. Not reacting to local weather signals.")
    
                if self.local_weather_active:
                    plog("Reacting to local weather is *ON*. Reacting to local weather signals.")
    
                if self.keep_open_all_night:
                    plog("Roof is being forced to stay OPEN ALL NIGHT")
    
                if self.keep_closed_all_night:                
                    plog("Roof is being forced to stay CLOSED ALL NIGHT")
    
                if self.ocn_exists:
                    model_skyambient=ocn_status['sky_temp_C']-self.current_owm_ambient_temperature
                    
                    
                    ########## FIRST CORRECT SKY TEMPERATURE FOR SUN ADN MOON EFFECTS
                    
                    
                    sun_altitude, moon_altitude, moon_illumination, flux_ground, sun_azimuth = self.get_sun_and_moon_info()
                
                                   
                    new_data = pd.DataFrame({
                        'corrected_sky_temp_C': ocn_status['sky_temp_C'],
                        'sky-ambient': [model_skyambient],
                        'sky-ambient^2': [model_skyambient **2]
                    })
                    
                    plog (new_data)
                    try:                    
                        
                        if sun_altitude.deg >= 18:
                            self.predicted_clouds = self.daytime_cloud_model.predict(new_data)
                        elif sun_altitude.deg <= -18:
                            self.predicted_clouds = self.nighttime_cloud_model.predict(new_data)
                        else:
                            fraction_through_transition = (sun_altitude.deg + 18) / 36
                            daytime_cloud_prediction=self.daytime_cloud_model.predict(new_data)
                            plog ("daytime prediction: "+ str(daytime_cloud_prediction))
                            nighttime_cloud_prediction=self.nighttime_cloud_model.predict(new_data)
                            plog ("nighttime prediction: "+ str(nighttime_cloud_prediction))
                            
                            self.predicted_clouds= fraction_through_transition *  daytime_cloud_prediction + (1-fraction_through_transition) * nighttime_cloud_prediction
                            
                        self.cloud_tracker.append(self.predicted_clouds[0])
                        if len(self.cloud_tracker) > 10:
                            self.cloud_tracker.pop(0)
                        
                        self.median_cloud_estimate=round(np.median(self.cloud_tracker),2)
                    
                        plog(f"Predicted clouds: {self.predicted_clouds[0]:.2f}")
                        plog ("Past clouds: " + str(self.cloud_tracker))
                        plog ("Median of last ten observations: " + str(round(np.median(self.cloud_tracker),2)) + " std " + str(round(np.std(self.cloud_tracker),2)))
        
                    except:
                        plog ("failed model? Perhaps can happen if we haven't built up enough points yet.")
                        self.median_cloud_estimate=100
                        plog(traceback.format_exc())
                else:
                    self.median_cloud_estimate=None
    
                try:
                    plog ("****************************")
                    plog("FORECAST DERIVED CLOUD COVER")
                    plog("OWM cloud cover: " +_pct(self.owm_cloud_cover))
                    plog("Open Meteo cloud cover: " +_pct(self.open_meteo_cloud_cover))
                    plog("TomorrowIO Now: " +_pct(self.tomorrowio_cloud_now))
                    plog("Pirate Now: " +_pct(self.pirate_clouds_now))
                    plog("Metocean Now: " +_pct(self.metocean_clouds_now))
                    plog("Worldweather Now: " +_pct(self.worldweather_current_cloud))
                    
                    plog('**')
                    
                    plog("OWM Next Hour: " +_pct(self.owm_cloud_cover_next_hour))
                    plog("Open Meteo Next Hour: " +_pct(self.open_meteo_cloud_cover_next_hour))
                    plog("TomorrowIO Next Hour: " +_pct(self.tomorrowio_cloud_inanhour))
                    
                    plog("Pirate Next Hour: " +_pct(self.pirate_clouds_inanhour))
                    
                    plog("Metocean Next Hour: " +_pct(self.metocean_clouds_inanhour))
                    
                    plog("Worldweather Next Hour: " +_pct(self.worldweather_nexthour_cloud))
                    
                    plog('**')
                    
                    plog("Median cloud cover from all estimates: "+_pct(self.medianforecast_current_cloud_cover))
        
                    plog("**************************************************************")
                except:
                    plog(traceback.format_exc())
    
                if (g_dev['events']['Nightly Reset'] <= ephem.now() < g_dev['events']['End Nightly Reset']):
                    if self.nightly_reset_complete == False:
                        self.nightly_reset_complete = True
                        self.nightly_reset_script(enc_status)
                
                # Safety checks here
                if not g_dev['debug'] and self.open_and_enabled_to_observe:
                    if enc_status is not None:
                        if enc_status['shutter_status'] == 'Software Fault':
                            plog("Software Fault Detected. Will alert the authorities!")
                            self.open_and_enabled_to_observe = False
                            self.park_enclosure_and_close()
                            
                        if enc_status['shutter_status'] == 'Closing':
                            plog("Detected Roof Closing.")
                            self.open_and_enabled_to_observe = False
                            self.enclosure_next_open_time = time.time(
                             ) + self.config['roof_open_safety_base_time'] * self.opens_this_evening
    
                        if enc_status['shutter_status'] == 'Error':
                            plog("Detected an Error in the Roof Status. Packing up for safety.")
                            self.open_and_enabled_to_observe = False
                            self.park_enclosure_and_close()
                            self.enclosure_next_open_time = time.time(
                            ) + self.config['roof_open_safety_base_time'] * self.opens_this_evening
                                
                    else:
                        plog("Enclosure roof status probably not reporting correctly. WEMA down?")
    
                # Error / Fault Clear timer.
                # If the ASCOM status is in Error of Software Fault,
                # It generally needs a close command to clear it out.
                # This periodically checks for that and sends a close
                # every now and then to try and clear it. 
                if self.error_fault_clear_timer-time.time() > 120:
                    self.error_fault_clear_timer=time.time()
                    if enc_status['shutter_status'] == 'Software Fault':
                        
                        plog("Software Fault Detected. Will alert the authorities!")
                        self.open_and_enabled_to_observe = False
                        self.park_enclosure_and_close()
                        self.enclosure_next_open_time = time.time(
                        ) + self.config['roof_open_safety_base_time'] * self.opens_this_evening
                         
                    
                    if enc_status['shutter_status'] == 'Error':
                        
                        plog("Detected an Error in the Roof Status. Packing up for safety.")
                        self.open_and_enabled_to_observe = False
                        self.park_enclosure_and_close()
                        self.enclosure_next_open_time = time.time(
                        ) + self.config['roof_open_safety_base_time'] * self.opens_this_evening
                         
    
    
                roof_should_be_shut = False
    
                if g_dev['enc'].mode in ['Shutdown']:
                    roof_should_be_shut = True
                    self.open_and_enabled_to_observe = False
    
                if not (g_dev['events']['Cool Down, Open'] < ephem_now < g_dev['events']['Close and Park']):
                    roof_should_be_shut = True
                    self.open_and_enabled_to_observe = False
                    
                if self.keep_closed_all_night:
                    roof_should_be_shut = True
                    self.open_and_enabled_to_observe = False
                
                
                    
                if enc_status['shutter_status'] == 'Open':
                    if roof_should_be_shut == True and not g_dev['enc'].mode == 'Manual':
                        plog("Safety check notices that the roof was open outside of the normal observing period")
                        self.park_enclosure_and_close()
                    
                    if not (self.local_weather_ok == None) and g_dev['enc'].mode == 'Automatic':
                        if (not self.local_weather_ok and self.local_weather_active):
                            plog("Safety check notices that the local weather is not ok. Shutting the roof.")
                            self.park_enclosure_and_close()
                    
                    if g_dev['enc'].mode == 'Automatic':
                        if (not self.weather_report_open_at_start) and self.owm_active:
                            plog("Safety check notices that the weather report is not ok. Shutting the roof.")
                            self.park_enclosure_and_close()
                    
    
                if enc_status['shutter_status'] == 'Closed' and self.keep_open_all_night and g_dev['enc'].mode in ['Automatic']:
    
                    if time.time() > self.enclosure_next_open_time and self.opens_this_evening < self.config[
                        'maximum_roof_opens_per_evening']:
                        self.nightly_reset_complete = False
                        self.open_enclosure(enc_status, ocn_status)
    
                if (self.enclosure_next_open_time - time.time()) > 0:
                    plog("opens this eve: " + str(self.opens_this_evening))
    
                    plog("minutes until next open attempt ALLOWED: " +
                         str((self.enclosure_next_open_time - time.time()) / 60))
                    
                if (not self.keep_closed_all_night) and ((g_dev['events']['Cool Down, Open'] <= ephem_now < g_dev['events']['Observing Ends']) and (self.keep_open_all_night or self.weather_report_open_at_start==True or not self.owm_active) and \
                    g_dev['enc'].mode == 'Automatic') and (not self.cool_down_latch) and (self.keep_open_all_night or self.local_weather_ok  or (not self.ocn_exists) or (not self.local_weather_active)) and \
                    (not enc_status['shutter_status'] in ['Software Fault', 'Opening', 'Closing', 'Error']):
    
                    self.cool_down_latch = True
    
                    if not self.open_and_enabled_to_observe and (self.weather_report_open_at_start or not self.owm_active): # and (self.weather_report_open_during_evening == False or self.local_weather_always_overrides_OWM):
    
                        if time.time() > self.enclosure_next_open_time and self.opens_this_evening < self.config['maximum_roof_opens_per_evening']:
                            self.nightly_reset_complete = False
                            self.open_enclosure(enc_status, ocn_status)
    
                    self.cool_down_latch = False
    
                # If in post-close and park era of the night, check those two things have happened!
                if (g_dev['events']['Close and Park'] <= ephem_now < g_dev['events']['Nightly Reset']) \
                        and g_dev['enc'].mode == 'Automatic':
    
                    if not any(status in enc_status['shutter_status'].lower() for status in ('closed', 'closing')):
                        plog("Found shutter open after Close and Park, shutting up the shutter")
                        self.park_enclosure_and_close()
    
            
                if (g_dev['events']['Observing Ends'] <= ephem_now < g_dev['events']['Nightly Reset']) \
                        and g_dev['enc'].mode == 'Automatic' and enc_status['shutter_status'] in ['Open', 'open', 'Opening', 'opening']:
                            
                    # Checking roof shouldn't be shut due to local clock hour
                    current_local_time=datetime.datetime.now(self.local_pytz_timezone)
                    current_local_decimal_hour=current_local_time.hour + (current_local_time.minute/60)
                    if current_local_decimal_hour > self.config['absolute_latest_shutting_hour']:
                        plog ("Shutting roof as it is after the absolute latest shutting hour")
                        self.park_enclosure_and_close()            
    
                # If it is in the morning, check whether obs have finished morning flats
                # If finished, close the shutter            
                if ephem_now > g_dev['events']['Naut Dawn']: # Start checking towards Dawn                
                    plog ("Morning Flats Done: " + str(self.morning_flats_finished))
                    if not self.morning_flats_finished:
                        completed=[]
                        for obsid in self.obs_ids:
                            uri_status = f"{PTR_STATUS_ROOT}/{obsid}/obs_settings/"
    
                            
                            try:
                                #plog ("Grabbing obs settings")                            
                                obs_settings=requests.get(uri_status, timeout=20, allow_redirects=False, headers=close_headers, stream=False)
                                #plog ("Grabbed obs settings")
                            except:
                                plog ("Some error in getting the obs_settings")
                                plog(traceback.format_exc())
                                obs_settings='nope'
    
                            if '[200]' in str(obs_settings): # If reading successful
                                obs_settings=obs_settings.json()['status']['obs_settings']
                                if 'morning_flats_done' in obs_settings:
                                    flats_done=obs_settings['morning_flats_done']
                                    plog (str(obsid) + " Flats Done: " + str(flats_done))
                                    last_communication=time.time()-obs_settings['timedottime_of_last_upload']
                                    plog (str(obsid) + " Last Communication: " + str(last_communication))
                                    # If last communication with obs was more than 10 minutes ago
                                    # OR it is reporting flats_done, then it is ready to close
                                    if last_communication > 600 or flats_done:
                                        completed.append(True)
                                    else:
                                        completed.append(False)
                                else:
                                    plog (str(obsid) + " isn't reporting flats done status yet")
                                    completed.append(False)
                            else:
                                # If fail to get status, assume it isn't done.
                                completed.append(False)
                        # If there is a False in completed then it is still waiting, otherwise close up
                        if False in completed:
                            plog ("Still waiting for flats to finish")
                        else:
                            plog ("Flats all done, closing up the shutter")
                            self.park_enclosure_and_close()
                            self.morning_flats_finished=True
            except:
                plog ("Something odd occurred in the safety call")
                plog(traceback.format_exc())
                
                      

    def nightly_reset_script(self, enc_status):
        
        if g_dev['enc'].mode == 'Automatic':
            self.park_enclosure_and_close()
        
        # Set weather report to false because it is daytime anyways.
        self.weather_report_open_at_start=False
        
        #events = g_dev['events']
        obs_win_begin, sunZ88Op, sunZ88Cl, ephem_now = self.astro_events.getSunEvents()

        # Reopening config and resetting all the things.
        self.astro_events.compute_day_directory()
        self.astro_events.calculate_events()
        self.astro_events.display_events()
        
        # sending this up to AWS
        '''
        Send the config to aws.
        '''
        uri = f"{self.config['wema_name']}/config/"
        # self.config['events'] = g_dev['events']
        response = self.api.authenticated_request("PUT", uri, self.config)
        if response:
            plog("Config uploaded successfully.")

        self.cool_down_latch = False
        self.nightly_reset_complete = True
        self.opens_this_evening=0
        
        self.keep_open_all_night = False
        self.keep_closed_all_night   = False          
        self.open_at_specific_utc = False
        self.specific_utc_when_to_open = -1.0  
        self.manual_weather_hold_set = False
        self.manual_weather_hold_duration = -1.0
        
        self.morning_flats_finished=False
        
        return



    def run(self):  # run is a poor name for this function.
        """Runs the continuous WEMA process.

        Loop ends with keyboard interrupt."""
        try:
            while True:
                self.update()  # `Ctrl-C` will exit the program.
                time.sleep(0.5)
        except KeyboardInterrupt:
            plog("Finishing loops and exiting...")
            self.stopped = True
            return

    def send_to_user(self, p_log, p_level="INFO"):
        """ """
        url_log = f"{PTR_LOGS_ROOT}/newlog"
        body = json.dumps(
            {
                "site": self.config["obsp_ids"][0],
                "log_message": str(p_log),
                "log_level": str(p_level),
                "timestamp": time.time(),
            }
        )
        try:
            requests.post(url_log, body, timeout=20, allow_redirects=False, headers=close_headers, stream=False)
        except Exception:
            plog("Log did not send, usually not fatal.")

    def park_enclosure_and_close(self):

        self.open_and_enabled_to_observe = False
        if not g_dev['enc'].dummy:
            g_dev['enc'].close_roof_directly({}, {})
        else:
            g_dev['enc'].dummy_status='Closed'
        
        # If it is a dome, then we need to get the dome parked as well
        # This currently does this. 
        if 'MaxDome' in g_dev['enc'].config['enclosure']['enclosure1']['driver']:
            plog ("Detected Dome. Now waiting for official close command and then Parking the Dome.")
            
            
            closing_timeout_timer=time.time()
            while True:
                enc_status = g_dev['enc'].get_status()
                self.send_enclosure_status(enc_status, [])
                if enc_status['shutter_status'] in ['Closed', 'closed']:
                    break
                elif time.time()-closing_timeout_timer > 300:
                    plog ("Never reported fully Closed! Parking the dome anyway assuming it is mostly shut")
                    break
                else:
                    time.sleep(10)
                    plog ("still waiting for official closed report")
                    
            if self.config['enclosure']['enclosure1']['home_dome_before_parking']:
            
                plog ("Homing Dome")
                try:
                    g_dev['enc'].enclosure.FindHome()
                    enc_status = g_dev['enc'].get_status()
                    self.send_enclosure_status(enc_status, [])
                    home_wait_timeout=time.time()
                    while not g_dev['enc'].enclosure.AtHome and (time.time()-home_wait_timeout < 300):
                        plog ("Waiting for Home")
                        time.sleep(5)
                
                    if g_dev['enc'].enclosure.AtHome:
                        g_dev['enc'].enclosure.SyncToAzimuth(self.config['enclosure']['enclosure1']['dome_home_azimuth']) # If shutter home at 194, then park at 100.
                        plog ("Successfully found Home. Ready to observe")
                    else:
                        plog ("Could not find Home reliably.")
                    
                    enc_status = g_dev['enc'].get_status()
                    self.send_enclosure_status(enc_status, [])
                
                    
                except:
                    plog(traceback.format_exc())
                    plog ("DOME COMMAND GLITCHED OUT.")
                    
            if self.config['enclosure']['enclosure1']['use_park_command_rather_than_slew_to_park']:
                plog ("Parking Dome")
                try:
                    g_dev['enc'].enclosure.Park()
                    enc_status = g_dev['enc'].get_status()
                    self.send_enclosure_status(enc_status, [])
                    park_timeout_timer=time.time()
                    while not g_dev['enc'].enclosure.AtPark and time.time()-park_timeout_timer < 300:
                        plog ("Waiting for Park")
                        time.sleep(5)
                    enc_status = g_dev['enc'].get_status()
                    self.send_enclosure_status(enc_status, [])
                except:
                    plog(traceback.format_exc())
                    plog ("DOME COMMAND GLITCHED OUT.")
            else:
                plog ("Parking Dome")
                try:
                    g_dev['enc'].enclosure.SlewToAzimuth(self.config['enclosure']['enclosure1']['slew_park_azimuth'])
                    enc_status = g_dev['enc'].get_status()
                    self.send_enclosure_status(enc_status, [])
                    park_timeout_timer=time.time()
                    while g_dev['enc'].enclosure.Slewing and time.time()-park_timeout_timer < 300:
                        plog("Waiting for Park")
                        #self.send_enclosure_status(self.enc_status, self.ocn_status)
                        time.sleep(5)
                    enc_status = g_dev['enc'].get_status()
                    self.send_enclosure_status(enc_status, [])
                except:
                    plog(traceback.format_exc())
                    plog ("DOME COMMAND GLITCHED OUT.")
                
            
            plog ("Successfully parked. Ready to go to bed.")
        
        
        return

    def open_enclosure(self, enc_status, ocn_status):   # Unused 10142023 wer, no_sky=False):

        enc_status = g_dev['enc'].get_status()
        ocn_status = g_dev['ocn'].get_status()   #The call to get-status causes s spurious pringout of two Boltood lines, Status is the average
        flat_spot, flat_alt = g_dev['evnt'].flat_spot_now()
        obs_win_begin, sunZ88Op, sunZ88Cl, ephem_now = self.astro_events.getSunEvents()

        if g_dev['enc'].mode in ['Shutdown']:
            plog ("Not OPENING the enclosure. Site in Shutdown mode.")
            return

        if self.keep_closed_all_night and not g_dev['enc'].mode in ['Manual']:
            plog ("Observatory set to be closed all night. Not opening enclosure.")
            return
        
        # Checking roof shouldn't be shut due to local clock hour
        current_local_time=datetime.datetime.now(self.local_pytz_timezone)
        #plog('*******WER MOD At line 1138 in wema*******')
        current_local_decimal_hour=current_local_time.hour + (current_local_time.minute/60)
        if  current_local_decimal_hour < self.config['absolute_earliest_opening_hour']  and not g_dev['enc'].mode in ['Manual'] and ephem_now < g_dev['events']['Naut Dusk']:
            plog ("Not opening roof as it is before the absolute earliest opening hour.")
            return

        # Only send an enclosure open command if the weather
        if (self.weather_report_open_at_start or not self.owm_active or g_dev['enc'].mode == "Manual"):
            #plog('WER debug line 1146 in wema')
            if not g_dev['debug'] and not g_dev['enc'].mode in ['Manual'] and (
                    ephem_now < g_dev['events']['Cool Down, Open']) or \
                    (g_dev['events']['Close and Park'] < ephem_now < g_dev['events']['Nightly Reset']):
                plog("NOT OPENING THE enclosure -- IT IS THE DAYTIME!!")
                return
            else:

                try:

                    plog("Attempting to open the roof.")
                    

                    if ocn_status == None:
                        if not enc_status['shutter_status'] in ['Open', 'open','Opening','opening'] and \
                                g_dev['enc'].mode == 'Automatic' or g_dev['enc'].mode == 'Manual':
                            self.opens_this_evening = self.opens_this_evening + 1

                            if not g_dev['enc'].dummy:
                                g_dev['enc'].open_roof_directly({}, {})
                            else:
                                g_dev['enc'].dummy_status='Open'

                    elif  not enc_status['shutter_status'] in ['Open', 'open','Opening','opening'] and \
                            g_dev['enc'].mode == 'Automatic' \
                            and time.time() > self.enclosure_next_open_time and self.weather_report_open_at_start:#  and self.weather_report_is_acceptable_to_observe:  # NB

                        self.opens_this_evening = self.opens_this_evening + 1

                        if not g_dev['enc'].dummy:
                            g_dev['enc'].open_roof_directly({}, {})
                        else:
                            g_dev['enc'].dummy_status='Open'

                    elif not enc_status['shutter_status'] in ['Open', 'open', 'Opening', 'opening'] and \
                            g_dev['enc'].mode == 'Manual':
                        self.opens_this_evening = self.opens_this_evening + 1

                        if not g_dev['enc'].dummy:
                            g_dev['enc'].open_roof_directly({}, {})
                        else:
                            g_dev['enc'].dummy_status='Open'

                        
                    plog("Attempting to Open Shutter. Waiting until shutter opens")
                    #while True:
                    enc_status = g_dev['enc'].get_status()
                    if not enc_status['shutter_status'] in ['Open', 'open']:
# =============================================================================
                        if not g_dev['enc'].dummy:
                            g_dev['enc'].open_roof_directly({}, {})
                        else:
                            g_dev['enc'].dummy_status='Open'
# =============================================================================
                        time.sleep(self.config['period_of_time_to_wait_for_roof_to_open'])
                   
                    #This is where successive opens get stretched out.
                    self.enclosure_next_open_time = time.time() + (self.config['roof_open_safety_base_time'] * 60) * self.opens_this_evening

                    enc_status = g_dev['enc'].get_status()

                    # If it is a dome, then we need to get the dome setup as well
                    # This currently does this. 
                    if 'MaxDome' in g_dev['enc'].config['enclosure']['enclosure1']['driver']:
                        plog ("Detected Dome. Now waiting for official open command and then Homing the Dome.")
                        
                        
                        
                        open_dome_timer=time.time()
                        while True:
                            enc_status = g_dev['enc'].get_status()
                            if enc_status['shutter_status'] in ['Open', 'open']:
                                break
                            elif (time.time() - open_dome_timer) > 300:
                                plog ("dome open report timed out")
                                plog ("moving on")
                                break
                            else:
                                time.sleep(2)
                                plog ("still waiting for official open report")
                                
                        
                        
                        
                        if self.config['enclosure']['enclosure1']['home_dome_after_opening']:
                        
                            plog ("Homing Dome")
                            try:
                                g_dev['enc'].enclosure.FindHome()
                                enc_status = g_dev['enc'].get_status()
                                self.send_enclosure_status(enc_status, [])
                                home_wait_timeout=time.time()
                                while not g_dev['enc'].enclosure.AtHome  and (time.time()-home_wait_timeout < 300):
                                    plog ("Waiting for Home")
                                    time.sleep(5)
                                enc_status = g_dev['enc'].get_status()
                                self.send_enclosure_status(enc_status, [])
                                
                                g_dev['enc'].enclosure.SyncToAzimuth(self.config['enclosure']['enclosure1']['dome_home_azimuth']) # If shutter home at 194, then park at 100.
                                plog ("Successfully found Home. Ready to observe")
                            except:
                                plog(traceback.format_exc())
                                plog ("DOME COMMAND GLITCHED OUT.")
                                
                    time.sleep(5)
                    
                    enc_status = g_dev['enc'].get_status()
                    
                    plog ("Post dome shutter status:")
                    plog (enc_status)
                        
                    if enc_status['shutter_status'] in ['Open', 'open']:
                        self.open_and_enabled_to_observe = True

                        # try:
                        #     plog("Synchronising dome.")
                        #     g_dev['enc'].sync_mount_command({}, {})
                        # except:
                        #     pass
                        # Prior to skyflats no dome following.
                        # self.dome_homed = False

                        return

                    elif not 'MaxDome' in g_dev['enc'].config['enclosure']['enclosure1']['driver']:
                        
                        plog ("Looks like the roof isn't reporting open yet. Giving it an extra minute.....")
                        time.sleep(60)
                        enc_status = g_dev['enc'].get_status()
                        if enc_status['shutter_status'] in ['Open', 'open']:
                            self.open_and_enabled_to_observe = True
                        else:
                        
                            plog("Failed to open roof. Sending the close command to the roof.")
                            plog("opens this eve: " + str(self.opens_this_evening))
                            plog("minutes until next open attempt ALLOWED: " + str(
                                (self.enclosure_next_open_time - time.time()) / 60))
                            if not g_dev['enc'].dummy:
                                g_dev['enc'].close_roof_directly({}, {})
                            else:
                                g_dev['enc'].dummy_status='Closed'

                        return
                    else:
                        plog ("Skipping dome failure mode.... it was going to say failed to open .... but it usually isn't... need to find out what that is.")
                        return
                    
                except Exception as e:
                    plog("Enclosure opening glitched out: ", e)
                    plog(traceback.format_exc())

        else:
            plog("An enclosure command was rejected because the weather report was not acceptable.")

        return

    def run_nightly_weather_report(self,enc_status=None, ocn_status=None):
       
        events = g_dev['events']

        obs_win_begin, sunset, sunrise, ephem_now = self.astro_events.getSunEvents()
        print (ocn_status)
        # First thing to do at the Cool Down, Open time is to calculate the quality of the evening
        # using the broad weather report.
        try:
            try:
                plog("Appraising quality of evening from Open Weather Map.")
                
               
                
                # One Call 4.0 splits current conditions and the hourly timeline
                # across two endpoints. 3.0 served both from one URL but needs a
                # separate One Call by Call subscription, and answers 401 without it.
                params = {
                    "lat": self.latitude,
                    "lon": self.longitude,
                    "appid": self.owm_api_key,
                    "units": "metric"
                }

                params["exclude"] = "minutely,alerts"
                response = requests.get(
                    "https://api.openweathermap.org/data/3.0/onecall", params=params, timeout=30)
                data = response.json()
    
                self.weather_report_run_timer = time.time()
                
                # Keep this for weather stations that do not have current humidity
                self.current_owm_humidity=data['current']['humidity']
                self.current_owm_ambient_temperature=data['current']['temp']
                self.current_owm_dewpoint=data['current']['dew_point']
                
            
                # Collect relevant info for fitzgerald weather number calculation
                hourcounter=0
                fitzgerald_weather_number_grid=[]
                hours_until_end_of_observing= math.ceil((events['Close and Park'] - ephem_now) * 24)
                hours_until_start_of_observing= math.ceil((events['Cool Down, Open'] - ephem_now) * 24)
                if hours_until_start_of_observing < 0:
                    hours_until_start_of_observing = 0
                plog("Hours until end of observing: " + str(hours_until_end_of_observing))
                
                # The table covers the operational window and nothing else.
                # OpenWeather returns 48 hours; publishing all of them buries
                # the night the site is actually deciding about among two days
                # of irrelevance.
                #
                # The start floors to the hour and the end ceils to it, so a
                # window of 19:12 to 05:48 yields 19:00 through 06:00. The
                # partial hours at each end are inside the window and their
                # weather counts; truncating them would drop the hour the roof
                # opens and the hour it closes.
                def _hour_floor_unix(when):
                    moment = ephem.Date(when).datetime().replace(
                        minute=0, second=0, microsecond=0)
                    return calendar.timegm(moment.timetuple())

                def _hour_ceil_unix(when):
                    moment = ephem.Date(when).datetime()
                    floored = moment.replace(minute=0, second=0, microsecond=0)
                    if moment > floored:
                        floored = floored + datetime.timedelta(hours=1)
                    return calendar.timegm(floored.timetuple())

                window_start_unix = _hour_floor_unix(events['Operational Window Start'])
                window_end_unix = _hour_ceil_unix(events['Operational Window Closes'])

                hourly_in_window = [
                    entry for entry in data['hourly']
                    if window_start_unix <= entry['dt'] <= window_end_unix
                ]
                if not hourly_in_window:
                    # A window further out than OpenWeather's 48 hours, which
                    # happens when the site is closed for a long daytime. An
                    # empty table would read as "no forecast" rather than "not
                    # yet forecast", so the whole timeline goes out instead.
                    plog("Forecast: no hourly entry falls inside the operational "
                         "window (%s to %s UTC); publishing the full timeline."
                         % (datetime.datetime.utcfromtimestamp(window_start_unix).isoformat(),
                            datetime.datetime.utcfromtimestamp(window_end_unix).isoformat()))
                    hourly_in_window = data['hourly']
                else:
                    plog("Forecast: %d hours covering the operational window, %s to %s UTC."
                         % (len(hourly_in_window),
                            datetime.datetime.utcfromtimestamp(window_start_unix).isoformat(),
                            datetime.datetime.utcfromtimestamp(window_end_unix).isoformat()))

                OWM_status_json={}
                OWM_status_json["timestamp"] = round(time.time(), 1)
                for hourly_report in hourly_in_window:
                    
                    dt = datetime.datetime.utcfromtimestamp(hourly_report['dt'])  # or .fromtimestamp() for local time
                    iso_time = dt.isoformat()  # '2025-05-08T07:00:00'
                    clock_hour = iso_time.split('T')[1].split(':')[0]

                    # The same instant at the site. A forecast row is read by
                    # someone deciding whether to observe tonight, and "is 03:00
                    # UTC before or after my sunrise" is a subtraction nobody
                    # should be doing in their head -- least of all at ECO,
                    # where the local date is not even the same one.
                    local_clock_hour = datetime.datetime.fromtimestamp(
                        hourly_report['dt'], self.local_pytz_timezone).strftime('%H')
                    
                    tempFn = fitzgerald_number(
                        hourly_report['humidity'], hourly_report['clouds'],
                        hourly_report['wind_speed'],
                        hourly_report['weather'][0]['description'], hourly_report['pop'])

                    weatherline=[ hourly_report['humidity'], hourly_report['clouds'],hourly_report['wind_speed'],hourly_report['weather'][0]['main'], hourly_report['weather'][0]['description'], clock_hour, tempFn, iso_time,  hourly_report['temp'], hourly_report['pop'], local_clock_hour] # Last one meant to be rain but it has s
                    fitzgerald_weather_number_grid.append(weatherline)
    
                    hourcounter=hourcounter + 1
    
    
                forecast_status=[]
                for weatherline in fitzgerald_weather_number_grid:
    
                    status_line={}
                    status_line['humidity']=weatherline[0]
                    status_line['cloud_cover'] = weatherline[1]
                    status_line['wind_speed'] = weatherline[2]
                    status_line['short_text'] = weatherline[3]
                    status_line['long_text'] = weatherline[4]
                    status_line['utc_clock_hour'] = weatherline[5]
                    # Beside the UTC hour, deliberately: same instant, site clock.
                    status_line['local_clock_hour'] = weatherline[10]
                    status_line['fitz_number'] = weatherline[6]
                    status_line['utc_long_form'] = weatherline[7].replace(' ','T').split('+')[0]+'Z'
                    status_line['temperature'] = weatherline[8]
                    status_line['rain'] = weatherline[9]
    
                    status_line['weather_quality_number'] = weather_quality_number(weatherline[6])
    
                    forecast_status.append(status_line)
                    
                    
                if forecast_status is not None:
                    lane = "forecast"
                    obsy = self.config['wema_name']
                    url = f"{PTR_STATUS_ROOT}/{obsy}/status"
    
                    payload = json.dumps({
                        "statusType": "forecast",
                        "status": { "forecast": forecast_status }
                    })
# =======
#                     hourly_fitzgerald_number.append(entry[6])
#                     hourly_fitzgerald_number_by_hour.append([entry[5],entry[6],textdescription])
#                 hourcounter=hourcounter+1
            
#             plog ("Hourly Fitzgerald number report")
#             self.hourly_report_holder.append("Hourly Fitzgerald number report")
            
#             plog ("For Evening of " +str(g_dev['dayhyphened']) )
#             self.hourly_report_holder.append("For LOCAL Evening of " +str(g_dev['dayhyphened']) )
            
#             plog("Time of OWM Weather Forecast: " + str(time.asctime()))
#             self.hourly_report_holder.append("Time ofOWM  Weather Forecast (UTC): " + str(time.asctime()))
            
#             plog ("*******************************")
#             self.hourly_report_holder.append("*******************************")
#             plog ("Hour(UTC) |  FNumber |  Text    ")
#             self.hourly_report_holder.append("Hour(UTC) |  FNumber |  Text    ")
#             for line in hourly_fitzgerald_number_by_hour:
#                 plog (str(line[0]) + '         | '+ str(line[1]) + '        | ' + str(line[2]))
#                 self.hourly_report_holder.append(str(line[0]) + '         | '+ str(line[1]) + '        | ' + str(line[2]))
            
#             plog ("Night's total fitzgerald number: " + str(sum(hourly_fitzgerald_number)))
            
# >>>>>>> Stashed changes

                    try:
                        response = requests.request("POST", url, data=payload, allow_redirects=False, headers=close_headers, stream=False)
                    except:
                        plog ("Connection glitch on the forecast request")

                # The daily forecast, for the days the hourly series cannot
                # reach. One Call answers with eight days beside its forty-eight
                # hours, so the week ahead costs no extra request -- it was in
                # the response all along and simply went unread.
                daily_status = []
                for day in data.get('daily', []):
                    try:
                        weather = day['weather'][0]
                        day_time = datetime.datetime.utcfromtimestamp(day['dt'])
                        fitz = fitzgerald_number(
                            day['humidity'], day['clouds'], day['wind_speed'],
                            weather['description'], day.get('pop', 0))
                        daily_status.append({
                            'date': day_time.strftime('%Y-%m-%d'),
                            'utc_long_form': day_time.isoformat() + 'Z',
                            'humidity': day['humidity'],
                            'cloud_cover': day['clouds'],
                            'wind_speed': day['wind_speed'],
                            'short_text': weather['main'],
                            'long_text': weather['description'],
                            'summary': day.get('summary'),
                            'temperature_min': day['temp']['min'],
                            'temperature_max': day['temp']['max'],
                            'rain': day.get('pop', 0),
                            'moon_phase': day.get('moon_phase'),
                            'fitz_number': fitz,
                            'weather_quality_number': weather_quality_number(fitz),
                        })
                    except (KeyError, IndexError, TypeError):
                        # A malformed day costs that day, not the whole series.
                        plog('Skipping a malformed day in the OWM daily forecast')

                if daily_status:
                    daily_url = f"{PTR_STATUS_ROOT}/{self.config['wema_name']}/status"
                    daily_payload = json.dumps({
                        "statusType": "forecast_daily",
                        "status": {"forecast_daily": daily_status}
                    })
                    try:
                        requests.request("POST", daily_url, data=daily_payload,
                                         allow_redirects=False, headers=close_headers, stream=False)
                        plog("Daily forecast sent: " + str(len(daily_status)) + " days.")
                    except:
                        plog("Connection glitch on the daily forecast request")

                # Fitzgerald weather number calculation.
                hourly_fitzgerald_number=[]
                hourly_fitzgerald_number_by_hour=[]
                hourcounter = 0
                self.hourly_report_rows=[]
                # No hourcounter filter any more: the grid is already exactly the
                # operational window, floored and ceiled to the hour where it is
                # built. Counting index positions against math.ceil() of the
                # hours remaining assumed the first entry sat on the current
                # hour, which drifts through the night, and would now filter a
                # second time on top of the window.
                for entry in fitzgerald_weather_number_grid:
                    fitz = entry[6]
                    hourly_fitzgerald_number.append(fitz)
                    hourly_fitzgerald_number_by_hour.append([entry[5], fitz])
                    # The hour as a record. Presentation is the consumer's.
                    self.hourly_report_rows.append({
                        'hour_utc': entry[5],
                        # The same instant on the site's clock, beside the UTC
                        # hour rather than left as a subtraction for the reader.
                        'hour_local': entry[10],
                        'iso_time': entry[7],
                        'fitzgerald_number': fitz,
                        'condition': entry[3],
                        'description': entry[4],
                        'cloud_pct': entry[1],
                        'humidity_pct': entry[0],
                        'wind_ms': entry[2],
                        'temperature_c': entry[8],
                        'rain_probability_pct': float(entry[9]) * 100,
                        # Per hour, against the same threshold hours_bad_or_good
                        # uses below, so the column and the decision cannot
                        # disagree. Amended once open_at_start is known.
                        'roof_plan': 'stay_closed' if fitz > 41 else 'open',
                    })
                    hourcounter=hourcounter+1
                
                utc_string = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                plog("Weather forecast for the local evening of " + str(g_dev['dayhyphened'])
                     + ", retrieved " + str(utc_string) + " UTC, covering "
                     + str(len(hourly_fitzgerald_number_by_hour)) + " hours.")

                
                plog ("Night's total fitzgerald number: " + str(sum(hourly_fitzgerald_number)))
                
    
                self.night_fitzgerald_number = sum(hourly_fitzgerald_number)
                if len(hourly_fitzgerald_number) >= 1:
                    average_fitzn_for_rest_of_night = sum(hourly_fitzgerald_number) / len(hourly_fitzgerald_number)
                else:
                    average_fitzn_for_rest_of_night = 100
                
                plog("Night's average fitzgerald number: " + str(average_fitzn_for_rest_of_night))
                
                # Simplified decision array
                hours_bad_or_good=[]
                for entry in hourly_fitzgerald_number_by_hour:
                    if entry[1] > 41:
                        hours_bad_or_good.append([entry[0],0])
                    else:
                        hours_bad_or_good.append([entry[0],1])
    
               
                # If the first three hours are good, then open from the start
                self.weather_report_open_at_start = False
                try:
                    if (hours_bad_or_good[0][1] + hours_bad_or_good[1][1] +hours_bad_or_good[2][1] ) == 3:
                        plog("Looks like it is clear enough to open the observatory from the beginning.")
                        self.weather_report_open_at_start = True
                    elif (hours_bad_or_good[0][1]) == 0 and g_dev['enc'].mode == 'Automatic' and not \
                    'closed' in enc_status['shutter_status'].lower() and self.owm_active:
                        plog("Looks like the weather gets rough in the first hour, shutting up observatory.")
                        self.park_enclosure_and_close()
                except:
                    plog (plog(traceback.format_exc()))
                    plog (hours_bad_or_good)
                    plog ("Probably that there isn't actually three elements in the list?")
                    plog (len(hours_bad_or_good))

                # The opening rule is about the first three hours together, not
                # each hour on its own, so a good first hour still means a shut
                # roof when the two after it are bad. Say that in the column
                # rather than in a sentence under the table: a reader looking at
                # 19:00 should see what the roof will do at 19:00.
                if not self.weather_report_open_at_start:
                    for row in self.hourly_report_rows[:3]:
                        row['roof_plan'] = 'stay_closed'
    
                
    
                # Look for three hour gaps in the weather throughout the night
                self.times_to_open=[]
                self.times_to_close=[]
                for counter in range(len(hours_bad_or_good)):
                    
                    # A three hour gap after a bad hour is a good time to open.
                    
                    if (counter - len(hours_bad_or_good)) == -1:                   
                        pass
                    elif (counter - len(hours_bad_or_good)) == -2:
                        sum_of_next_three_hours=int((hours_bad_or_good[counter][1]+hours_bad_or_good[counter+1][1])*1.5)
                    else:
                        sum_of_next_three_hours = hours_bad_or_good[counter][1] + hours_bad_or_good[counter + 1][1] + \
                                              hours_bad_or_good[counter + 2][1]
    
                    if sum_of_next_three_hours == 3 and hours_bad_or_good[counter-1][1] == 0:
                        plog ("good time to open")
                        self.times_to_open.append([hours_bad_or_good[counter][0]])
    
                    # Simply a bad hour is a good time to close.
                    if len(hours_bad_or_good) == counter + 1:                    
                        pass
                    elif hours_bad_or_good[counter][1] == 1 and hours_bad_or_good[counter+1][1] == 0:
                        plog ("good time to close")
                        self.times_to_close.append([hours_bad_or_good[counter][0]])
    
    
                # The report, as data. Hours the roof would open or
                # close are marked on the hour they apply to, rather than
                # spliced in as extra lines.
                open_hours = set()
                close_hours = set()
                for entry in self.times_to_open:
                    try:
                        open_hours.add(int(entry[0]))
                    except (TypeError, ValueError):
                        pass
                for entry in self.times_to_close:
                    try:
                        close_hours.add(int(entry[0]))
                    except (TypeError, ValueError):
                        pass
                for row in self.hourly_report_rows:
                    try:
                        hour = int(float(row['hour_utc']))
                    except (TypeError, ValueError):
                        continue
                    # These are transitions, and the rest of the column is
                    # state, so they say so: an hour that reads "Opens" is the
                    # hour it happens, and the hours after it read "Open". Two
                    # meanings in one column -- a transition on some rows and a
                    # state on others -- is worse than either alone.
                    if hour in open_hours:
                        row['roof_plan'] = 'opens'
                    elif hour in close_hours:
                        row['roof_plan'] = 'closes'

                self.owm_report_payload = {
                    'schema': 1,
                    'generated_utc': utc_string,
                    'local_evening': str(g_dev['dayhyphened']),
                    'night_fitzgerald_number': self.night_fitzgerald_number,
                    'open_at_start': bool(self.weather_report_open_at_start),
                    'cool_down_open': bool(g_dev['events']['Cool Down, Open'] > ephem_now),
                    'close_and_park': bool(g_dev['events']['Close and Park'] > ephem_now),
                    'hours': self.hourly_report_rows,
                }
    
                status = {}
                status['owm_report'] = json.dumps(self.owm_report_payload)
                lane = "owm_report"
                
                
                plog ("OWM current clouds: " + str(data['current']['clouds']))
                self.owm_cloud_cover=data['current']['clouds']
                self.owm_cloud_cover_next_hour=data['hourly'][1]['clouds']
                self.owm_current_temp=data['current']['temp']
                self.owm_current_dewpoint=data['current']['dew_point']
                self.owm_current_humidity=data['current']['humidity']
                
            except:
                plog('Something happened in the OWM weather report area.')
                plog(traceback.format_exc())
                self.owm_cloud_cover=None
                self.owm_cloud_cover_next_hour=None
                self.owm_current_temp=None
                self.owm_current_dewpoint=None
                self.owm_current_humidity=None

            try:
                status = {}
                status['owm_report'] = json.dumps(self.owm_report_payload)
                lane = "owm_report"
                send_status(self.config['wema_name'], lane, status)
            except:
                plog('could not send owm_report status')
                plog(traceback.format_exc())


            # Output to the log the various interesting things about the weather
            # Which will be used at some stage to calibrate the weather station
            # BUT ONLY IF THERE IS ACTUALLY A WEATHER STATION! although we will
            # still collect non-weather station stuff.....
            
            
            line_of_weather_info=[]
            line_of_weather_info.append(str(datetime.datetime.now()))
            line_of_weather_info.append(time.time())
            # Current cloud % from weather forecast
            line_of_weather_info.append(self.owm_cloud_cover)
            

            
            # Reported cloud_cover
            
            if self.ocn_exists:
                try:
                    line_of_weather_info.append(self.predicted_clouds[0])
                except:
                    line_of_weather_info.append(None)
                    plog ("using none rather than predicted clouds for weatherline")
            else:
                line_of_weather_info.append(None)
                
            # Current humidity
            if self.ocn_exists:
                if ocn_status['humidity_%'] == -1:
                    line_of_weather_info.append(data['current']['humidity'])
                else:
                    line_of_weather_info.append(ocn_status['humidity_%'])
            else:
                line_of_weather_info.append(ocn_status['humidity_%'])
            
            
            if self.ocn_exists:
            
                # Measured sky_temp
                line_of_weather_info.append(ocn_status['sky_temp_C'])
            
                # Measured temp
                line_of_weather_info.append(ocn_status['temperature_C'])
                
                # Dewpoint
                if ocn_status['dewpoint_C'] == 100:
                    line_of_weather_info.append(self.owm_current_dewpoint)
                else:
                    line_of_weather_info.append(ocn_status['dewpoint_C'])

                # Rain Rate
                line_of_weather_info.append(ocn_status['rain_rate'])
                
                # Wind Speed
                line_of_weather_info.append(ocn_status['wind_m/s']) 
                        
            else:
                # Measured sky_temp
                line_of_weather_info.append(None)
            
                # Measured temp
                line_of_weather_info.append(None)
                
                # Dewpoint
                line_of_weather_info.append(self.owm_current_dewpoint)
                
                # Rain Rate
                line_of_weather_info.append(None)
                
                # Wind Speed
                line_of_weather_info.append(None)
                        
            
            
            # OWM temperature - can be more reliable than weather station
            line_of_weather_info.append(self.owm_current_temp)
            
        
            
            # Define the API endpoint and parameters
            url = "https://api.open-meteo.com/v1/forecast"
            params = {
                'latitude': self.latitude,  # Melbourne latitude
                'longitude': self.longitude,  # Melbourne longitude
                'hourly': 'cloudcover',  # Request cloud cover data
                'timezone': 'UTC'
            }
            
            # Send GET request
            try:
                response = requests.get(url, params=params)
            
                if response.status_code == 200:
                    data = response.json()
            
                    if 'hourly' in data and 'cloudcover' in data['hourly']:
                        time_list = [
                            datetime.datetime.fromisoformat(t).replace(tzinfo=timezone.utc)
                            for t in data['hourly']['time']
                        ]
                        cloud_list = data['hourly']['cloudcover']
            
                        # Get the current UTC time rounded down to the nearest hour
                        now = datetime.datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)                        
            
                        # Find exact index for the current hour if available
                        if now in time_list:
                            index_now = time_list.index(now)
                        else:
                            # Fallback: Find first forecast time that is >= now
                            future_times = [t for t in time_list if t >= now]
                            if not future_times:
                                plog("No future hourly data available.")
                                self.open_meteo_cloud_cover = None
                                self.open_meteo_cloud_cover_next_hour = None
                                return
            
                            closest_time = min(future_times, key=lambda x: x - now)
                            index_now = time_list.index(closest_time)
            
                        # Assign current cloud cover safely
                        cloud_now = cloud_list[index_now]
                        self.open_meteo_cloud_cover = cloud_now if cloud_now is not None else None
                        plog(f"Open Meteo Current Estimated Cloud Cover ({time_list[index_now]}): {self.open_meteo_cloud_cover}%")
                        line_of_weather_info.append(self.open_meteo_cloud_cover)
            
                        # Assign next hour's cloud cover safely
                        if index_now + 1 < len(cloud_list):
                            cloud_next = cloud_list[index_now + 1]
                            self.open_meteo_cloud_cover_next_hour = cloud_next if cloud_next is not None else None
                            plog(f"Open Meteo Cloud Cover for Next Hour ({time_list[index_now + 1]}): {self.open_meteo_cloud_cover_next_hour}%")
                        else:
                            self.open_meteo_cloud_cover_next_hour = None
                            plog("No cloud cover data available for the next hour.")
            
                    else:
                        plog("Hourly cloud cover data not available in response.")
                        self.open_meteo_cloud_cover = None
                        self.open_meteo_cloud_cover_next_hour = None
            
                else:
                    plog(f"Error: {response.status_code}, {response.text}")
                    self.open_meteo_cloud_cover = None
                    self.open_meteo_cloud_cover_next_hour = None
            
            except Exception as e:
                plog(f"An error occurred: {str(e)}")
                self.open_meteo_cloud_cover = None
                self.open_meteo_cloud_cover_next_hour = None

            
            
            API_KEY = self.tomorrowio_APIkey
            latitude = self.latitude
            longitude = self.longitude
            
            # Tomorrow.io API URL
            url = "https://api.tomorrow.io/v4/timelines"
            
            # Define the fields you want to retrieve
            fields = ["cloudCover"]
            
            # Define the time frame for the data you want to retrieve (now and 1 hour later)
            start_time = datetime.datetime.utcnow().isoformat() + "Z"
            end_time = (datetime.datetime.utcnow() + datetime.timedelta(hours=1)).isoformat() + "Z"
            
            # Define the request payload
            params = {
                "apikey": API_KEY,
                "location": f"{latitude},{longitude}",
                "fields": ",".join(fields),
                "timesteps": "current,1h",
                "startTime": start_time,
                "endTime": end_time,
                "units": "metric"
            }
            
            try:
                # Make the API request
                response = requests.get(url, params=params)
                
                # Check if the request was successful
                if response.status_code == 200:
                    data = response.json()
                    timelines = data.get("data", {}).get("timelines", [])
                
                    self.tomorrowio_cloud_now=timelines[1]['intervals'][0]['values']['cloudCover']
                    self.tomorrowio_cloud_inanhour=timelines[0]['intervals'][1]['values']['cloudCover']
                                
                else:
                    plog(f"Error: {response.status_code}, {response.text}")
                    self.tomorrowio_cloud_now=None
                    self.tomorrowio_cloud_inanhour=None
                    
                plog("TomorrowIO Now: " +str(self.tomorrowio_cloud_now))
                plog("TomorrowIO Next Hour: " +str(self.tomorrowio_cloud_inanhour))
            except:
                plog ("failed to write weatherlog")
                plog(traceback.format_exc())
                self.tomorrowio_cloud_now=None
                self.tomorrowio_cloud_inanhour=None
            

            try:
                # NOTE: don't for get to set "apikey" env, or the default below.
                resp = requests.post(
                    "https://forecast-v2.metoceanapi.com/point/time",
                    headers={"x-api-key": self.metocean_apikey},
                    json={
                        "points": [{
                            "lon": self.longitude,
                            "lat": self.latitude
                        }],
                        "variables": [
                            "cloud.cover"
                        ],
                        "time": {
                            "from": "{:%Y-%m-%dT%H:%M:00Z}".format(datetime.datetime.now(timezone.utc)),
                            "interval": "1h",
                            "repeat": 1
                        }
                    }
                )
    
                        
                self.metocean_clouds_now=resp.json()['variables']['cloud.cover']['data'][0]
                self.metocean_clouds_inanhour=resp.json()['variables']['cloud.cover']['data'][1]
            except:
                self.metocean_clouds_now=None
                self.metocean_clouds_inanhour=None
                
                
                
            # PIRATE API
            try:
                API_KEY = self.pirateapi_key
            
                # Fetch data from Pirate Weather API
                url = f"https://api.pirateweather.net/forecast/{API_KEY}/{self.latitude},{self.longitude}?units=si"
                response = requests.get(url)
                data = response.json()
            
                # Get current cloud cover
                #current_cloud_cover = data['currently']['cloudCover'] * 100  # percentage
            
                # Get cloud cover forecasted an hour from now
                hourly_data = data['hourly']['data']
                current_hour_cloud_cover = hourly_data[0]['cloudCover'] * 100
                next_hour_cloud_cover = hourly_data[1]['cloudCover'] * 100  # Assuming 1-hour intervals
            
                self.pirate_clouds_now = current_hour_cloud_cover
                self.pirate_clouds_inanhour = next_hour_cloud_cover
            except:
                self.pirate_clouds_now = None
                self.pirate_clouds_inanhour = None
                
                
            # WORLDWEATHER API
            try:
            
                params = {
                    'key': self.worldweather_key,
                    'q': f'{self.latitude},{self.longitude}',
                    'format': 'json',
                    'num_of_days': 1,
                    'tp': 1  # Hourly intervals
                }
            
                response = requests.get("https://api.worldweatheronline.com/premium/v1/weather.ashx", params=params)
                data = response.json()
                        
                # Extract hourly data
                hourly_data = data['data']['weather'][0]['hourly']
                
                current_cloud = hourly_data[0]['cloudcover']
                next_hour_cloud = hourly_data[1]['cloudcover']
            
                plog(f"WorldWeather Current Cloud Cover: {current_cloud}%")
                plog(f"WorldWeather Next Hour Cloud Cover: {next_hour_cloud}%")
                
                self.worldweather_current_cloud = float(current_cloud)
                self.worldweather_nexthour_cloud = float(next_hour_cloud)
            except:
                self.worldweather_current_cloud = None
                self.worldweather_nexthour_cloud = None
            
                        
            try:
                #self.medianforecast_current_cloud_cover= np.median(np.asarray([self.owm_cloud_cover,self.open_meteo_cloud_cover,self.owm_cloud_cover_next_hour,self.open_meteo_cloud_cover_next_hour,self.tomorrowio_cloud_now,self.tomorrowio_cloud_inanhour, self.pirate_clouds_now ,self.pirate_clouds_inanhour ,self.metocean_clouds_now, self.metocean_clouds_inanhour, self.worldweather_current_cloud, self.worldweather_nexthour_cloud]))
            
                cloud_values = [
                    self.owm_cloud_cover, self.open_meteo_cloud_cover, self.owm_cloud_cover_next_hour,
                    self.open_meteo_cloud_cover_next_hour, self.tomorrowio_cloud_now, self.tomorrowio_cloud_inanhour,
                    self.pirate_clouds_now, self.pirate_clouds_inanhour, self.metocean_clouds_now,
                    self.metocean_clouds_inanhour, self.worldweather_current_cloud, self.worldweather_nexthour_cloud
                ]
                filtered_values = [v for v in cloud_values if v is not None]
                
                if filtered_values:
                    self.medianforecast_current_cloud_cover = np.median(filtered_values)
                else:
                    self.medianforecast_current_cloud_cover = None  
            
            except:                
                plog ("SOME PROBLEM IN THE MEDIAN CLOUD COVER THING")
                self.medianforecast_current_cloud_cover=None
            
            
            line_of_weather_info.append(self.medianforecast_current_cloud_cover)

            # Next hours
            line_of_weather_info.append(self.open_meteo_cloud_cover_next_hour)
            line_of_weather_info.append(self.owm_cloud_cover_next_hour)
           
            sun_altitude, moon_altitude, moon_illumination, flux_ground, sun_azimuth = self.get_sun_and_moon_info()
        
            # Put in relevant sun and moon potential effects
            line_of_weather_info.append(sun_altitude / u.deg)
            line_of_weather_info.append(moon_altitude/ u.deg)
            line_of_weather_info.append(moon_illumination)
            line_of_weather_info.append(flux_ground)
            line_of_weather_info.append(sun_azimuth / u.deg)
            line_of_weather_info.append(self.tomorrowio_cloud_now)
            line_of_weather_info.append(self.tomorrowio_cloud_inanhour)            
            
            line_of_weather_info.append(self.pirate_clouds_now) 
            line_of_weather_info.append(self.pirate_clouds_inanhour)
            line_of_weather_info.append(self.metocean_clouds_now)
            line_of_weather_info.append(self.metocean_clouds_inanhour)
            line_of_weather_info.append(self.worldweather_current_cloud)
            line_of_weather_info.append(self.worldweather_nexthour_cloud)
            
            
            obs_properties_dict={}
            
            for obsid in self.obs_ids:
                uri_status = f"{PTR_STATUS_ROOT}/{obsid}/device"

                
                try:
                    #plog ("Grabbing obs settings")                            
                    obs_status=requests.get(uri_status, timeout=20, allow_redirects=False, headers=close_headers, stream=False)
                    #plog ("Grabbed obs settings")
                except:
                    plog ("Some error in getting the obs_settings")
                    plog(traceback.format_exc())
                    obs_status=None

                if '[200]' in str(obs_status): # If reading successful
                    last_status_time=obs_status.json()['server_timestamp_ms']/1000
                    try:
                        if time.time() - last_status_time < 600:
                            # Get focuser temperatuer
                        
                            focuser_status=obs_status.json()['status']['focuser']
                            focuser_status=focuser_status[next(iter(focuser_status))] # first focuser
                            focuser_temperature= focuser_status['focus_temperature']['val']
                            
                            current_fwhm_seeing=obs_status.json()['status']['current_fwhm_seeing']
                            try:
                                estimated_sky_transmissiveness= obs_status.json()['status']['estimated_sky_transmissiveness']
                                #estimated_sky_transmissiveness_filter= obs_status.json()['status']['estimated_sky_transmissiveness_filter']
                            except:
                                plog(traceback.format_exc())
                                estimated_sky_transmissiveness=None
                                #estimated_sky_transmissiveness_filter=None
                        
                        else:
                            focuser_temperature=None
                            current_fwhm_seeing=None
                            estimated_sky_transmissiveness=None
                            #estimated_sky_transmissiveness_filter=None
                    except:
                        plog ("Some error in getting the obs status keys")
                        focuser_temperature=None
                        current_fwhm_seeing=None
                        estimated_sky_transmissiveness=None
                        #estimated_sky_transmissiveness_filter=None
                        plog(traceback.format_exc())
                else:
                    plog ("not successful obs status reading")
                    focuser_temperature=None
                    current_fwhm_seeing=None
                    estimated_sky_transmissiveness=None
                    #estimated_sky_transmissiveness_filter=None
                    plog (obs_status)
                
                obs_properties_dict[obsid]={}
                obs_properties_dict[obsid]['focuser_temperature']=focuser_temperature
                obs_properties_dict[obsid]['current_fwhm_seeing']=current_fwhm_seeing
                obs_properties_dict[obsid]['estimated_sky_transmissiveness']=estimated_sky_transmissiveness
                #obs_properties_dict[obsid]['estimated_sky_transmissiveness_filter']= estimated_sky_transmissiveness_filter
            
            
            
            line_of_weather_info.append(json.dumps(obs_properties_dict))

            #breakpoint()
            
            
            
            
            
            if self.config['send_hourly_cloud_forecast_emails']:
                # Your cPanel email credentials
                smtp_server = self.smtp_server
                port = self.smtp_port  # For SSL
                sender_email = self.sender_email
                password = self.email_password
                
                           
                # Receiver
                receiver_emails = self.weather_to_emails.replace(' ','').split(',')
                
                for receiver_email in receiver_emails:
                
                    # Create the email
                    message = MIMEMultipart()
                    message['From'] = sender_email
                    message['To'] = receiver_email
                    message['Subject'] = self.name + ' Cloud Report'
                    
                    body = 'Hello, the clouds are now (hopefully): ' + str(self.medianforecast_current_cloud_cover) +'\n'
                    
                    body = body +"OWM cloud cover: " +str(self.owm_cloud_cover) +'\n'
                    body = body +"Open Meteo cloud cover: " +str(self.open_meteo_cloud_cover)+'\n'    
                    body = body +"Metocean Now: " +str(self.metocean_clouds_now)+'\n'
                    body = body +"Pirate Now: " +str(self.pirate_clouds_now)+'\n'
                    body = body +"WorldWeather Now: " +str(self.worldweather_current_cloud)+'\n'
                    body = body +"TomorrowIO Now: " +str(self.tomorrowio_cloud_now)+'\n\n'
                    body = body +"OWM Next Hour: " +str(self.owm_cloud_cover_next_hour)+'\n'
                    body = body +"Open Meteo Next Hour: " +str(self.open_meteo_cloud_cover_next_hour)+'\n'
                    body = body +"TomorrowIO Next Hour: " +str(self.tomorrowio_cloud_inanhour)+'\n'
                    
                    body = body +"WorldWeather Next Hour: " +str(self.worldweather_nexthour_cloud)+'\n'
                    body = body +"Metocean Next Hour: " +str(self.metocean_clouds_inanhour)+'\n'
                    body = body +"Pirate Next Hour: " +str(self.pirate_clouds_inanhour)+'\n'
                    
        
                    message.attach(MIMEText(body, 'plain'))
                    
                    # Send the email
                    try:
                        with smtplib.SMTP_SSL(smtp_server, port) as server:
                            server.login(sender_email, password)
                            server.sendmail(sender_email, receiver_email, message.as_string())
                        plog("Email sent successfully!")
                    except Exception as e:
                        plog(f"Error sending email: {e}")

            
            print (line_of_weather_info)
            
            column_names = ['date','time','OWM_clouds','Local_clouds','Humidity','sky_temp_C','local_temperature_C', 'dewpoint', 'rain_rate','wind_m/s', 'OWM_temperature','openmeteo_clouds', 'avg_forecast_cloudcover', 'OWMClouds_inanhour', 'openmeteoclouds_inanhour','sun_altitude','moon_altitude','moon_illumination','moon_flux_on_ground', 'sun_azimuth', 'tomorrowio_nowclouds','tomorrowio_nexthourclouds','pirate_clouds_now','pirate_clouds_inanhour','metocean_clouds_now','metocean_clouds_inanhour','worldweather_clouds_now','worldweather_clouds_inanhour','obs_dict']
            

            # Open the file in append mode and write the line
            if not self.medianforecast_current_cloud_cover == None:
                try:
                    
                    if not os.path.exists(self.wema_path+self.name + '_weatherlog.csv'):
                        
                        with open(self.wema_path+self.name + '_weatherlog.csv', mode='a', newline='') as file:
                            writer = csv.writer(file)
                            writer.writerow(column_names)
                    with open(self.wema_path+self.name + '_weatherlog.csv', mode='a', newline='') as file:
                        writer = csv.writer(file)
                        writer.writerow(line_of_weather_info)
                        plog(f"Data written at {datetime.datetime.now().isoformat()}")  # For logging
                except:
                    plog ("failed to write weatherlog")
                    plog(traceback.format_exc())
                    
            
            try:
                weather_directory=self.wema_path+self.name+ '/weatherfits'
                if not os.path.exists(weather_directory):
                    os.makedirs(weather_directory)
                #file_date_string = str(datetime.datetime.now()).replace(' ', '_').split('.')[0].replace(':', '-')
                ######## We also need to update our cloud prediction model.
                # So lets open the weatherlog
                # Assign column names manually
                
                
                
                # Read CSV without a header and assign column names
                df = pd.read_csv(self.wema_path+self.name + '_weatherlog.csv', header=0)#, names=column_names)
                
                # # Need to remove some rows with nan values
                # #df = df.dropna()
                
                # # Convert to years as main value
                # # Arbitrary reference point is the 1st of janurary 2025
                # # time.time() then is 1735689600.0
                # df['time_in_days']= df['time'] - 1735689600.0
                # df['time_in_days']= df['time_in_days'] / 86400 
                # df['phase_of_day']= df['time_in_days'] % 1
                
                # df['time_in_years']= df['time'] - 1735689600.0
                # df['time_in_years']= df['time_in_years'] / 31536000
                # df['phase_of_year']= df['time_in_years'] % 1
                
                
                # # Solar flux is essentially zero at -18 so set minimum sun altitude to -18
                # df['sun_altitude'] = df['sun_altitude'].clip(lower=-18)
                
                # #To transform the sun altitude so that the relationship with solar flux becomes linear.
                # df['transformed_sun_altitude']= np.exp( df['sun_altitude'] / 6.0)
                
                # X = df[['transformed_sun_altitude', 'sun_azimuth', 'moon_flux_on_ground']]
                # y = df['sky_temp_C']
                
                # # Train-test split (for verification purposes)
                # X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
                
                # # Initialize the model
                # self.sky_temp_model = LinearRegression()
                
                
                # breakpoint()
                # # Train the model
                # self.sky_temp_model.fit(X_train, y_train)
                
                # # Predict the contributions of the factors to sky_temp_C
                # df['predicted_factor_contributions'] = self.sky_temp_model.predict(X)
                
                # # Calculate corrected sky temperature
                # df['corrected_sky_temp_C'] = df['sky_temp_C'] - df['predicted_factor_contributions']
                
                # # Plotting before and after
                # plt.figure(figsize=(14, 6))
                
                # # Original Sky Temperature Plot
                # plt.subplot(1, 2, 1)
                # sns.scatterplot(x=df.index, y=df['sky_temp_C'], label='Original Sky Temperature', color='blue')
                # plt.title(f'Original Sky Temperature\nR² = {r2_score(y, self.sky_temp_model.predict(X)):.2f}')
                # plt.xlabel('Index')
                # plt.ylabel('Sky Temperature (°C)')
                
                # # Corrected Sky Temperature Plot
                # plt.subplot(1, 2, 2)
                # sns.scatterplot(x=df.index, y=df['corrected_sky_temp_C'], label='Corrected Sky Temperature', color='green')
                # plt.title('Corrected Sky Temperature (After Removing Factors)')
                # plt.xlabel('Index')
                # plt.ylabel('Sky Temperature (°C)')
                
                
                # plt.savefig(weather_directory + '/CorrectedSkyTemperature_' + str(file_date_string) + '.png', dpi=300, bbox_inches='tight')
    
                
                # # Checking if the required columns are present in the DataFrame
                # required_columns = ['avg_forecast_cloudcover', 'corrected_sky_temp_C']
                
                # if all(col in df.columns for col in required_columns):
                #     # Plotting avg_forecast_cloudcover vs corrected_sky_temp_C
                #     plt.figure(figsize=(10, 6))
                #     sns.scatterplot(data=df, x='avg_forecast_cloudcover', y='corrected_sky_temp_C', color='purple')
                #     plt.title('Corrected Sky Temperature vs. Average Forecast Cloud Cover')
                #     plt.xlabel('Average Forecast Cloud Cover (%)')
                #     plt.ylabel('Corrected Sky Temperature (°C)')
                #     plt.savefig(weather_directory + '/CloudsvsCorrectedSkyTemperature_' + str(file_date_string) + '.png', dpi=300, bbox_inches='tight')
    
                # else:
                #     missing_columns = [col for col in required_columns if col not in df.columns]
                #     raise ValueError(f"The following columns are missing from the DataFrame: {missing_columns}")
                
                df['sky-ambient'] = df['sky_temp_C'] - df['OWM_temperature']
                
                # dew point depression
                df['dew_point_depression'] =  df['OWM_temperature'] - df['dewpoint']                
                
                try:                    
                    # Run the updated model with polynomial features included
                    self.daytime_cloud_model, self.nighttime_cloud_model, self.number_of_daytime_weather_observations, self.number_of_nighttime_weather_observations = fit_cloud_prediction_model(df, weather_directory)     
                    
                except:
                    plog ("failed model?")
                    plog(traceback.format_exc())
            except:
                plog ("failed model?")
                plog(traceback.format_exc())
                
        except Exception as e:
            plog ("OWM failed", e)
            plog ("Usually a connection glitch")
            plog(traceback.format_exc())
            
        # However, if the enclosure is under manual control, leave this switch on.
        if self.enc_status_custom==False:
            enc_status = g_dev['enc'].status
        else:
            enc_status = get_enc_status_custom()        
                    
        return
        
if __name__ == "__main__":
    wema = WxEncAgent(ptr_config.wema_name, ptr_config.wema_config)
    wema.run()
