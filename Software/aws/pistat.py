#!/usr/bin/python3
# -*- coding: utf-8 -*-

# Copyright (c) 2021 Niklas Ekström, Christian Nilsson


import awslib
import queue
from ctypes import c_char, c_char_p, CDLL

import pygame

from boing import BoingBall
from statdisplay import StatDisplay

from pyvirtualdisplay import Display

lib_path = './cc2p.so'
try:
    cc2p_lib = CDLL(lib_path)
except Exception as e:
    print('Failed to load C chunky 2 planar: {}'.format(e))

def c2p(raw, width, height, depth):
    """Call C function to perform chunky to planar conversion"""
    indexed2planar = cc2p_lib.indexed2planar
    indexed2planar.restype = None

    c_arr_in = (c_char_p)(raw)
    c_arr_out = (c_char * (width*height*depth//8))()

    indexed2planar(c_arr_in, c_arr_out, width*height, depth)
    return c_arr_out[:]




class ConnectionCallbacks(object):
    # Take care as these callbacks are executed in a separate thread!

    # There is currently no synchronization in awslib,
    # so you should not invoke connection methods on this thread.

    # An option is to forward the notification to the main thread through a queue or socketpair.
    def connection_closed(self, conn):
        #print('Connection closed')
        pass

    def event_close_window(self, conn, wid):
        event_queue.put(b'C')

    def event_flip_done(self, conn, wid):
        event_queue.put(b'F')


def main():
    global event_queue
    event_queue = queue.Queue()

    conn = awslib.connect(ConnectionCallbacks())
    if conn is None:
        print("Failed to connect to AWS")
        exit(-1)

    print("Connected to AWS")

    w, h, d, pal = conn.get_wb_screen_info()
    print('Screen info:')
    print('  width={}, height={}, depth={}'.format(w, h, d))
    print('  palette={}'.format([('%04x' % c) for c in pal]))

    wid, size = conn.open_window(100, 100, 128, 70, 'A314 Stats')
    if wid == None:
        print('Failed to open window')
        exit(-1)

    Aw, Ah, Ad = size
    Aw = (Aw + 15) & ~15
    draw_size = (Aw, Ah, Ad)

    print('Window opened successfully, wid={}'.format(wid))
    print('  width={}, height={}, depth={}'.format(*draw_size))

    with Display() as disp:
        # Create a tiny display window, not used but pygame really wants it.
        pygame.init()
        screen = pygame.display.set_mode((1,1))

        # Use the pygame tick to limit number of updates
        clock = pygame.time.Clock()

        # Set up the drawing surface, this is the content of the Amiga window.
        surface = pygame.Surface((Aw, Ah), depth=8)

        # Clear palette
        surface.set_palette(256 * ((0,0,0),))

        # Build a palette for pygame from the WB palette and apply it.
        palette = []
        for c in pal:
            r = c >> 4 & 0xf0
            g = c & 0xf0
            b = c << 4 & 0xf0
            palette.append((r,g,b))
        surface.set_palette(palette)

        sd = StatDisplay(surface)
        bb = BoingBall(surface)

        waiting_flip = False
        done = False
        while not done:
            # Fill the surface with color 0, that is the WB background color.
            # Then draw the classic Boing Ball followed by the text on top.
            surface.fill(0)
            bb.update()
            sd.update()

            # Get the raw graphics data from the surface and perform chunky-2-planar
            # conversion before copying to Amiga memory.
            buffer = c2p(surface.get_view('0').raw, *draw_size)
            while waiting_flip or not event_queue.empty():
                e = event_queue.get()
                if e == b'C':
                    conn.close()
                    pygame.quit()
                    done = True
                elif e == b'F':
                    waiting_flip = False

            if not done:
                conn.copy_flip_window(wid, buffer)
                waiting_flip = True

            # Limit to 50 fps. Only barely relevant on a Pi Zero :)
            clock.tick(50)

if __name__ == "__main__":
    main()
