#!/usr/bin/python3
# -*- coding: utf-8 -*-

# Copyright (c) 2022 Christian Nilsson

from multiprocessing import Process, Pipe

from PIL import Image, ImageOps
from pyvirtualdisplay import smartdisplay

from ctypes import c_char, c_char_p, CDLL

lib_path = '/opt/a314/libcc2p.so'
try:
    cc2p_lib = CDLL(lib_path)
except Exception as e:
    print('Failed to load C chunky 2 planar: {}'.format(e))

DEBUG = True

class FrameGrabber(object):
    def __init__(self):
        self.w = 320
        self.h = 256

        self.disp = smartdisplay.SmartDisplay(size=(320, 256))
        self.disp.start()
        print(f'Display: {self.disp.new_display_var}')

        self.num_graboids = 2
        self.graboids = []
        for g in range(0, self.num_graboids):
            parent_conn, child_conn = Pipe()
            graboid = Process(target=self.framegrabber_process, args=(child_conn, g))
            graboid.start()
            self.graboids.append((parent_conn, graboid))

    def framegrabber_process(self, conn, g):
        if DEBUG: print(f'Graboid {g} started!')
        frame_num = conn.recv()
        while frame_num != None:
            if DEBUG: print(f'Graboid {g} start #{frame_num}')
            original_image = self.disp.grab(autocrop=False)

            # Keep top 4 bits of colour values. This is not really needed, but it seems
            # to lighten the CPU load enough for 25 fps playback on an RPi Zero 2
            posterized_image = ImageOps.posterize(image=original_image, bits=4)

            # Quantize image, reducing to 32 colours
            quantized_image = posterized_image.quantize(colors=32, method=Image.MEDIANCUT, dither=Image.FLOYDSTEINBERG)
            quantized_palette = quantized_image.getpalette('RGB')

            # Perform chunky-to-planar conversion
            amiga_image = self.c2p(quantized_image.tobytes(), self.w, self.h, 5)
            amiga_palette = bytearray(64)

            for c in range(0, 32):
                amiga_palette[2*c] = quantized_palette[3*c] >> 4
                amiga_palette[2*c+1] = (quantized_palette[3*c+1] & 0xf0) | (quantized_palette[3*c+2] >> 4)
            if DEBUG: print(f'Graboid {g} sending #{frame_num}')
            conn.send(amiga_palette)
            conn.send(amiga_image)
            if DEBUG: print(f'Graboid {g} sent #{frame_num}')
            frame_num = conn.recv()

    @staticmethod
    def c2p(raw, width, height, depth):
        """Call C function to perform chunky to planar conversion"""
        indexed2planar = cc2p_lib.indexed2planar
        indexed2planar.restype = None

        c_arr_in = (c_char_p)(raw)
        c_arr_out = (c_char * (width*height*depth//8))()

        indexed2planar(c_arr_in, c_arr_out, width*height, depth)
        return c_arr_out[:]

    def get_planar_frame(self, frame_number):
        if frame_number < self.num_graboids:
            if DEBUG: print(f'Faking #{frame_number}')
            amiga_palette = bytes(64)
            amiga_image = bytes(320*256//8*5)
        else:
            if DEBUG: print(f'Getting #{frame_number} from {frame_number%self.num_graboids}')
            amiga_palette = self.graboids[frame_number%self.num_graboids][0].recv()
            amiga_image = self.graboids[frame_number%self.num_graboids][0].recv()

        if DEBUG: print(f'Requesting #{frame_number} from {frame_number%self.num_graboids}')
        self.graboids[frame_number % self.num_graboids][0].send(frame_number)
        
        return amiga_palette, amiga_image
