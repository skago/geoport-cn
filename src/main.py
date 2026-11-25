import locale
import os
import re
import sys
import json
import time
import math
import uuid
import psutil
import signal
import socket
import random
import asyncio
import argparse
import requests
import threading
import webbrowser
import subprocess
import pycountry

if sys.platform == 'win32':
    import pyuac  # Windows-only: UAC elevation helper

from flask import Flask, jsonify, render_template, request
from urllib3.exceptions import ConnectionError
from contextlib import asynccontextmanager

from pymobiledevice3.usbmux import list_devices
from pymobiledevice3.cli.mounter import auto_mount
from pymobiledevice3.lockdown import create_using_usbmux, create_using_tcp, get_mobdev2_lockdowns
from pymobiledevice3.services.amfi import AmfiService
from pymobiledevice3.exceptions import DeviceHasPasscodeSetError, NoDeviceConnectedError
from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation
from pymobiledevice3.remote.remote_service_discovery import RemoteServiceDiscoveryService
from pymobiledevice3.remote.utils import stop_remoted_if_required, resume_remoted_if_required, get_rsds
from pymobiledevice3.remote.tunnel_service import create_core_device_tunnel_service_using_rsd, get_remote_pairing_tunnel_services, start_tunnel, create_core_device_tunnel_service_using_remotepairing, get_core_device_tunnel_services, CoreDeviceTunnelProxy
#from pymobiledevice3.cli.remote import install_driver_if_required
from pymobiledevice3.osu.os_utils import get_os_utils
from pymobiledevice3.bonjour import DEFAULT_BONJOUR_TIMEOUT, browse_mobdev2
from pymobiledevice3.pair_records import get_local_pairing_record, get_remote_pairing_record_filename, get_preferred_pair_record
from pymobiledevice3.common import get_home_folder
# Removed in newer pymobiledevice3 (WeTest driver hack for iOS 17.0-17.3.1 on Windows is obsolete)
try:
    from pymobiledevice3.cli.remote import cli_install_wetest_drivers
except ImportError:
    cli_install_wetest_drivers = None

from pymobiledevice3.cli.remote import tunnel_task
from pymobiledevice3.lockdown import LockdownClient
from pymobiledevice3.lockdown_service_provider import LockdownServiceProvider
from pymobiledevice3.remote.common import TunnelProtocol

#========= Arg Parser ========
# Parse command-line arguments
parser = argparse.ArgumentParser()
parser.add_argument('--no-browser', action='store_true', help='Skip auto opening the browser')
parser.add_argument('--port', type=int, help='Specify port number to listen on for web browser requests')
parser.add_argument('--host', type=str, default='127.0.0.1', help='Address to serve the web UI on (default: 127.0.0.1)')
parser.add_argument('--wifihost', type=str, help='Specify the wifi IP address to connect to')
parser.add_argument('--udid', type=str, help='Specify the device udid to target')
args = parser.parse_args()
#========= Arg Parser ========

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
OSUTILS = get_os_utils()


import logging


# Get or create a logger instance named "GeoPort"
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)

# Create a logger named "GeoPort"
logger = logging.getLogger("GeoPort")
logging.getLogger("urllib3").setLevel(logging.WARNING)

logging.getLogger('werkzeug').disabled = True
#log.disabled = True

app = Flask(__name__)

# Define constants
# Get the home directory of the current user
home_dir = os.path.expanduser("~")
is_windows = sys.platform == 'win32'
base_directory = getattr(sys, '_MEIPASS', os.path.abspath(os.path.dirname(sys.argv[0])))
flask_port = 54321
api_url = "https://projectzerothree.info/api.php?format=json"
api_data = None
user_locale = None
location = None
rsd_data = None
rsd_host = None
rsd_port = None
rsd_data_map = {}
wifi_address = None
wifihost = args.wifihost
wifi_port = None
connection_type = None
udid = None
lockdown = None
ios_version = None
pair_record = None
error_message = None
sudo_message = ""
captured_output = None
# Update check / broadcast point to this fork's repo (falls back silently if unreachable).
# Change this if you publish under a different GitHub path.
GITHUB_REPO = 'skago/geoport-cn'
CURRENT_VERSION_FILE = 'CURRENT_VERSION'
BROADCAST_FILE = 'BROADCAST'
APP_VERSION_NUMBER = "5.0.3-cn.1"
APP_VERSION_TYPE = "cn"
terminate_tunnel_thread = False
terminate_location_thread = False
location_threads = []
timeout = DEFAULT_BONJOUR_TIMEOUT

# Get the current platform using sys.platform
current_platform = sys.platform

# Map the platform names to standard values
platform = {
    'win32': 'Windows',
    'linux': 'Linux',
    'darwin': 'MacOS',
}.get(current_platform, 'Unknown')

# Check if running as sudo
if current_platform == "darwin":
    if os.geteuid() != 0:
        logger.error("*********************** WARNING ***********************")
        logger.error("Not running as Sudo, this probably isn't going to work")
        logger.error("*********************** WARNING ***********************")
        sudo_message = "Not running as Sudo, this probably isn't going to work"
    else:
        logger.info("Running as Sudo")
        sudo_message = ""



def fetch_api_data(api_url):
    global api_data
    try:
        api_data = requests.get(api_url, timeout=10).json()
        return api_data
    except requests.exceptions.RequestException as e:
        logger.error(f"Error: {e}")
        logger.error(f"API is unreachable or there was an error during the request")
        logger.error("Sorry - Fuel data is not available")
        return None
    except ConnectionError as e:
        logger.error("Error: Name resolution failed.")
        logger.error("Please check your internet connection or the correctness of the API URL.")
        logger.error("Sorry - Fuel data is not available")
        logger.error(f"Details: {e}")
        return None

def create_geoport_folder():
    # Define the path to the GeoPort folder
    geoport_folder = os.path.join(home_dir, 'GeoPort')

    # Check if the GeoPort folder exists, create it if not
    if not os.path.exists(geoport_folder):
        os.makedirs(geoport_folder)
        logger.info(f"GeoPort Home: {geoport_folder}")
        logger.info("GeoPort folder created successfully")

    # Set permissions for the GeoPort folder
    if current_platform == 'win32':
        # Windows permissions (read/write for everyone)
        os.system(f"icacls {geoport_folder} /grant Everyone:(OI)(CI)F")
        logger.info("Permissions set for GeoPort folder on Windows")
    else:  # Linux and MacOS
        # POSIX permissions (read/write for everyone)
        os.chmod(geoport_folder, 0o777)
        logger.info("Permissions set for GeoPort folder on MacOS")



# Define the function to be executed in the thread
def run_tunnel(service_provider):

    try:
        asyncio.run(start_quic_tunnel(service_provider))

        logger.info("run_tun completed")
        sys.exit(0)

    except Exception as e:
        error_message = str(e)

        # Handle the exception, such as logging it or returning an error response
        with app.app_context():
            return jsonify({'error': error_message})

    #return

