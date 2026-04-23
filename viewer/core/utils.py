import threading

import PIL
import PIL.Image

lock = threading.Lock()


def singleton(class_):
    instances = {}

    def getinstance(*args, **kwargs):
        with lock:
            if class_ not in instances:
                instances[class_] = class_(*args, **kwargs)
            return instances[class_]

    return getinstance


def clear_queue(q):
    while not q.empty():
        q.get()


def read_in_chunks(file_object, chunk_size=1_000_000):
    while True:
        data = file_object.read(chunk_size)
        if not data:
            break
        yield data


def resize_image(img: PIL.Image, ratio=None, width=None, height=None, logger=None, width_max=False, height_max=False):
    img_width = img.size[0]
    img_height = img.size[1]

    if ratio is not None:
        width = int(img_width * ratio)
        height = int(img_height * ratio)

    if img_width > img_height:
        wpercent = (width / float(img_width))
        hsize = int((float(img_height) * float(wpercent)))
        target_width = width
        target_height = hsize
    else:
        hpercent = (height / float(img_height))
        wsize = int((float(img_width) * float(hpercent)))
        target_width = wsize
        target_height = height

    if width_max and target_width > width:
        w_scale = width / target_width
    else:
        w_scale = 1

    if height_max and target_height > height:
        h_scale = height / target_height
    else:
        h_scale = 1

    scale = w_scale * h_scale

    target_height = int(target_height * scale)
    target_width = int(target_width * scale)

    if logger:
        logger.debug("Resizing image from {}x{} to {}x{}, canvas {}x{}".format(
            img_width, img_height, target_width, target_height, width, height))
    img = img.resize((target_width, target_height), PIL.Image.Resampling.BICUBIC, reducing_gap=2)
    return img
