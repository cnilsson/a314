#!/usr/bin/python3
# -*- coding: utf-8 -*-

# Copyright (c) 2021 Christian Nilsson

import sys
import awslib
import queue
import threading
import struct
from ctypes import c_char, c_char_p, CDLL

import pygame

from pyvirtualdisplay import Display
import Xlib.display
import os

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

# Some silly hacked together eyes to show Intuition events
class Peyes(object):
    def __init__(self, surface):
        self.last_update = 0
        self.surface = surface
        self.pokecnt_l = 0
        self.pokecnt_r = 0

    def update(self, mouseX, mouseY, click):
        self.surface.fill(0)
        centerL = (45, 45)
        centerR = (137, 45)

        pupilL = (centerL[0]+10 + (mouseX-centerL[0]-10) // ((mouseX > centerL[0])*15 + 15), centerL[1] + (mouseY-centerL[1]) // 15)
        pupilR = (centerR[0]-10 + (mouseX-centerR[0]+10) // ((mouseX < centerR[0])*15 + 15), centerR[1] + (mouseY-centerR[1]) // 15)

        if click:
            poke_left = ( pow(mouseX - centerL[0], 2) + pow(mouseY - centerL[1], 2) < pow(40, 2) )
            poke_right = ( pow(mouseX - centerR[0], 2) + pow(mouseY - centerR[1], 2) < pow(37, 2) )

        if click and poke_left:
            pygame.draw.line(self.surface, (0, 0, 0), (centerL[0]-25, centerL[1]-20), (centerL[0]+30, centerL[1]), 2)
            pygame.draw.line(self.surface, (0, 0, 0), (centerL[0]-30, centerL[1]), (centerL[0]+30, centerL[1]), 2)
            pygame.draw.line(self.surface, (0, 0, 0), (centerL[0]-25, centerL[1]+20), (centerL[0]+30, centerL[1]), 2)
            self.pokecnt_l += 1
        else:
            if self.pokecnt_l > 5*25:
                pygame.draw.circle(self.surface, (255, 100, 100), centerL, 40)
            else:
                pygame.draw.circle(self.surface, (255, 255, 255), centerL, 40)
            pygame.draw.circle(self.surface, (0, 0, 0), pupilL, 10)

        if click and poke_right:
            pygame.draw.line(self.surface, (0, 0, 0), (centerR[0]+25, centerR[1]-20), (centerR[0]-30, centerR[1]), 2)
            pygame.draw.line(self.surface, (0, 0, 0), (centerR[0]+30, centerR[1]), (centerR[0]-30, centerR[1]), 2)
            pygame.draw.line(self.surface, (0, 0, 0), (centerR[0]+25, centerR[1]+20), (centerR[0]-30, centerR[1]), 2)
            self.pokecnt_r += 1
        else:
            if self.pokecnt_r > 5*25:
                pygame.draw.circle(self.surface, (255, 100, 100), centerR, 37)
            else:
                pygame.draw.circle(self.surface, (255, 255, 255), centerR, 37)
            pygame.draw.circle(self.surface, (0, 0, 0), pupilR, 8)

class ConnectionCallbacks(object):
    # Take care as these callbacks are executed in a separate thread!

    # There is currently no synchronization in awslib,
    # so you should not invoke connection methods on this thread.

    # An option is to forward the notification to the main thread through a queue or socketpair.
    def connection_closed(self, conn):
        #print('Connection closed')
        pass

    def event_close_window(self, conn, wid):
        event_queue.put(struct.pack('=B', awslib.AWS_CLIENT_EVENT_CLOSE_WINDOW))

    def event_flip_done(self, conn, wid):
        waiting_flip.release()

    def event_user_input(self, conn, msg):
        e, wid = struct.unpack_from('=BH', msg, 0)
        if e == awslib.AWS_CLIENT_EVENT_MOUSE_MOVE:
            mouseX, mouseY = struct.unpack_from('=hh', msg, 3)
            newevent = pygame.event.Event(pygame.MOUSEMOTION, pos=[mouseX, mouseY])
            pygame.event.post(newevent)
        elif e == awslib.AWS_CLIENT_EVENT_MOUSE_BUTTONS:
            action, mouseX, mouseY = struct.unpack_from('=Bhh', msg, 3)
            newevent = pygame.event.Event(pygame.MOUSEMOTION, pos=[mouseX, mouseY])
            pygame.event.post(newevent)
            if action == awslib.AWS_CLIENT_EVENT_MOUSE_LEFT_DOWN:
                newevent = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1)
            elif action == awslib.AWS_CLIENT_EVENT_MOUSE_LEFT_UP:
                newevent = pygame.event.Event(pygame.MOUSEBUTTONUP, button=1)
            elif action == awslib.AWS_CLIENT_EVENT_MOUSE_RIGHT_DOWN:
                newevent = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=3)
            elif action == awslib.AWS_CLIENT_EVENT_MOUSE_RIGHT_UP:
                newevent = pygame.event.Event(pygame.MOUSEBUTTONUP, button=3)
            elif action == awslib.AWS_CLIENT_EVENT_MOUSE_MIDDLE_DOWN:
                newevent = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=2)
            elif action == awslib.AWS_CLIENT_EVENT_MOUSE_MIDDLE_UP:
                newevent = pygame.event.Event(pygame.MOUSEBUTTONUP, button=2)
            pygame.event.post(newevent)

def main():
    global event_queue
    event_queue = queue.Queue()
    global waiting_flip
    waiting_flip = threading.Lock()

    disp = Display().start()
    pygame.init()

    conn = awslib.connect(ConnectionCallbacks())
    if conn is None:
        print("Failed to connect to AWS")
        exit(-1)

    print("Connected to AWS")

    w, h, d, pal = conn.get_wb_screen_info()
    print('Screen info:')
    print('  width={}, height={}, depth={}'.format(w, h, d))
    print('  palette={}'.format([('%04x' % c) for c in pal]))

    wid, size = conn.open_window(0, 11, 192, 100, 'Peyes')
    if wid == None:
        print('Failed to open window')
        exit(-1)

    Aw, Ah, Ad = size
    Aw = (Aw + 15) & ~15
    draw_size = (Aw, Ah, Ad)

    print('Window opened successfully, wid={}'.format(wid))
    print('  width={}, height={}, depth={}'.format(*draw_size))

    # Create a tiny display window, not used but pygame really wants it.
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

    peyes = Peyes(surface)

    mouseX = 0
    mouseY = 0
    click = False
    done = False
    while True:
        while not event_queue.empty():
            e = event_queue.get()
            event = e[0]
            if event == awslib.AWS_CLIENT_EVENT_CLOSE_WINDOW:
                conn.close()
                pygame.quit()
                disp.stop()
                done = True
        if done:
            break

        for event in pygame.event.get():
            if event.type == pygame.MOUSEMOTION:
                mouseX, mouseY = event.pos
            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:
                    click = True
            elif event.type == pygame.MOUSEBUTTONUP:
                if event.button == 1:
                    click = False

        # Prepare the surface and get the raw graphics data. Perform
        # chunky-2-planar conversion before copying to Amiga memory.
        peyes.update(mouseX, mouseY, click)
        gfxbuffer = c2p(surface.get_view('0').raw, *draw_size)

        waiting_flip.acquire()
        conn.copy_flip_window(wid, gfxbuffer)

        # Limit to 25 fps.
        clock.tick(25)

if __name__ == "__main__":
    main()