# Define a function to start the tunnel thread
def start_tunnel_thread(service_provider):
    global terminate_tunnel_thread  # Declare the global variable
    terminate_tunnel_thread = False  # Set the value of the global variable
    thread = threading.Thread(target=run_tunnel, args=(service_provider,))
    thread.start()
    return

async def start_quic_tunnel(service_provider: RemoteServiceDiscoveryService) -> None:

    logger.warning("Start USB QUIC tunnel")

    global terminate_tunnel_thread
    stop_remoted_if_required()
    #install_driver_if_required()

    # if sys.platform == 'win32':
    #     logger.info("Windows System - Driver Check Required")
    #     if version_check(ios_version):
    #         logger.warning("Installing WeTest Driver - QUIC Tunnel")
    #         cli_install_wetest_drivers()

    service = await create_core_device_tunnel_service_using_rsd(service_provider, autopair=True)

    async with service.start_quic_tunnel() as tunnel_result:
        resume_remoted_if_required()

        logger.info(f"QUIC Address: {tunnel_result.address}")
        logger.info(f"QUIC Port: {tunnel_result.port}")
        global rsd_port
        global rsd_host
        rsd_host = tunnel_result.address

        rsd_port = str(tunnel_result.port)


        while True:
            if terminate_tunnel_thread is True:
                return
            # wait user input while the asyncio tasks execute
            await asyncio.sleep(.5)


# Define the function to be executed in the thread
def run_tcp_tunnel(service_provider):

    try:
        asyncio.run(start_tcp_tunnel(service_provider))

        logger.info("run_tun completed")
        sys.exit(0)

    except Exception as e:
        error_message = str(e)

        # Handle the exception, such as logging it or returning an error response
        with app.app_context():
            return jsonify({'error': error_message})

    #return

# Define a function to start the tunnel thread
def start_tcp_tunnel_thread(service_provider):
    global terminate_tunnel_thread  # Declare the global variable
    terminate_tunnel_thread = False  # Set the value of the global variable
    thread = threading.Thread(target=run_tcp_tunnel, args=(service_provider,))
    thread.start()
    return

async def start_tcp_tunnel(service_provider: CoreDeviceTunnelProxy) -> None:

    logger.warning("Start USB TCP tunnel")

    global terminate_tunnel_thread
    stop_remoted_if_required()
    #install_driver_if_required()

    #service = await create_core_device_tunnel_service_using_rsd(service_provider, autopair=True)

    lockdown = create_using_usbmux(udid, autopair=True)
    #print("Lockdown for Windows: ", lockdown)
    service = CoreDeviceTunnelProxy(lockdown)
    #asyncio.run(tunnel_task(service, secrets=None, protocol=TunnelProtocol.TCP), debug=True)
    async with service.start_tcp_tunnel() as tunnel_result:
        logger.info(f"TCP Address: {tunnel_result.address}")
        logger.info(f"TCP Port: {tunnel_result.port}")
        global rsd_port
        global rsd_host
        rsd_host = tunnel_result.address

        rsd_port = str(tunnel_result.port)

        while True:
            if terminate_tunnel_thread is True:
                return
            # wait user input while the asyncio tasks execute
            await asyncio.sleep(.5)





def is_major_version_17_or_greater(version_string):
    # Check if the major version in the given version string is 17 or greater.
    try:
        major_version = int(version_string.split('.')[0])
        return major_version >= 17
    except (ValueError, IndexError):
        # Handle invalid version string or missing major version
        return False

def is_major_version_less_than_16(version_string):
    # Check if the major version in the given version string is 17 or greater.
    try:
        major_version = int(version_string.split('.')[0])
        return major_version < 16
    except (ValueError, IndexError):
        # Handle invalid version string or missing major version
        logger.error(f"Error: {ValueError}, {IndexError}")
        return False


def version_check(version_string):
    try:
        # Split the version string into major and minor version parts
        version_parts = version_string.split('.')

        # Extract the major and minor version parts
        major_version = int(version_parts[0])
        minor_version = int(version_parts[1]) if len(version_parts) > 1 else 0

        # Check if the version string satisfies the condition
        if major_version == 17 and 0 <= minor_version <= 3:
            if sys.platform == 'win32':
                logger.info("Checking Windows Driver requirement")
                logger.info("Driver is required")
            return True
        else:
            if sys.platform == 'win32':
                logger.info("Driver is not required")
                return False
            logger.info("MacOS - pass")
            return False



    except (ValueError, IndexError) as e:
        logger.error(f"Driver check error: {e}")
        # Handle invalid version string or missing major/minor version
        return False

_user_country_cache = None

def get_user_country():
    global user_locale, _user_country_cache
    # Cache the result: this is called for every device on every device-list refresh
    if _user_country_cache is not None:
        return _user_country_cache
    try:
        # Attempt to get the user's country using locale and pycountry
        user_locale, _ = locale.getlocale()

        if user_locale is None:
            logger.warning("User locale is None. Defaulting to IP geolocation service.")
            _user_country_cache = get_country_from_ip()
            return _user_country_cache

        country_code = user_locale.split('_')[-1]
        country = pycountry.countries.get(alpha_2=country_code)
        country_name = country.name if country else None

        # If country_name is None, try IP geolocation service as a fallback
        if country_name is None:
            logger.warning("Failed to retrieve country name using locale. Using IP geolocation service.")
            _user_country_cache = get_country_from_ip()
        else:
            _user_country_cache = country_name
        return _user_country_cache

    except Exception as e:
        logger.error(f"Error getting user country: {e}")
        return None


def get_country_from_ip():
    # Prefer an HTTPS geolocation service; fall back to ip-api.com (HTTP-only on the free tier)
    try:
        response = requests.get("https://ipapi.co/json/", timeout=10)
        if response.status_code == 200:
            data = response.json()
            country_name = data.get("country_name")
            if country_name:
                return country_name
    except Exception as e:
        logger.warning(f"ipapi.co lookup failed: {e}")

    try:
        response = requests.get("http://ip-api.com/json/", timeout=10)
        if response.status_code == 200:
            data = response.json()
            country_name = data.get("country")
            if country_name:
                return country_name
            else:
                logger.warning("Failed to retrieve country name from IP geolocation service.")
        else:
            logger.error(f"Error: Unable to retrieve data. Status code: {response.status_code}")
            logger.warning("Setting to default country")
            country_name = "Spain"
        return country_name
    except Exception as e:
        logger.error(f"Error getting country from IP geolocation service: {e}")
        country_name = "Spain"
        return country_name
