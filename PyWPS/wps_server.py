from pathlib import Path
from pywps import Service
from pyWPS_process import TemperaturaMODISProcess
from wsgicors import CORS

processes = [TemperaturaMODISProcess()]
config_files = [str(Path(__file__).parent / "pywps.cfg")]
application = Service(processes, config_files)
application = CORS(application, headers="*", methods="GET,POST,OPTIONS", origin="*")