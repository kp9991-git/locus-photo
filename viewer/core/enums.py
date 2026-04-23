from enum import Enum

class MetaTagName(Enum):
    Orientation = "Orientation"
    GPSAltitude = "GPS Altitude"
    GPSLongitude = "GPS Longitude"
    GPSLatitude = "GPS Latitude"

class MetaTagGroup(Enum):
    Composite = "Composite"
    EXIF = "EXIF"