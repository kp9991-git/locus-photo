from typing import Dict
from viewer.core.enums import MetaTagName

class ImageContainer:

    def __init__(self, img, meta_data_num: Dict[MetaTagName, float]):
        self.img = img
        self.meta_data_num = meta_data_num

    def get_rotation_angle_cw(self):
        angle = 0
        if MetaTagName.Orientation in self.meta_data_num:
            if self.meta_data_num[MetaTagName.Orientation] == 3:
                angle = 180
            elif self.meta_data_num[MetaTagName.Orientation] == 6:
                angle = 270
            elif self.meta_data_num[MetaTagName.Orientation] == 8:
                angle = 90
        return angle