def get_devices_with_retry(max_attempts=10):
    if sys.platform == 'win32':
        logger.info(f"iOS Version: {ios_version}")
        if version_check(ios_version):
            logger.info("Windows Driver Install Required")
            if cli_install_wetest_drivers is not None:
                cli_install_wetest_drivers()
            else:
                logger.warning("WeTest driver installer unavailable in this pymobiledevice3 version - upgrade the device to iOS 17.4+ instead")
    for attempt in range(1, max_attempts + 1):
        try:
            devices = asyncio.run(get_rsds(timeout))
            #dev1 = asyncio.run(get_rsds(timeout))
            #devices = asyncio.run(get_core_device_tunnel_services(timeout))
            #print("devices: ", devices)
            #print("dev1: ", dev1)
            if devices:
                return devices  # Return devices if the list is not empty
            else:
                logger.warning(f"Attempt {attempt}: No devices found")
        except Exception as e:
            logger.warning(f"Attempt {attempt}: Error occurred - {e}")
        time.sleep(1)  # Add a delay between attempts if needed
    raise RuntimeError("No devices found after multiple attempts.\n Ensure you are running GeoPort as sudo / Administrator \n Please see the FAQ: https://github.com/davesc63/GeoPort/blob/main/FAQ.md \n If you still have the error please raise an issue on github: https://github.com/davesc63/GeoPort/issues ")


def get_wifi_with_retry(max_attempts=10):
    global udid, wifi_address, wifi_port

    for attempt in range(1, max_attempts + 1):
        try:
            logger.info("Discovering Wifi Devices - This may take a while...")
            devices = asyncio.run(get_remote_pairing_tunnel_services(timeout))
            #devices = get_remote_pairing_tunnel_services(timeout)



            if devices:
                if udid:
                    for device in devices:
                        if device.remote_identifier == udid:
                            logger.info(f"Device found with udid: {udid}.")
                            wifi_address = device.hostname
                            wifi_port = device.port
                            return device
                else:
                    return devices
            else:
                logger.warning(f"Attempt {attempt}: No devices found")
        except Exception as e:
            logger.warning(f"Attempt {attempt}: Error occurred - {e}")

        # Add a delay between attempts
        time.sleep(1)

    raise RuntimeError("No devices found after multiple attempts. Please see the FAQ.")
@app.route('/stop_tunnel', methods=['POST'])
def stop_tunnel_thread():
    global terminate_tunnel_thread
    logger.info("stop tunnel thread")
    # Set the terminate flag to True to stop the thread
    terminate_tunnel_thread = True
    return jsonify("Tunnel stopped")

@app.route('/api/data/<fuel_type>')
def get_fuel_type_data(fuel_type):
    selected_fuel_region = request.args.get('region', 'All')

    if api_data is None:
        logger.error("API Data is none, Fuel data is not available")
        return jsonify({}), 500  # Return an empty response with status code 500 (Internal Server Error)

    all_region_data = next(
        (region['prices'] for region in api_data['regions'] if region['region'] == selected_fuel_region), [])

    selected_data = next((entry for entry in all_region_data if entry['type'] == fuel_type), None)

    return jsonify(selected_data)


@app.route('/api/fuel_types')
def get_fuel_types():
    selected_fuel_region = request.args.get('region', 'All')

    if api_data is None:
        logger.error("API Data is none, sorry - Fuel data is not available")
        return jsonify({}), 500  # Return an empty response with status code 500 (Internal Server Error)

    all_region_data = next(
        (region['prices'] for region in api_data['regions'] if region['region'] == selected_fuel_region), [])

    fuel_types = set(entry['type'] for entry in all_region_data)

    return jsonify(list(fuel_types))


@app.route('/update_location', methods=['POST'])
def update_location():
    # Use 'request' to get the JSON data from the client
    data = request.get_json()

    # Convert latitude and longitude to float values
    lat = float(data['lat'])
    lng = float(data['lng'])

    global location
    location = f"{lat} {lng}"
    return 'Location updated successfully'


#========= Saved Locations (History & Favorites) ========

SAVED_LOCATIONS_FILE = os.path.join(home_dir, 'GeoPort', 'saved_locations.json')
SAVED_LOCATIONS_LOCK = threading.Lock()
HISTORY_MAX_ENTRIES = 100
# Distance (meters) below which a new history entry updates the previous one
# instead of creating a duplicate
HISTORY_DEDUPE_DISTANCE = 50

def load_saved_locations():
    with SAVED_LOCATIONS_LOCK:
        try:
            with open(SAVED_LOCATIONS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get('history'), list) \
                    and isinstance(data.get('favorites'), list):
                return data
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass
        return {'history': [], 'favorites': []}

