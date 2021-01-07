import pygame
import psutil
import subprocess
import time

class StatDisplay(object):
    UPDATE_INTERVAL = 3

    def __init__(self, surface):
        self.last_update = 0
        self.surface = surface

        # Make a copy of the real surface to buffer the drawn text
        self.textsurface = surface.copy()
        self.textsurface.set_colorkey(0)

        # Load an image containing a 7x9 bitmap font.
        self.fontimg = pygame.image.load('pixel_font_basic_latin_ascii.png')

    # Draws a series of characters in the requested color onto a surface.
    # This should really be done with a blitlist but there is a bug in
    # pygame 1.9.4 when using blitlists with areas...
    def _blitchr(self, surface, position, c):
        if ord(c) < 32 or ord(c) > 126:
            return
        row = (ord(c) - 32) // 16
        col = (ord(c) - 32) % 16
        surface.blit(self.fontimg, position, area=((7*col,9*row),(7,9)))

    def blitstr(self, surface, position, string, color):
        self.fontimg.set_palette_at(1, color)
        x, y = position
        for c in range(len(string)):
            self._blitchr(surface, (x+(7*c), y), string[c])

    @staticmethod
    def cpu_temp():
        with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
            cputemp = int(f.read().strip())/1000
        return cputemp

    @staticmethod
    def wifi_ssid():
        try:
            output = subprocess.check_output(['iwgetid'])
            ssid = str(output).split('"')[1]
        except Exception:
            ssid = ''
        return ssid

    @staticmethod
    def wifi_quality():
        with open('/proc/net/wireless', 'r') as f:
            lines = f.readlines()
            for l in lines:
                if 'wlan0' in l:
                    q = float(l.split()[2])
                    return int(q / 70 * 100)
        return 0

    def update(self):
        # Don't update the values too often, it makes it harder to read. Also,
        # keeping a prepared surface with the current values speeds up drawing.
        if time.monotonic() > self.last_update + self.UPDATE_INTERVAL:
            self.stat_strings = [
                'CPU Load:{:5.1f} %'.format(psutil.cpu_percent()),
                'CPU Temp: {:4.1f} C'.format(self.__class__.cpu_temp()),
                'WiFi AP:',
                '{:>16s}'.format(self.__class__.wifi_ssid()),
                'Quality: {:5d} %'.format(self.__class__.wifi_quality())
                ]
            self.last_update = time.monotonic()

            # Clear the text surface to all transparent
            self.textsurface.fill(0)

            # Draw the text on the surface in black
            for i in range(len(self.stat_strings)):
                self.blitstr(self.textsurface, (3, (i*10)+3), self.stat_strings[i], (0,0,0))
        # Draw the text surface onto the real surface.
        self.surface.blit(self.textsurface, (0,0))
