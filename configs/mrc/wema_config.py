# -*- coding: utf-8 -*-
"""
Created on Fri Mar 24 19:29:34 2023

@author: obs
"""

# -*- coding: utf-8 -*-
'''

FIRST Created on Fri Aug  2 11:57:41 2019

Refactored on 20230407


@author: wrosing


MRC-0m35      10.0.0.??
MRC-WEMA      10.15.0.42
Power Control 10.15.0.100   admin mrct******
Roof Control  10.15.0.200   admin mrct******
Redis         10.15.0.73:6379
'''
'''
         0         0         0         0         0         0         0         0         0         1         1         1       1
         1         2         3         4         5         6         7         8         9         0         1         2       2
12345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678
'''
import json
import time
from pprint import pprint

# NB NB NB json is not bi-directional with tuples (), instead, use lists [], nested if tuples are needed.
degree_symbol = "°"
wema_name = 'mrc'
instance_type = 'wema'


wema_config = {

    'wema_name': 'mrc',
    'instance_type': 'wema',
    'instance_is_private': False,
    'obsp_ids': ['mrc1', 'mrc2'],  # a list of the obsp's in an enclosure.  

    # These values are to help the weather station self-organise
    # If it is only a nighttime or a daytime observatory, we can restrict
    # fits and predictions of the weather to using data for that period of the day
    # Particularly sky temperature is impacted by daily effects.
    'opens_during_nighttime' : True,
    'opens_during_daytime': False,
    # Which emails to send?
    'send_hourly_cloud_forecast_emails' : False,
    
    'debug_mode': False,
    'debug_duration_sec': 80000,
    'admin_owner_commands_only': False,
    
    'owner':  ['google-oauth2|112401903840371673242'],  # Wayne  Can be a list
    'owner_alias': ['WER', 'TELOPS'],
    
    'site_desc': "Mountain Ranch Camp Observatory, Santa Barbara, CA, USA. 318m",
    'airport_codes': ['SBA', 'SQA', 'OXN'],
    
    'client_hostnames': ["MRC-0m35", "MRC-0m60"],     # This should be a list corresponding to obsp ID's and maybe an parallel ip# list.

    'wema_is_active': True,
    'wema_hostname': 'MRC-WEMA',
    'host_wema_site_name':  'MRC',   #do we need this? 
    'wema_path':  'C:/ptr/',  # '/wema_transfer/',
    'plog_path':  'C:/ptr/mrc/',  # place where night logs can be found.
    'encl_coontrolled_by_wema':  True,
    'site_IPC_mechanism':  'shares',   # ['None', shares', 'shelves', 'redis']
    'wema_write_share_path':  'W:/',
    #'alt_path':  'Q:/ptr/',  # Alternative place for this host to stash misc stuff
    #'save_to_alt_path': 'no',
    #'archive_path':  'Q:/ptr/',
    #'archive_age': 99,  # Number of days to keep files in the local archive before deletion. Negative means never delete
    #'aux_archive_path':  None,  # NB NB we might want to put Q: here for MRC
    #'wema_is_a_process':  False,   #Indicating WEMA runs as an independent OS process on Obsp platform computer
    'dome_on_wema':  False,  #Temporary assignment   20230617 WER
    'redis_ip': None,   # None if no redis path present, localhost if redis iself-contained
    'site_is_single_host':  False, 
    
    'name': 'Mountain Ranch Camp Observatory, Santa Barbara, CA, USA. 318m',
    'location': 'Near Santa Barbara CA,  USA',
    'observatory_url': 'https://starz-r-us.sky/clearskies',
    'observatory_logo': None,
    'dedication':  '''
                    Now is the time for all good persons
                    to get out and vote early and often lest
                    we lose charge of our democracy.
                    ''',  # i.e, a multi-line text block supplied by the owner.  Must be careful about the contents for now.
    'location_day_allsky':  None,  # Thus ultimately should be a URL, probably a color camera.
    'location_night_allsky':  None,  # Thus ultimately should be a URL, usually Mono camera with filters.
    'location _pole_monitor': None,  # This probably gets us to some sort of image (Polaris in the North)
    'location_seeing_report': None,  # Probably a path to a jpeg or png graph.

    'TZ_database_name': 'America/Los_Angeles',
    'mpc_code':  'ZZ23',  # This is made up for now.
    'time_offset': -8,     # NB these two should be derived from Python libs so change is automatic
    'timezone': 'PST',
    'latitude': 34.459375,  # Decimal degrees, North is Positive
    'longitude': -119.681172,  # Decimal degrees, West is negative
    'elevation': 317.75,    # meters above sea level
    # Clear Sky Chart key from cleardarksky.com, eg. 'SaBarbCA'. The UI builds
    # the chart URLs from this; None means no chart is shown for the site.
    'clear_sky_chart_id': 'SaBarbCA',
    'reference_ambient':  10.0,  # Degrees Celsius.  Alternately 12 entries, one for every - mid month.
    'reference_pressure':  977.83,  # mbar Alternately 12 entries, one for every - mid month.
    
    'OWM_active': True,  #  Cosider breaking this up into Rain and Wind vs Cloud cover.
    'local_weather_active': True,
    'local_weather_always_overrides_OWM': False,  ## WER changed to False 20240227  WER changed to True 10/14//2023 Shame on him!
    'enclosure_status_check_period': 30,
    'weather_status_check_period': 30,
    'safety_status_check_period': 30,
    'wema_has_control_of_roof': True,
    'wema_allowed_to_open_roof': True,

    'period_of_time_to_wait_for_roof_to_open': 120,  # seconds - needed to check if the roof ACTUALLY opens.
    'only_scope_that_controls_the_roof': True, # If multiple scopes control the roof, set this to False
    'check_time': 300,  # MF's original setting.  WER No longer used 20231106
    'maximum_roof_opens_per_evening': 4,
    'roof_open_safety_base_time': 15,  #first 'Wx-hold" alternative devinition, time
    
    # For some sites like schools, we need roof to be shut during work hours so balls don't fall into observatories.
    # 24 hour time in decimal local time according to TZ_database_name
    'absolute_earliest_opening_hour': 15.5, # School definitely closed by then.
    'absolute_latest_shutting_hour' : 10.0, # Kids start arriving after this.
    
    'site_enclosures_default_mode': "Automatic",  # "Manual", "Shutdown", "Automatic"
    'automatic_detail_default': "Enclosure is set to Automatic mode.",

    'observing_check_period': 2,    # How many minutes between weather checks
    'enclosure_check_period': 2,    # How many minutes between enclosure checks
    
    #Sequencing keys and value, sets up Events
    'auto_eve_bias_dark': True,
    'auto_eve_sky_flat': True,
    'auto_midnight_moonless_bias_dark': False,
    'auto_morn_sky_flat': True,
    'auto_morn_bias_dark': True,
    
    'morn_close_and_park': 45.0, # How many minutes after sunrise to close. Default 32 minutes = enough time for narrowban
    'eve_cool_down_open': -60.0,
    # WEMA can not have local_weather_info sometimes.. e.g. ECO
    'has_local_weather_info' : True,
    "has_ligntning_detector": False, 

    'bias_dark interval':  115.,   # Takes 102 minutes as of 11/1/23 @ ARO
    'eve_sky_flat_sunset_offset': -50.,  # Before Sunset Minutes  neg means before, + after. Takes about 33 min @ ARO 110123
    'end_eve_sky_flats_offset': -1 ,      # How many minutes after civilDusk to do....
    'clock_and_auto_focus_offset':-10,   #min before start of observing
    'astro_dark_buffer': 30,   #Min before and after AD to extend observing window
    'morn_flat_start_offset': -10,       #min from Sunrise
    'morn_flat_end_offset':  +40,        #min from Sunrise
    'end_night_processing_time':  90,   #  A guess#'eve_sky_flat_sunset_offset': -60.0,  # Minutes  neg means before, + after.
    
        #############################################################
    #### BE AWARE THAT THESE VALUES ARE JUST FOR INITILIASATION!#
    ## THEY WILL BE STORED IN A SHELF AND CHANGES SHOULD BE MADE#
    ## THROUGH THE UI IN THE LONG TERM!                         #
    #############################################################

    # Whether these limits are on by default
    'rain_limit_on': False,
    'humidity_limit_on': False,
    'windspeed_limit_on': False,
    'lightning_limit_on': False,
    'temperature_minus_dewpoint_limit_on': False,
    'sky_minus_ambient_limit_on': True,
    'sky_temperature_limit_on': True,
    'local_cloud_cover_limit_on': True,
    'forecast_cloud_cover_limit_on': True,
    'lowest_ambient_temperature_on': False,
    'highest_ambient_temperature_on': False,
    
    #############################################################
    #### BE AWARE THAT THESE VALUES ARE JUST FOR INITILIASATION!#
    ## THEY WILL BE STORED IN A SHELF AND CHANGES SHOULD BE MADE#
    ## THROUGH THE UI IN THE LONG TERM!                         #
    #############################################################

    # Local weather DANGER limits - will cause the roof to shut
    'rain_limit': 0,
    'humidity_limit': 95,
    'windspeed_limit': 25,
    'lightning_limit': 15,
    'temperature_minus_dewpoint_limit': 2,
    'sky_minus_ambient_limit': -1,
    'sky_temperature_limit': -3,
    'local_cloud_cover_limit': 70,
    'forecast_cloud_cover_limit' : 70,
    'lowest_ambient_temperature': -5,
    'highest_ambient_temperature': 60,
    
    #############################################################
    #### BE AWARE THAT THESE VALUES ARE JUST FOR INITILIASATION!#
    ## THEY WILL BE STORED IN A SHELF AND CHANGES SHOULD BE MADE#
    ## THROUGH THE UI IN THE LONG TERM!                         #
    #############################################################

    # Local weather warning limits, will send a warning, but leave the roof alone
    'warning_rain_limit': 0,
    'warning_humidity_limit': 75,
    'warning_windspeed_limit': 15,
    'warning_lightning_limit': 10,
    'warning_temperature_minus_dewpoint_limit': 2,
    'warning_sky_minus_ambient_limit': -17,
    'warning_sky_temperature_limit': -6,
    'warning_local_cloud_cover_limit': 25,
    'warning_forecast_cloud_cover_limit': 25,
    'warning_lowest_ambient_temperature': 5,
    'warning_highest_ambient_temperature': 35,
    
    
    # #############################################################
    # #### BE AWARE THAT THESE VALUES ARE JUST FOR INITILIASATION!#
    # ## THEY WILL BE STORED IN A SHELF AND CHANGES SHOULD BE MADE#
    # ## THROUGH THE UI IN THE LONG TERM!                         #
    # #############################################################
    
    # # Whether these limits are on by default
    # 'rain_limit_on': False,
    # 'humidity_limit_on': True,
    # 'windspeed_limit_on': True,
    # 'lightning_limit_on': True,
    # 'temperature_minus_dewpoint_limit_on': True,
    # 'sky_minus_ambient_limit_on': True,
    # 'cloud_cover_limit_on': True,
    # 'lowest_ambient_temperature_on': True,
    # 'highest_ambient_temperature_on': True,
    # 'has_inside_weather_station': False,


    # #############################################################
    # #### BE AWARE THAT THESE VALUES ARE JUST FOR INITILIASATION!#
    # ## THEY WILL BE STORED IN A SHELF AND CHANGES SHOULD BE MADE#
    # ## THROUGH THE UI IN THE LONG TERM!                         #
    # #############################################################

    # # Local weather DANGER limits - will cause the roof to shut
    # 'rain_limit': 1,
    # 'humidity_limit': 75,  # % presumably
    # 'windspeed_limit': 15,
    # 'lightning_limit' : 15,
    # 'temperature_minus_dewpoint_limit': 2,
    # 'sky_minus_ambient_limit': -1,
    # 'cloud_cover_limit': 51,
    # 'lowest_ambient_temperature': 1,
    # 'highest_ambient_temperature': 43,
    
    
    # #############################################################
    # #### BE AWARE THAT THESE VALUES ARE JUST FOR INITILIASATION!#
    # ## THEY WILL BE STORED IN A SHELF AND CHANGES SHOULD BE MADE#
    # ## THROUGH THE UI IN THE LONG TERM!                         #
    # #############################################################
    
    # # Local weather warning limits, will send a warning, but leave the roof alone
    # 'warning_rain_limit': 3,
    # 'warning_humidity_limit': 75,
    # 'warning_windspeed_limit': 15,
    # 'warning_lightning_limit' : 10,
    # 'warning_temperature_minus_dewpoint_limit': 3,   #This Should be measured by a radiating metal surface.
    # 'warning_sky_minus_ambient_limit': -17,
    # 'warning_cloud_cover_limit': 25,
    # 'warning_lowest_ambient_temperature': 2,
    # 'warning_highest_ambient_temperature': 35,
 
    'get_ocn_status': None,
    'get_enc_status': None,
    'not_used_variable': None,


    'defaults': {
        'observing_conditions': 'observing_conditions1',
        'enclosure': 'enclosure1',},
    'wema_types': ['observing_conditions','enclosure'], 
    
    'observing_conditions': {
        'observing_conditions1': {
            'ocn_is_custom':  False,  # Indicates some special site code.
            # Intention it is found near bottom of this file.
            'name': 'SkyAlert Custom for MRC',
            'driver': 'ASCOM.SkyAlert.ObservingConditions',
            
            # From reading the aagsolo manual and papers around it,
            # It seems there isn't one reliable settings for estimating
            # cloud cover or rain for that matter and these values are best
            # set based on experience at each different site and probably
            # each different aagsolo that is set up in different ambient
            # conditions. So these values should be eyeballed from
            # the aagsolo/ webpage on the actual network            
            'aagsolo_rain_threshold': 3200,
            'aagsolo_clear_skyT': -4,
            'aagsolo_cloudy_skyT': 19,
            
            
            'share_path_name': None,
            'driver_2': 'ASCOM.SkyAlert.SafetyMonitor',
            'driver_3': None,
            'has_unihedron': False,
            'ocn_has_unihedron':  False,
            'have_local_unihedron': False,     #  Need to add these to setups.
            'uni_driver': 'ASCOM.SQM.serial.ObservingConditions',
            'unihedron_port':  10    #  False, None or numeric of COM port..
            },
        },

    'enclosure': {
        'enclosure1': {
            'name': 'Megawan',
            'driver': 'ASCOM.SkyRoofHub.Dome',    #  Not really a dome for Skyroof!  
            'enclosure_is_directly_connected': False, # True for ECO and EC2, they connect directly to the enclosure, whereas WEMA are different.
            # NB NB NB MF and WER think about this slightly different ways!
            'encl_serves':  ['mnt1', 'mnt2'],
            'encl_is_custom':  False,   #SRO needs sorting, presuambly with this flag.
            'encl_is_dome': False,   #NB NB NB WER Temp Hack
            'encl_is_rolloff': False,
            'rolloff_has_endwall': False,
            'encl_axis': 'ENE',   #Typicall N or S
            'encl_is_openair': False,   #An open-air telescope, on a patio, deck, etc. Presumably uncovered.
            'encl_is_clamshell': True,
            'clamshell_is_split':  True,
            'clamshell_rotates': False,
            'dome_offset_in_degrees': 0.0,
        },
    },

}

def get_enc_status_custom():
    pass
def get_ocn_status_custom():
    pass



if __name__ == '__main__':
    '''
    This is a simple test to send and receive via json.
    '''

    j_dump = json.dumps(wema_config)
    site_unjasoned = json.loads(j_dump)
    if str(wema_config) == str(site_unjasoned):
        print('Strings matched.')
    if wema_config == site_unjasoned:
        print('Dictionaries matched.')