def save_saved_locations(data):
    folder = os.path.dirname(SAVED_LOCATIONS_FILE)
    os.makedirs(folder, exist_ok=True)
    with SAVED_LOCATIONS_LOCK:
        with open(SAVED_LOCATIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

def haversine_distance(lat1, lng1, lat2, lng2):
    """Great-circle distance between two points in meters."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(a))

def make_location_entry(lat, lng, label):
    return {
        'id': uuid.uuid4().hex[:12],
        'lat': round(float(lat), 6),
        'lng': round(float(lng), 6),
        'label': (label or '').strip() or f"{round(float(lat), 6)}, {round(float(lng), 6)}",
        'ts': int(time.time()),
    }

def record_location_history(lat, lng, label=None):
    """Record a used location. Consecutive entries closer than
    HISTORY_DEDUPE_DISTANCE meters update the existing entry (moves it to front)."""
    data = load_saved_locations()
    history = data.get('history', [])
    entry = make_location_entry(lat, lng, label)

    if history:
        last = history[0]
        if haversine_distance(last['lat'], last['lng'], entry['lat'], entry['lng']) \
                < HISTORY_DEDUPE_DISTANCE:
            entry['id'] = last['id']
            history[0] = entry
            data['history'] = history
            save_saved_locations(data)
            return

    history.insert(0, entry)
    data['history'] = history[:HISTORY_MAX_ENTRIES]
    save_saved_locations(data)

def find_favorite(data, favorite_id):
    for entry in data.get('favorites', []):
        if entry.get('id') == favorite_id:
            return entry
    return None

@app.route('/api/locations')
def get_saved_locations():
    return jsonify(load_saved_locations())

@app.route('/api/history', methods=['POST'])
def add_history_entry():
    try:
        data = request.get_json(force=True) or {}
        lat = float(data['lat'])
        lng = float(data['lng'])
        record_location_history(lat, lng, data.get('label'))
        return jsonify({'success': True})
    except (ValueError, TypeError, KeyError) as e:
        return jsonify({'error': f'Invalid coordinates: {e}'}), 400

@app.route('/api/history', methods=['DELETE'])
def clear_history():
    data = load_saved_locations()
    data['history'] = []
    save_saved_locations(data)
    return jsonify({'success': True})

@app.route('/api/favorites', methods=['POST'])
def add_favorite():
    try:
        data = request.get_json(force=True) or {}
        lat = float(data['lat'])
        lng = float(data['lng'])
    except (ValueError, TypeError, KeyError) as e:
        return jsonify({'error': f'Invalid coordinates: {e}'}), 400

    stored = load_saved_locations()
    entry = make_location_entry(lat, lng, data.get('label'))

    # Skip exact duplicates (same spot with the same label)
    for existing in stored.get('favorites', []):
        if existing['lat'] == entry['lat'] and existing['lng'] == entry['lng'] \
                and existing['label'] == entry['label']:
            return jsonify({'success': True, 'duplicate': True})

    stored.setdefault('favorites', []).insert(0, entry)
    save_saved_locations(stored)
    return jsonify({'success': True})

@app.route('/api/favorites/<favorite_id>', methods=['DELETE'])
def delete_favorite(favorite_id):
    stored = load_saved_locations()
    favorites = stored.get('favorites', [])
    kept = [entry for entry in favorites if entry.get('id') != favorite_id]
    if len(kept) == len(favorites):
        return jsonify({'error': 'Favorite not found'}), 404
    stored['favorites'] = kept
    save_saved_locations(stored)
    return jsonify({'success': True})

@app.route('/api/favorites/<favorite_id>', methods=['PUT'])
def rename_favorite(favorite_id):
    data = request.get_json(force=True) or {}
    new_label = (data.get('label') or '').strip()
    if not new_label:
        return jsonify({'error': 'Label cannot be empty'}), 400

    stored = load_saved_locations()
    entry = find_favorite(stored, favorite_id)
    if entry is None:
        return jsonify({'error': 'Favorite not found'}), 404
    entry['label'] = new_label
    save_saved_locations(stored)
    return jsonify({'success': True})

#========= Saved Locations (History & Favorites) ========

def check_pair_record(udid):
    global pair_record
    logger.info(f"Connection Type: {connection_type}")
    logger.info("Enable Developer Mode")

    home = get_home_folder()
    logger.info(f"Pair Record Home: {home}")

    filename = get_remote_pairing_record_filename(udid)
    logger.info(f"Pair Record File: {filename}")

    # pair_record = get_local_pairing_record(filename, home)
    pair_record = get_preferred_pair_record(udid, home)
    #logger.info(f"Pair Record: {pair_record}")
    return pair_record

def check_developer_mode(udid, connection_type):
    try:

        logger.warning(f"Check Developer Mode")

        lockdown = create_using_usbmux(udid, connection_type=connection_type, autopair=True)

        result = lockdown.developer_mode_status
        logger.info(f"Developer Mode Check result:  {result}")

        # Check if developer mode is enabled
        if result:
            logger.info("Developer Mode is true")
            return True
        else:
            logger.warning("Developer Mode is false")
            return False

    except subprocess.CalledProcessError as e:
        return False


def enable_developer_mode(udid, connection_type):
    check_pair_record(udid)


    logger.info(f"Connection Type: {connection_type}")
    logger.info("Enable Developer Mode")

    home = get_home_folder()
    logger.info(f"Pair Record Home: {home}")
    #
    # filename = get_remote_pairing_record_filename(udid)
    # logger.info(f"Pair Record File: {filename}")
    #
    # pair_record = get_local_pairing_record(filename, home)
    # logger.info(f"Pair Record: {pair_record}")
    if connection_type == "Network":
        if pair_record is None:
            logger.error("Network: No Pair Record Found. Please use a USB cable first to create a pair record")
            return False, "No Pair Record Found. Please use a USB cable first to create a pair record"
    else:
        logger.error("No Pair Record Found. USB cable detected. Creating a pair record")
        pass
        #return False, "No Pair Record Found. Please use a USB cable first to create a pair record"

    lockdown = create_using_usbmux(
        udid,
        connection_type=connection_type,
        autopair=True,
        pairing_records_cache_folder=home)


    try:

        AmfiService(lockdown).enable_developer_mode()
        logger.info("Enable complete, mount developer image...")
        mount_developer_image()

    except DeviceHasPasscodeSetError:
        error_message = "Error: Device has a passcode set\n \n Please temporarily remove the passcode and run GeoPort again to enable Developer Mode \n \n Go to \"Settings - Face ID & Passcode\"\n"
        logger.error(f"{error_message}")
        return False, error_message

    # except Exception as e:  # Catch any other exception
    #     logger.error(f"An error occurred: {str(e)}")
    #     return False, f"An error occurred: {str(e)}"

    return True, None




@app.route('/enable_developer_mode', methods=['POST'])
def enable_developer_mode_route():
    try:
        global udid
        data = request.get_json()

        # Extract the udid from the request
        udid = data.get('udid', None)

        success, error_message = enable_developer_mode(udid, connection_type)

        if success:
            # Return a success response with any additional data needed
            return jsonify({'success': True, 'udid': udid})
        else:
            return jsonify({'error': error_message})

    except Exception as e:
        error_message = str(e)
        return jsonify({'error': error_message})



@app.route('/connect_device', methods=['POST'])
def connect_device():
    global udid, connection_type, ios_version, rsd_data, rsd_host, rsd_port, wifi_address

    data = request.get_json()
    logger.info(f"Connect Device Data: {data}")

    # Extract the udid from the request
    udid = data.get('udid', None)
    #ios_version = data.get('ios_version')

    connection_type = data.get('connType')



    if udid in rsd_data_map:
        if connection_type in rsd_data_map[udid]:
            logger.info(f"Connect_Device Map - Looking for {udid} in {connection_type}")
            rsd_data = rsd_data_map[udid][connection_type]

            rsd_host = rsd_data['host']
            rsd_port = rsd_data['port']

            logger.info(f"RSD in udid mapping is: {rsd_data}")
            logger.info("RSD already created. Reusing connection")
            logger.info(f"RSD Data: {rsd_data}")
            return jsonify({'rsd_data': rsd_data})

        # If no matching entry found for the udid and desired connection type
        logger.info(f"No matching RSD entry found for udid: {udid} and connection type: {connection_type}")


    # Check if developer mode is enabled, and enable it if not
    #logger.info("Must be iOS17")
    if not check_developer_mode(udid, connection_type):
        # Display modal to inform the user and give options
        return jsonify({'developer_mode_required': 'True'})

    if connection_type == "USB":
        return connect_usb(data)

    elif connection_type == "Network":
        check_pair_record(udid)

        if pair_record is None:
            logger.error("No Pair Record Found. Please use a USB Cable to create one")
            return jsonify({"Error": "No Pair Record Found"})
        result = connect_wifi(data)
        #result = await connect_wifi(data)
        #return await connect_wifi(data)
        return result

    elif connection_type == "Manual":
        check_pair_record(udid)

        if pair_record is None:
            logger.error("No Pair Record Found. Please use a USB Cable to create one")
            return jsonify({"Error": "No Pair Record Found"})
        result = connect_wifi(data)
        # result = await connect_wifi(data)
        # return await connect_wifi(data)
        return result
    else:
        logger.error("Error: No matching connection type")
        return jsonify({"Error": "No matching connection type"})

def check_rsd_data():
    max_attempts = 30
    attempts = 0
    while attempts < max_attempts:
        if rsd_host is not None and rsd_port is not None:
            return True  # Data is available
        time.sleep(1)
        attempts += 1
    return False  # Data is still None after all attempts

def connect_usb(data):
    try:
        global udid, connection_type
        global ios_version
        global rsd_data, rsd_host, rsd_port

        logger.info(f"USB data: {data}")

        # Extract the udid from the request
        udid = data.get('udid', None)
        ios_version = data.get('ios_version')
        #ios_version = "17.0"
        connection_type = data.get('connType')
        rsd_host = None
        rsd_port = None

        if ios_version is not None and is_major_version_17_or_greater(ios_version):
            logger.info("iOS 17+ detected")


            logger.info(f"iOS Version: {ios_version}")
            if version_check(ios_version):
                if sys.platform == 'win32':
                    logger.warning("iOS is between 17.0 and 17.3.1, WHY?")
                    logger.warning("You should upgrade to 17.4+")
                    logger.error("We need to install a 3rd party driver for these versions")
                    logger.error("which may stop working at any time")
                    try:
                        devices = get_devices_with_retry()
                        logger.info(f"Devices: {devices}")
                        rsd = [device for device in devices if device.udid == udid]
                        if len(rsd) > 0:
                            rsd = rsd[0]
                        start_tunnel_thread(rsd)

                    except RuntimeError as e:
                        error_message = str(e)
                        logger.error(f"Error: {error_message}")
                        return jsonify({'error': 'No Devices Found'})
                else:
                    logger.warning("ios <17.4 on non-windows")
                    try:
                        devices = get_devices_with_retry()
                        logger.info(f"Devices: {devices}")
                        rsd = [device for device in devices if device.udid == udid]
                        if len(rsd) > 0:
                            rsd = rsd[0]
                        start_tunnel_thread(rsd)

                    except RuntimeError as e:
                        error_message = str(e)
                        logger.error(f"Error: {error_message}")
                        return jsonify({'error': 'No Devices Found'})

            else:
                global lockdown
                lockdown = create_using_usbmux(udid, autopair=True)
                logger.info(f"Create Lockdown {lockdown}")
                start_tcp_tunnel_thread(lockdown)


            #time.sleep(3)
            if not check_rsd_data():
                logger.error("RSD Data is None, Perhaps the tunnel isn't established")
            else:
                rsd_data = rsd_host, rsd_port
                logger.info(f"RSD Data: {rsd_data}")

            rsd_data_map.setdefault(udid, {})[connection_type] = {"host": rsd_host, "port": rsd_port}
            logger.info(f"Device Connection Map: {rsd_data_map}")
            return jsonify({'rsd_data': rsd_data})

        elif ios_version is not None and not is_major_version_17_or_greater(ios_version):
            rsd_data = ios_version, udid
            logger.info(f"RSD Data: {rsd_data}")

            # # Check if developer mode is enabled, and enable it if not
            # if not check_developer_mode(udid, connection_type):
            #     # Display modal to inform the user and give options
            #     return jsonify({'developer_mode_required': 'True'})

            # create LockdownServiceProvider
            #global lockdown
            lockdown = create_using_usbmux(udid, autopair=True)
            logger.info(f"Lockdown client = {lockdown}")
            #rsd_data = rsd_host, rsd_port
            rsd_host, rsd_port = rsd_data

            #rsd_data_map[udid] = rsd_data
            rsd_data_map.setdefault(udid, {})[connection_type] = {"host": rsd_host, "port": rsd_port}

            return jsonify({'message': 'iOS version less than 17', 'rsd_data': rsd_data})

        else:
            # Invalid ios_version
            return jsonify({'error': 'No iOS version present'})
    finally:
        logger.warning("Connect Device function completed")

def connect_wifi(data):
    try:
        global udid, wifi_address, connection_type, wifi_port
        global ios_version
        global rsd_data, rsd_host, rsd_port

        logger.info(f"Wifi data: {data}")

        # Extract the udid from the request
        udid = data.get('udid', None)
        ios_version = data.get('ios_version')
        #ios_version = "17.3.1"
        #wifi_address = data.get('wifiAddress')
        #logger.error(f"wifi address: {wifi_address}")
        connection_type = data.get('connType')

        if ios_version is not None and is_major_version_17_or_greater(ios_version):
            logger.info("iOS 17+ detected")

            if version_check(ios_version):
                try:
                    devices = get_wifi_with_retry()
                    #devices = "blah"
                    logger.info(f"Connect Wifi Devices: {devices}")
                    logger.info(f"Wifi Address:  {wifi_address}")
                except RuntimeError as e:
                    error_message = str(e)
                    logger.error(f"Error: {error_message}")
                    return jsonify({'error': 'No Devices Found'})


            rsd_host = None
            rsd_port = None

            # Run tun(devices) as a background task
            #asyncio.create_task(tun(devices))
            #await tun(devices)
            #start_wifi_tunnel_thread(devices)
            start_wifi_tunnel_thread()

            if not check_rsd_data():
                logger.error("RSD Data is None, Perhaps the tunnel isn't established")
            else:
                rsd_data = rsd_host, rsd_port
                logger.info(f"RSD Data: {rsd_data}")

            rsd_data_map.setdefault(udid, {})[connection_type] = {"host": rsd_host, "port": rsd_port}
            logger.info(f"Device Connection Map: {rsd_data_map}")
            return jsonify({'rsd_data': rsd_data})

        elif ios_version is not None and not is_major_version_17_or_greater(ios_version):
            rsd_data = ios_version, udid
            logger.info(f"RSD Data: {rsd_data}")

            # create LockdownServiceProvider
            global lockdown
            lockdown = create_using_usbmux(udid, connection_type=connection_type, autopair=True)
            #lockdown = create_using_tcp(wifi_address, udid)
            logger.info(f"Lockdown client = {lockdown}")

            rsd_data_map.setdefault(udid, {})[connection_type] = {"host": rsd_host, "port": rsd_port}

            return jsonify({'message': 'iOS version less than 17', 'rsd_data': rsd_data})

        else:
            # Invalid ios_version
            return jsonify({'error': 'No iOS version present'})
    finally:
        logger.warning("Connect Device function completed")




async def start_wifi_tcp_tunnel() -> None:

    logger.warning(f"Start Wifi TCP Tunnel")

    global terminate_tunnel_thread
    stop_remoted_if_required()
    #install_driver_if_required()

    # if sys.platform == 'win32':
    #     if is_driver_required:
    #         logger.warning("Installing WeTest Driver")
    #         cli_install_wetest_drivers()

    #service = await create_core_device_tunnel_service_using_remotepairing(udid, wifi_address, wifi_port)
    lockdown = create_using_usbmux(udid)
    service = CoreDeviceTunnelProxy(lockdown)

    async with service.start_tcp_tunnel() as tunnel_result:
        resume_remoted_if_required()

        logger.info(f'Identifier: {service.remote_identifier}')
        logger.info(f'Interface: {tunnel_result.interface}')
        logger.info(f'RSD Address: {tunnel_result.address}')
        logger.info(f'RSD Port: {tunnel_result.port}')
        global rsd_port
        global rsd_host
        rsd_host = tunnel_result.address

        rsd_port = str(tunnel_result.port)


        while True:
            if terminate_tunnel_thread is True:
                return
            # wait user input while the asyncio tasks execute
            await asyncio.sleep(.5)

async def start_wifi_quic_tunnel() -> None:

    logger.warning(f"Start Wifi QUIC Tunnel")

    global terminate_tunnel_thread
    stop_remoted_if_required()
    #install_driver_if_required()

    # if sys.platform == 'win32':
    #     if is_driver_required:
    #         logger.warning("Installing WeTest Driver")
    #         cli_install_wetest_drivers()
    #get_wifi_with_retry()
    service = await create_core_device_tunnel_service_using_remotepairing(udid, wifi_address, wifi_port)
    # lockdown = create_using_usbmux(udid)
    # service = CoreDeviceTunnelProxy(lockdown)

    async with service.start_quic_tunnel() as tunnel_result:
        resume_remoted_if_required()

        logger.info(f'Identifier: {service.remote_identifier}')
        logger.info(f'Interface: {tunnel_result.interface}')
        logger.info(f'RSD Address: {tunnel_result.address}')
        logger.info(f'RSD Port: {tunnel_result.port}')
        global rsd_port
        global rsd_host
        rsd_host = tunnel_result.address

        rsd_port = str(tunnel_result.port)


        while True:
            if terminate_tunnel_thread is True:
                return
            # wait user input while the asyncio tasks execute
            await asyncio.sleep(.5)

# Define a function to start the tunnel thread
def start_wifi_tunnel_thread():
    global terminate_tunnel_thread
    terminate_tunnel_thread = False  # Set the value of the global variable
    thread = threading.Thread(target=run_wifi_tunnel)
    thread.start()
    return

# Entry point for running the tunnel async function
def run_wifi_tunnel():
    try:
        if version_check(ios_version):
            asyncio.run(start_wifi_quic_tunnel())
        #TODO: or win32 / 17.0-17.3 special tunnel

        else:
            asyncio.run(start_wifi_tcp_tunnel())
        #await tun(devices)
    except Exception as e:
        logger.error(f"Error in run_wifi_tunnel: {e}")


@app.route('/mount_developer_image', methods=['POST'])
def mount_developer_image():
    try:

        global lockdown
        lockdown = create_using_usbmux(udid, autopair=True)
        logger.info(f"mount lockdown: {lockdown}")

        auto_mount(lockdown)

        return 'Developer image mounted successfully'
    except Exception as e:
        error_message = str(e)
        return jsonify({'error': error_message})

async def set_location_thread(latitude, longitude):
    global terminate_location_thread

    try:
        global rsd_host, rsd_port, udid, ios_version, connection_type

        if udid in rsd_data_map:
            if connection_type in rsd_data_map[udid]:
                rsd_data = rsd_data_map[udid][connection_type]
                rsd_host = rsd_data['host']
                rsd_port = rsd_data['port']

                logger.info(f"RSD in udid mapping is: {rsd_data}")
                logger.info("RSD already created. Reusing connection")
                logger.info(f"RSD Data: {rsd_data}")


                if ios_version is not None and is_major_version_17_or_greater(ios_version):
                    async with RemoteServiceDiscoveryService((rsd_host, rsd_port)) as sp_rsd:
                        async with DvtProvider(sp_rsd) as dvt:
                            async with LocationSimulation(dvt) as simulation:
                                await simulation.set(float(latitude), float(longitude))
                                logger.warning("Location Set Successfully")
                                #OSUTILS.wait_return()
                                while not terminate_location_thread:
                                    await asyncio.sleep(0.5)


                elif ios_version is not None and not is_major_version_17_or_greater(ios_version):
                    async with DvtProvider(lockdown) as dvt:
                        async with LocationSimulation(dvt) as simulation:
                            await simulation.clear()
                            await simulation.set(float(latitude), float(longitude))
                            logger.warning("Location Set Successfully")
                            #await asyncio.wait_for(OSUTILS.wait_return(), timeout=1)  # Adjust timeout as needed
                            while not terminate_location_thread:
                                await asyncio.sleep(0.5)

                await asyncio.sleep(1)  # Adjust sleep time according to your requirements

    except asyncio.CancelledError:
        # Handle cancellation gracefully
        pass
    except ConnectionResetError as cre:
        if "[Errno 54] Connection reset by peer" in str(cre):
            logger.error("The Set Location buffer is full. Try to 'Stop Location' to clear old connections")
    except Exception as e:
        logger.error(f"Error setting location: {e}")


# Function to start the set_location_thread in a separate thread
def start_set_location_thread(latitude, longitude):
    global terminate_location_thread
    # Stop existing threads
    stop_set_location_thread()

    # Reset the terminate flag before starting the thread
    terminate_location_thread = False



    # Define a helper function to run the async function in the thread
    async def run_async_function():
        await set_location_thread(latitude, longitude)

    # Define a function to periodically check if the thread should terminate
    def check_termination():
        while not terminate_location_thread:
            asyncio.run(asyncio.sleep(1))  # Adjust sleep time as needed
        logger.info("Location Thread Terminated")

    # Create a new thread and start it
    location_thread = threading.Thread(target=lambda: asyncio.run(run_async_function()))
    location_thread.start()

    # Create a new thread for checking termination
    termination_thread = threading.Thread(target=check_termination)
    termination_thread.start()


# Function to stop the location thread
def stop_set_location_thread():
    # Set the flag to indicate that the thread should stop
    global terminate_location_thread
    terminate_location_thread = True




@app.route('/set_location', methods=['POST'])
def set_location():
    try:
        global rsd_data, rsd_host, rsd_port
        global location
        global udid, connection_type
        global ios_version

        if ios_version is not None and is_major_version_17_or_greater(ios_version):
            # Split the location string into latitude and longitude
            latitude, longitude = location.split()

            #asyncio.run(set_location_thread(latitude, longitude))
            start_set_location_thread(latitude, longitude)

            record_location_history(float(latitude), float(longitude))

            return 'Location set successfully'

        elif ios_version is not None and not is_major_version_17_or_greater(ios_version):
            global lockdown
            # Split the location string into latitude and longitude
            latitude, longitude = location.split()

            mount_developer_image()
            #asyncio.run(set_location_thread(latitude, longitude))
            start_set_location_thread(latitude, longitude)

            record_location_history(float(latitude), float(longitude))

            return 'Location set successfully'

        else:
            # Invalid ios_version
            return jsonify({'error': 'No iOS version present'})

    except Exception as e:
        error_message = str(e)
        return jsonify({'error': error_message})


@app.route('/stop_location', methods=['POST'])
async def stop_location():
    try:
        stop_set_location_thread()
        global rsd_data
        global rsd_host
        global rsd_port
        global lockdown
        global ios_version, udid, connection_type
        logger.info(f"stop set location data:  {rsd_data}")


        if udid in rsd_data_map:
            if connection_type in rsd_data_map[udid]:
                rsd_data = rsd_data_map[udid][connection_type]

                rsd_host = rsd_data['host']
                rsd_port = rsd_data['port']

            if ios_version is not None and is_major_version_17_or_greater(ios_version):
                async with RemoteServiceDiscoveryService((rsd_host, rsd_port)) as sp_rsd:
                    async with DvtProvider(sp_rsd) as dvt:
                        async with LocationSimulation(dvt) as simulation:
                            await simulation.clear()
                            logger.warning("Location Cleared Successfully")
                return 'Location cleared successfully'

            elif ios_version is not None and not is_major_version_17_or_greater(ios_version):
                async with DvtProvider(lockdown) as dvt:
                    async with LocationSimulation(dvt) as simulation:
                        await simulation.clear()
                        logger.warning("Location Cleared Successfully")
                return 'Location cleared successfully'
        return 'Location cleared successfully'
    except Exception as e:
        error_message = str(e)
        return jsonify({'error': error_message})


def get_github_version():
    try:
        # Make a request to the GitHub API to get the content of CURRENT_VERSION file
        url = f'https://raw.githubusercontent.com/{GITHUB_REPO}/main/{CURRENT_VERSION_FILE}'
        response = requests.get(url)

        response.raise_for_status()

        # Parse the content of the file
        github_version = response.text.strip()


        return github_version
    except requests.RequestException as e:

        return None


def get_github_broadcast():
    try:
        # Make a request to the GitHub API to get the content of CURRENT_VERSION file
        url = f'https://raw.githubusercontent.com/{GITHUB_REPO}/main/{BROADCAST_FILE}'
        logger.info(f"Github URL: {url}")

        response = requests.get(url, timeout=10)
        #response.raise_for_status()

        # Parse the content of the file
        github_broadcast = response.text.strip()
        logger.error(f"GITHUB BROADCAST MESSAGE:")

        return github_broadcast
    except requests.RequestException as e:

        return None


def remove_ansi_escape_codes(text):
    ansi_escape = re.compile(r'\x1b[^m]*m')
    return ansi_escape.sub('', text)

async def get_network_devices():
# you can also query network lockdown instances using the following:
    async for ip, lockdown in get_mobdev2_lockdowns():
        print(ip, lockdown.short_info)

@app.route('/list_devices')
def py_list_devices():
    try:
        connected_devices = {}

        # Retrieve all devices
        all_devices = list_devices()
        #wifi_devices = None
        #wifi_devices = asyncio.run(get_network_devices())
        logger.info(f"\n\nRaw Devices:  {all_devices}\n")
        #logger.info(f"\n\nWifi Devices:  {wifi_devices}\n")


        if wifihost:
            udid = args.udid
            logger.warning(f"Wifi requested to {wifihost}")
            logger.warning(f"udid: {udid}")
            lockdown = create_using_tcp(hostname=wifihost, identifier=udid)

            # udid = lockdown.udid
            # print("wifi udid", udid)
            info = lockdown.short_info
            logger.warning(f"Wifi Short Info: {info}")
            # Modify the info dictionary to include wifiConState
            wifi_connection_state = lockdown.enable_wifi_connections = True
            info['wifiState'] = wifi_connection_state

            # Modify the info dictionary to include user locale
            info['userLocale'] = get_user_country()

            info['ConnectionType'] = 'Network'

            # Substitute "Network" with "Wifi" in the connection_type
            connection_type = "Manual Wifi"
            # if connection_type == "Network":
            #     connection_type = "Wifi"

            # If the serial already exists in the connected_devices dictionary
            if udid in connected_devices:
                # If the connection_type already exists under the serial, append the device to the list
                if connection_type in connected_devices[udid]:
                    connected_devices[udid][connection_type].append(info)
                # If the connection_type doesn't exist under the serial, create a new list with the device
                else:
                    connected_devices[udid][connection_type] = [info]
            # If the serial is new, create a new dictionary entry with the connection_type as a list
            else:
                connected_devices[udid] = {connection_type: [info]}






        # Iterate through all devices

        for device in all_devices:
            udid = device.serial
            connection_type = device.connection_type

            # Create lockdown and info variables
            #global lockdown
            lockdown = create_using_usbmux(udid, connection_type=connection_type, autopair=True)
            info = lockdown.short_info


            wifi_connection_state = lockdown.enable_wifi_connections

            if wifi_connection_state == False:
                logger.info("Enabling Wifi Connections")
                wifi_connection_state = lockdown.enable_wifi_connections = True
                logger.info(f"Wifi Connection State: True")

            # Modify the info dictionary to include wifiConState
            info['wifiState'] = wifi_connection_state

            # Modify the info dictionary to include user locale
            info['userLocale'] = get_user_country()

            # Substitute "Network" with "Wifi" in the connection_type
            if connection_type == "Network":
                connection_type = "Wifi"

            # If the serial already exists in the connected_devices dictionary
            if udid in connected_devices:
                # If the connection_type already exists under the serial, append the device to the list
                if connection_type in connected_devices[udid]:
                    connected_devices[udid][connection_type].append(info)
                # If the connection_type doesn't exist under the serial, create a new list with the device
                else:
                    connected_devices[udid][connection_type] = [info]
            # If the serial is new, create a new dictionary entry with the connection_type as a list
            else:
                connected_devices[udid] = {connection_type: [info]}

        logger.info(f"\n\nConnected Devices: {connected_devices}\n")

        # Check if running as sudo
        if current_platform == "darwin":
            if os.geteuid() != 0:
                logger.error("*********************** WARNING ***********************")
                logger.error("Not running as Sudo, this probably isn't going to work")
                logger.error("*********************** WARNING ***********************")
        return jsonify(connected_devices)

    except ConnectionAbortedError as e:
        logger.error(f"ConnectionAbortedError occurred: {e}")
        return {"error"}

    except Exception as e:
        error_message = str(e)
        return jsonify({'error': error_message})

def clear_geoport():
    logger.info("clear any GeoPort instances")
    substring = "GeoPort"

    for process in psutil.process_iter(['pid', 'name']):
        if substring in process.info['name']:
            logger.info(f"Found process: {process.info['pid']} - {process.info['name']}")

            # Terminate the process
            process.terminate()
    else:
        logger.warning("No GeoPort found")


def clear_old_geoport():
    logger.info("clear old GeoPort instances")
    substring = "GeoPort"

    current_pid = os.getpid()

    for process in psutil.process_iter(['pid', 'name']):
        if substring in process.info['name'] and process.info['pid'] != current_pid:
            logger.info(f"Found process: {process.info['pid']} - {process.info['name']}")

            # Terminate the process
            process.terminate()


def shutdown_server():
    logger.warning("shutdown server")
    asyncio.run(stop_location())
    stop_set_location_thread()
    stop_tunnel_thread()
    cancel_async_tasks()
    terminate_threads()


    # Terminate the current process
    clear_geoport()

    logger.error("OS Kill")
    os.kill(os.getpid(), signal.SIGINT)
    list_threads()
    terminate_threads()
    logger.error("sys exit")
    os._exit(0)


def terminate_threads():
    """
    Terminate all threads.
    """
    for thread in threading.enumerate():
        if thread != threading.main_thread():
            logger.info(f"thread: {thread}")
            terminate_flag = threading.Event()
            terminate_flag.set()
            #thread.terminate()  # Terminate the thread

def list_threads():
    """
    Terminate all threads.
    """
    for thread in threading.enumerate():
        logger.info(f"thread: {thread}")
def cancel_async_tasks():
    try:
        #loop = asyncio.get_running_loop()
        tasks = asyncio.all_tasks()
        for task in tasks:
            logger.info(f"task: {task}")
            task.cancel()
    except RuntimeError as e:
        if "no running event loop" in str(e):
            logger.error("No running event loop found.")
        else:
            raise e  # Re-raise the error if it's not related to the event loop



@app.route('/exit', methods=['POST'])
def exit_app():
    logger.warning("Exit GeoPort")
    shutdown_server()
    # Send a response to the client immediately
    response = {"success": True, "message": "Server is shutting down..."}

    return jsonify(response)


#========= Background remote data (fuel / version / broadcast / country) ========
# 首页原本串行请求 4 个外网服务，弱网/代理故障时页面会卡 30 秒以上。
# 改为后台线程预取并缓存，页面渲染只读缓存，秒开。
REMOTE_REFRESH_INTERVAL = 1800  # seconds

def refresh_remote_data():
    """Prefetch all remote data used by the index page. Runs in a daemon thread."""
    while True:
        try:
            fetch_api_data(api_url)
        except Exception as e:
            logger.warning(f"Fuel data refresh failed: {e}")
        try:
            version = get_github_version()
            if version:
                global _cached_github_version
                _cached_github_version = version
        except Exception as e:
            logger.warning(f"Version check failed: {e}")
        try:
            broadcast = get_github_broadcast()
            if broadcast:
                global _cached_github_broadcast
                _cached_github_broadcast = broadcast
        except Exception as e:
            logger.warning(f"Broadcast fetch failed: {e}")
        try:
            get_user_country()  # caches into _user_country_cache
        except Exception as e:
            logger.warning(f"Country lookup failed: {e}")
        time.sleep(REMOTE_REFRESH_INTERVAL)

_cached_github_version = None
_cached_github_broadcast = None

@app.route('/')
def index():
    # global error_message
    global _cached_github_version, _cached_github_broadcast, _user_country_cache
    # All remote data comes from the background refresh thread - never block rendering
    github_version = _cached_github_version
    github_broadcast = _cached_github_broadcast
    user_locale = _user_country_cache
    logger.info(f"Country: {user_locale}")
    logger.info(f"Current platform: {platform}")
    logger.info(f"App Version = {APP_VERSION_NUMBER}")
    logger.info(f"base dir =  {base_directory}")
    logger.info(f"GitHub Version = {github_version}")

    #list_devices()
    # Compare with the locally hardcoded version
    if github_version and github_version > APP_VERSION_NUMBER:
        version_message = f"Update available. New Version is {github_version}"

    elif github_version and github_version < APP_VERSION_NUMBER:
        version_message = f"Beta Testing. App version is {APP_VERSION_NUMBER} - github is {github_version}"

    else:
        version_message = None

    return render_template('map.html', version_message=version_message, github_broadcast=github_broadcast,
                           user_locale=user_locale, app_version_num=APP_VERSION_NUMBER,
                           app_version_type=APP_VERSION_TYPE, error_message=error_message, current_platform=platform,
                           sudo_message=sudo_message)


def open_browser():
    time.sleep(2)  # Wait for the Flask app to start
    #webbrowser.open(f'http://localhost:{chosen_port}')
    browser = webbrowser.get()
    browser.open(f'http://localhost:{chosen_port}')


def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0
    # with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    #     try:
    #         s.bind((' ', port))
    #         return False  # Port is available
    #     except OSError:
    #         return True  # Port is already in use


# Define try_bind_listener_on_free_port function
def try_bind_listener_on_free_port():
    global chosen_port
    min_port = 49215
    max_port = 65535

    # Check if --port argument is provided
    if args.port:
        chosen_port = args.port
    else:
        chosen_port = flask_port

    if is_port_in_use(chosen_port):
        chosen_port = random.randint(min_port, max_port)
    logger.info(f'Serving: http://localhost:{chosen_port}')
    return chosen_port


if __name__ == '__main__':
    #create_geoport_folder()
    if is_windows:
        try:
            import pyi_splash

            pyi_splash.update_text('UI Loaded ...')
            logger.info("clear splash")
            pyi_splash.close()
        except:
            pass
        if not pyuac.isUserAdmin():
            print("Relaunching as Admin")
            pyuac.runAsAdmin()
    #else:




    chosen_port = try_bind_listener_on_free_port()

    # Prefetch remote data (fuel prices / update check / broadcast / country) in the
    # background so the index page never waits on outbound network calls
    threading.Thread(target=refresh_remote_data, daemon=True).start()

    # Check if --no-browser flag is provided
    if not args.no_browser:
        open_browser()
    else:
        logger.info("--no-browser flag passed")
        logger.info("Running without auto-browser popup")



    #threading.Thread(target=open_browser).start()

    # debug=False: Werkzeug's debugger exposes arbitrary code execution, and it
    # must never be combined with a network-visible listener. Pass --host 0.0.0.0
    # explicitly if LAN access to the UI is really needed.
    # threaded=True: without it a single half-open client connection (e.g. via a
    # system proxy) blocks the only worker and wedges the whole app.
    app.run(debug=False, use_reloader=False, port=chosen_port, host=args.host, threaded=True)




