''' Based on script by frankbags@https://gist.github.com/frankbags/c85d37d9faff7bce67b6d18ec4e716ff '''
''' 2023 12 04: Extended by Christian Vick: Handle MAXZ, too. '''

import re  # To perform the search and replace.
from ..Script import Script

class KlipperPrintArea(Script):
    
    def getSettingDataString(self):
        return """{
            "name": "Klipper print area mesh",
            "key": "KlipperPrintArea",
            "metadata": {},
            "version": 2,
            "settings":{}
        }"""

    def execute(self, data):
        minMaxXYZ = {'MINX': 0, 'MINY': 0, 'MAXX': 0, 'MAXY': 0, 'MAXZ': 0}
        startGcodeLineData = ''
        for layerNumber, layerData in enumerate(data):
            # search for print area boundary
            for k, v in minMaxXYZ.items():
                result = re.search(str(k)+":(\d*\.?\d*)", layerData)
                if result is not None:
                    minMaxXYZ[k] = result.group(1)
            # search for set print area macro
            areaStartGcode = re.search(
                ".*%(MINX|MAXX|MINY|MAXY|MAXZ)%.*", layerData)
            # replace print area template
            if areaStartGcode is not None:
                if not startGcodeLineData:
                    startGcodeLineData = layerData
                for k, v in minMaxXYZ.items():
                    pattern3 = re.compile('%' + k + '%')
                    startGcodeLineData = re.sub(
                        pattern3, v, startGcodeLineData)
                data[layerNumber] = startGcodeLineData
        return data


# start g-code format
# START_PRINT EXTRUDER_TEMP={material_print_temperature_layer_0} BED_TEMP={material_bed_temperature_layer_0} AREA_START=%MINX%,%MINY% AREA_END=%MAXX%,%MAXY% MODEL_HEIGHT=%MAXZ%