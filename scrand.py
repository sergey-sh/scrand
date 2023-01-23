import time
import threading
import io
from PIL import Image
from argparse import ArgumentParser
from ppadb.client import Client as AdbClient
import PySimpleGUI as sg
from ppadb.keycode import (
    KEYCODE_APP_SWITCH, KEYCODE_BACK, KEYCODE_HOME, KEYCODE_PAGE_DOWN, KEYCODE_PAGE_UP,
    KEYCODE_POWER,
)

FREQ_DEFAULT = 2
FREQ_TOUCHPAD = 10
EVENT_TOUCHPAD = '/dev/input/event0'


def open_adb_client():
    client = AdbClient(host="127.0.0.1", port=5037)
    devices = client.devices()
    if len(devices) < 1:
        print('Not found android device')
        exit(1)

    device = devices[0]
    print(f'Connect to android  device: {device.serial}')
    image = device.screencap()

    return client, device, image


def read_image_size(image):
    img = Image.open(io.BytesIO(bytes(image)))
    return img.width, img.height


def thread_device_screencap(thread_name, window, device, timeout, device_thread_message):
    while not device_thread_message.get('stop'):
        try:
            t = time.time()
            image = device.screencap()
            window.write_event_value(thread_name, image)
            d = timeout - (time.time() - t) / 1000
            if 0 < d < timeout:
                time.sleep(d)
        except Exception as e:
            print(e)
            return


class AdbTouchpad:

    def __init__(self, freq, verbose=False):
        self.freq = freq
        self.timeout = 1/freq
        self.lock = threading.Lock()
        self.verbose = verbose

        self.touchpad_tap = False
        self.touchpad_coordinate_x = 0
        self.touchpad_coordinate_y = 0
        self.touchpad_swipe = False
        self.touchpad_swipe_horizontal = False

    def tap(self, x, y):
        try:
            self.lock.acquire()
            self.touchpad_tap = True
            self.touchpad_coordinate_x = x
            self.touchpad_coordinate_y = y
        finally:
            self.lock.release()

    def swipe(self, horizontal=True):
        try:
            self.lock.acquire()
            self.touchpad_swipe = True
            self.touchpad_swipe_horizontal = horizontal
        finally:
            self.lock.release()

    def get_cmds(self):
        return None

    def run_loop(self, device):
        cmds = self.get_cmds()
        if cmds:
            for cmd in cmds:
                if isinstance(cmd, float) or isinstance(cmd, int):
                    time.sleep(cmd)
                elif isinstance(cmd, str):
                    device.shell(cmd)
                if self.verbose:
                    print(cmd)

    def run(self, device, device_thread_message):
        while not device_thread_message.get('stop'):
            self.run_loop(device)
            time.sleep(self.timeout)


class AdbTouchpadIncreaseLatencyUseSendevent(AdbTouchpad):

    def get_cmds(self):
        cmds = []
        try:
            self.lock.acquire()
            if self.touchpad_tap:
                cmds.append(
                    f'sendevent {EVENT_TOUCHPAD} 3 57 0;'
                    f'sendevent {EVENT_TOUCHPAD} 3 53 {self.touchpad_coordinate_x};'
                    f'sendevent {EVENT_TOUCHPAD} 3 54 {self.touchpad_coordinate_y};'
                    f'sendevent {EVENT_TOUCHPAD} 0 0 0;'
                    f'sendevent {EVENT_TOUCHPAD} 3 57 -1;sendevent {EVENT_TOUCHPAD} 0 0 0'
                )
                self.touchpad_tap = False
            if self.touchpad_swipe:
                cmds.append(
                    f'sendevent {EVENT_TOUCHPAD} 3 57 0;'
                    f'sendevent {EVENT_TOUCHPAD} 3 53 {self.touchpad_coordinate_x};'
                    f'sendevent {EVENT_TOUCHPAD} 3 54 {self.touchpad_coordinate_y};'
                    f'sendevent {EVENT_TOUCHPAD} 0 0 0'
                )
                cmds.append(1)
                cmds.append(
                    f'sendevent {EVENT_TOUCHPAD} 3 57 0;'
                    f'sendevent {EVENT_TOUCHPAD} 3 53 {self.touchpad_coordinate_x + 200 if self.touchpad_swipe_horizontal else self.touchpad_coordinate_x};'
                    f'sendevent {EVENT_TOUCHPAD} 3 54 {self.touchpad_coordinate_y + 200 if not self.touchpad_swipe_horizontal else self.touchpad_coordinate_y};'
                    f'sendevent {EVENT_TOUCHPAD} 0 0 0;'
                    f'sendevent {EVENT_TOUCHPAD} 3 57 -1;sendevent {EVENT_TOUCHPAD} 0 0 0'
                )
                self.touchpad_swipe = False
        finally:
            self.lock.release()

        return cmds


class AdbTouchpadIncreaseLatencyUseInput(AdbTouchpad):

    def get_cmds(self):
        cmds = []
        try:
            self.lock.acquire()
            if self.touchpad_tap:
                cmds.append(
                    f'input touchscreen tap {self.touchpad_coordinate_x} {self.touchpad_coordinate_y}'
                )
                self.touchpad_tap = False
            if self.touchpad_swipe:
                cmds.append(
                    f'input touchscreen swipe {self.touchpad_coordinate_x} '
                    f'{self.touchpad_coordinate_y} '
                    f'{self.touchpad_coordinate_x + 200 if self.touchpad_swipe_horizontal else self.touchpad_coordinate_x} '
                    f'{self.touchpad_coordinate_y + 200 if not self.touchpad_swipe_horizontal else self.touchpad_coordinate_y} '
                    f' 1000'
                )
                self.touchpad_swipe = False
        finally:
            self.lock.release()

        return cmds


def thread_device_cmd(thread_name, device, device_thread_message, touchpad):
    touchpad.run(device, device_thread_message)


def main(args, timeout):

    client, device, image = open_adb_client()

    width, height = read_image_size(image)

    layout = [
        [sg.Graph(
            canvas_size=(width, height), graph_top_right=(width, 0), graph_bottom_left=(0, height),
            key="-GRAPH-", enable_events=True
            ), ],
        [
            sg.Button('On|Off', size=(10, 1), key="-BTN-ON-"),
            sg.Button('Home', size=(10, 1), key="-BTN-HOME-"),
            sg.Button('Back', size=(10, 1), key="-BTN-BACK-"),
        ],
        [
            sg.Button('App', size=(10, 1), key="-BTN-APPSWITCH-"),
            sg.Button('Setting', size=(10, 1), key="-BTN-SETTINGS-"),
            sg.Button('Swipe H', size=(10, 1), key="-SWIPE-H-"),
            sg.Button('Swipe V', size=(10, 1), key="-SWIPE-V-"),
        ],
    ]

    window = sg.Window(f'Android: {device.serial}', layout, return_keyboard_events=True, finalize=True)
    graph = window["-GRAPH-"]  # type: sg.Graph
    image_id = graph.draw_image(data=bytes(image), location=(0, 0))

    device_thread_message = {'stop': False}

    device_thread = threading.Thread(target=thread_device_screencap, args=('device_screencap', window, device, timeout, device_thread_message), daemon=True)
    device_thread.start()

    touchpad_use_input = 'swipe' in device.shell('input')
    touchpad = AdbTouchpadIncreaseLatencyUseInput(FREQ_TOUCHPAD) \
        if touchpad_use_input else AdbTouchpadIncreaseLatencyUseSendevent(FREQ_TOUCHPAD)

    device_thread_cmd = threading.Thread(target=thread_device_cmd, args=('device_cmd', device, device_thread_message, touchpad), daemon=True)
    device_thread_cmd.start()

    while True:
        event, values = window.read()
        if event == 'Exit' or event == sg.WIN_CLOSED:
            device_thread_message['stop'] = True
            return
        elif event == 'device_screencap':
            img = values.get('device_screencap')
            if img:
                new_image_id = graph.draw_image(data=bytes(img), location=(0, 0))
                if image_id:
                    graph.delete_figure(image_id)
                    image_id = new_image_id
                window.refresh()
        elif event == '-GRAPH-':
            x, y = values["-GRAPH-"]
            touchpad.tap(x, y)
        elif event == '-BTN-ON-':
            device.shell(f'input keyevent --longpress {KEYCODE_POWER}')
        elif event == '-BTN-HOME-':
            device.shell(f'input keyevent {KEYCODE_HOME}')
        elif event == '-BTN-BACK-':
            device.shell(f'input keyevent {KEYCODE_BACK}')
        elif event == '-BTN-APPSWITCH-':
            device.shell(f'input keyevent {KEYCODE_APP_SWITCH}')
        elif event == '-BTN-SETTINGS-':
            device.shell(f'am start com.android.settings')
        elif event == '-SWIPE-H-':
            touchpad.swipe(True)
        elif event == '-SWIPE-V-':
            touchpad.swipe(False)
        elif event.startswith('Up:'):
            device.shell(f'input keyevent {KEYCODE_PAGE_UP}')
        elif event.startswith('Down:'):
            device.shell(f'input keyevent {KEYCODE_PAGE_DOWN}')

        if args.v:
            print(event)


def parse_arguments():
    parser = ArgumentParser(
        prog='Remote Desktop for Android',
        description='Control Android device over USB connection',
        epilog='')

    parser.add_argument('-f', '--freq', type=int, default=FREQ_DEFAULT, help=f'Frequency refresh screen at seconds default {FREQ_DEFAULT}')
    parser.add_argument('-v', action='store_true', help='More detailed log')

    return parser.parse_args()


if __name__ == '__main__':
    args = parse_arguments()
    timeout = round(1/args.freq) if args.freq > 0 else 1/FREQ_DEFAULT

    main(args, timeout)
